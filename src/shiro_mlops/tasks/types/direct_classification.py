"""Direct classification task type: one LightGBM classifier answers every lead hour at once.

Used by the high-load alert: each row pairs what is known at an
anchor hour (its load, load lags and rolling statistics, and the high-load
threshold) with one target hour's calendar, weather and lead time. Unlike the
recursive strategy, no forecast output is fed back in. Models are persisted as
LightGBM's native text format plus JSON metadata (ADR-0010).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveInt
from sklearn.metrics import f1_score, precision_score, recall_score

from shiro_mlops.core.constants import (
    DATETIME_COL,
    HOURS_PER_DAY,
    LOAD_MW_COL,
    MAX_HORIZON_HOURS,
)
from shiro_mlops.features.transformers import create_calendar_features
from shiro_mlops.tasks.types.base import (
    HealthAssessment,
    HealthStatus,
    HistoryCoverage,
    InputRequirements,
    PredictionData,
    Trained,
    TrainingData,
    WeatherEchoingItem,
    WeatherInput,
    require_trained_recipe,
    split_at_validation,
)
from shiro_mlops.tasks.types.lightgbm_common import (
    LIGHTGBM_BASE_PARAMS,
    LightGBMParams,
    NativeBoosterFiles,
)
from shiro_mlops.tasks.types.metadata import ModelFormat

if TYPE_CHECKING:
    import lightgbm as lgb

TASK_TYPE_NAME = "direct_classification"
MODEL_FILES = NativeBoosterFiles(ModelFormat(TASK_TYPE_NAME, version=1))
ANCHOR_COL = "anchor"
ANCHOR_LOAD_COL = f"anchor_{LOAD_MW_COL}"
LEAD_HOURS_COL = "lead_hours"
THRESHOLD_COL = "threshold_mw"
LABEL_COL = "is_high_load"
PROBABILITY_COL = "probability"
# 視界上限與 API 接受的最長 horizon 一致，單一模型才能涵蓋任何請求的每個小時。
MAX_LEAD_HOURS = MAX_HORIZON_HOURS
# 以機率 0.5 判定是否預警，與 LightGBM 二元分類的預設決策界線一致。
ALERT_PROBABILITY = 0.5
METRIC_NAMES = ("precision", "recall", "f1")
NON_FEATURE_COLUMNS = frozenset({ANCHOR_COL, DATETIME_COL, LOAD_MW_COL, LABEL_COL})
FIXED_LIGHTGBM_PARAMS: dict[str, Any] = {**LIGHTGBM_BASE_PARAMS, "objective": "binary"}
# WHY-NOT(FEATURE_DTYPE): 不沿用 float64：每個錨點展開 168 列，一年逐時負載即超過百萬列，
# float32 讓特徵表減半；負載數萬 MW 在 float32 下的解析度仍小於 0.01 MW。
FEATURE_DTYPE = np.float32


class HighLoadThresholdParams(BaseModel):
    """How the high-load threshold is derived from load known at the anchor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_days: PositiveInt
    quantile: float = Field(gt=0.0, lt=1.0)

    @property
    def window_hours(self) -> int:
        return self.window_days * HOURS_PER_DAY


class DirectClassificationParams(BaseModel):
    """Threshold rule, anchor feature recipe and model hyperparameters from the task definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: HighLoadThresholdParams
    lags: list[PositiveInt] = Field(min_length=1)
    rolling_windows: list[PositiveInt] = Field(min_length=1)
    # 放假日特徵（GLOSSARY）：依目標小時的日期判定，預設關閉以維持既有特徵集。
    day_off: bool = False
    model: LightGBMParams

    @property
    def lookback_hours(self) -> int:
        """History that covers the threshold window plus the longest lag or rolling window."""
        return self.threshold.window_hours + max(*self.lags, *self.rolling_windows)


class DirectClassificationPrediction(WeatherEchoingItem):
    """One served alert hour: the verdict, its probability and threshold, served with the weather."""

    datetime: str
    is_high_load: bool
    probability: float
    threshold_mw: float


class DirectClassificationHealth(BaseModel):
    """Monitoring floors read from the task definition's ``[health]`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_precision: float = Field(ge=0.0, le=1.0)
    min_recall: float = Field(ge=0.0, le=1.0)
    min_f1: float = Field(ge=0.0, le=1.0)


class DirectClassification:
    """Task type adapter for direct-strategy binary classification over a horizon."""

    name: ClassVar[str] = TASK_TYPE_NAME
    params_model: ClassVar[type[DirectClassificationParams]] = DirectClassificationParams
    prediction_item: ClassVar[type[BaseModel]] = DirectClassificationPrediction
    health_model: ClassVar[type[DirectClassificationHealth]] = DirectClassificationHealth

    def requirements(self, params: DirectClassificationParams) -> InputRequirements:
        return InputRequirements(
            weather=WeatherInput.FORECAST,
            lookback_hours=params.lookback_hours,
            history_coverage=HistoryCoverage.complete(params.threshold.window_hours),
        )

    def train(self, params: DirectClassificationParams, data: TrainingData) -> Trained:
        """Label every (anchor, lead) pair, fit on targets before the split, evaluate after it."""
        fitting_rows, validation_rows = split_at_validation(
            training_rows(params, data), data.validation_start
        )
        model = DirectClassificationModel.fit(params, fitting_rows, data.weather_columns)
        return Trained(model=model, metrics=model.evaluate(validation_rows))

    def load(
        self, directory: Path, params: DirectClassificationParams, weather_fields: Sequence[str]
    ) -> DirectClassificationModel:
        model = DirectClassificationModel.load(directory)
        require_trained_recipe(
            directory,
            trained=_recipe(model.params, model.weather_columns),
            declared=_recipe(params, weather_fields),
        )
        return model

    def assess_health(
        self, thresholds: DirectClassificationHealth, metrics: Mapping[str, float]
    ) -> HealthAssessment:
        """Healthy only while every metric reaches its floor; a missing metric warns."""
        verdicts = []
        for metric in METRIC_NAMES:
            floor = getattr(thresholds, f"min_{metric}")
            if metric not in metrics:
                return HealthAssessment(
                    HealthStatus.WARNING, f"No {metric} metric to compare with min_{metric}={floor}"
                )
            value = float(metrics[metric])
            if value < floor:
                return HealthAssessment(
                    HealthStatus.WARNING, f"{metric}={value:.4g} < min_{metric}={floor}"
                )
            verdicts.append(f"{metric}={value:.4g} >= min_{metric}={floor}")
        return HealthAssessment(HealthStatus.HEALTHY, "; ".join(verdicts))


class DirectClassificationModel:
    """Fitted LightGBM binary booster plus the recipe that shaped its rows."""

    def __init__(
        self,
        booster: lgb.Booster,
        *,
        params: DirectClassificationParams,
        feature_names: list[str],
        weather_columns: list[str],
    ):
        self.booster = booster
        self.params = params
        self.feature_names = feature_names
        self.weather_columns = weather_columns

    @classmethod
    def fit(
        cls,
        params: DirectClassificationParams,
        rows: pd.DataFrame,
        weather_columns: list[str],
    ) -> DirectClassificationModel:
        if rows[LABEL_COL].nunique() < 2:
            raise ValueError(
                "Training labels contain a single class; the high-load threshold never "
                "separates the training rows, so no classifier can be fitted."
            )
        # WHY-NOT(lgb): 用到時才 import；lightgbm 4.7.0 在 python -OO 下一 import 就崩潰，
        # 放在模組頂層會讓只讀任務設定的 CLI（smoke check 的 --help）在解析參數前就失敗。
        import lightgbm as lgb

        feature_names = [column for column in rows.columns if column not in NON_FEATURE_COLUMNS]
        classifier = lgb.LGBMClassifier(**FIXED_LIGHTGBM_PARAMS, **params.model.model_dump())
        classifier.fit(rows[feature_names], rows[LABEL_COL].astype(int))
        return cls(
            classifier.booster_,
            params=params,
            feature_names=feature_names,
            weather_columns=weather_columns,
        )

    def evaluate(self, validation_rows: pd.DataFrame) -> dict[str, float]:
        """Precision, recall and F1 of the alert verdict on out-of-time rows; none without rows."""
        if validation_rows.empty:
            return {}
        actual = validation_rows[LABEL_COL].astype(int)
        predicted = self._probabilities(validation_rows) >= ALERT_PROBABILITY
        return {
            "precision": float(precision_score(actual, predicted, zero_division=0)),
            "recall": float(recall_score(actual, predicted, zero_division=0)),
            "f1": float(f1_score(actual, predicted, zero_division=0)),
        }

    def predict(self, data: PredictionData) -> pd.DataFrame:
        """One row per weather hour, in the weather's order, as the generic endpoint requires."""
        anchor = pd.Timestamp(data.anchor)
        known = _anchor_features(self.params, _load_series(data.load_history)).loc[[anchor]]
        if known[THRESHOLD_COL].isna().any():
            raise ValueError(
                f"Load history has fewer than {self.params.threshold.window_hours} hours in "
                f"the {self.params.threshold.window_days}-day high-load threshold window "
                f"ending at anchor {anchor.isoformat()}"
            )
        targets = pd.DatetimeIndex(pd.to_datetime(data.weather[DATETIME_COL]))
        the_one_anchor = np.zeros(len(targets), dtype=int)
        weather_in_order = np.arange(len(targets))
        rows = _target_rows(
            known,
            the_one_anchor,
            targets,
            _TargetWeather(data.weather[self.weather_columns], weather_in_order),
            self.params.day_off,
        )
        _require_trained_leads(rows[LEAD_HOURS_COL].to_numpy())
        probability = self._probabilities(rows)
        return pd.DataFrame(
            {
                DATETIME_COL: rows[DATETIME_COL],
                LABEL_COL: [bool(value) for value in probability >= ALERT_PROBABILITY],
                PROBABILITY_COL: probability,
                THRESHOLD_COL: float(known[THRESHOLD_COL].iloc[0]),
            }
        )

    def _probabilities(self, rows: pd.DataFrame) -> pd.Series:
        return pd.Series(self.booster.predict(rows[self.feature_names]), index=rows.index)

    def save(self, directory: Path) -> None:
        metadata = {
            "params": self.params.model_dump(),
            "max_lead_hours": MAX_LEAD_HOURS,
            "feature_names": self.feature_names,
            "weather_columns": self.weather_columns,
        }
        MODEL_FILES.save(directory, self.booster, metadata)

    @classmethod
    def load(cls, directory: Path) -> DirectClassificationModel:
        booster, metadata = MODEL_FILES.load(directory)
        return cls(
            booster,
            params=DirectClassificationParams.model_validate(metadata["params"]),
            feature_names=metadata["feature_names"],
            weather_columns=metadata["weather_columns"],
        )


def _recipe(params: DirectClassificationParams, weather: Sequence[str]) -> dict[str, object]:
    """What decides a model's inputs and labels; list order and hyperparameters decide nothing."""
    return {
        "threshold": params.threshold.model_dump(),
        "lags": sorted(params.lags),
        "rolling_windows": sorted(params.rolling_windows),
        "day_off": params.day_off,
        "weather_fields": sorted(weather),
    }


def training_rows(params: DirectClassificationParams, data: TrainingData) -> pd.DataFrame:
    """Every (anchor, lead 1..MAX_LEAD_HOURS) pair with a covered threshold window, target and weather.

    Columns: ``anchor``, ``datetime`` (target hour), ``lead_hours``, the anchor
    features (including ``threshold_mw``), the target hour's calendar features and
    weather, the target ``load_mw`` and the label ``is_high_load``. Target hours
    without load or without every weather field get no row; missing weather is never
    filled with a constant or a later value.

    Feature columns are ``FEATURE_DTYPE``; ``load_mw`` stays float64 and the label
    compares it with the float64 threshold, so rounding the features never flips a label.
    """
    load = _load_series(data.load)
    known = _anchor_features(params, load).dropna(subset=[THRESHOLD_COL])
    anchor_position = np.repeat(np.arange(len(known)), MAX_LEAD_HOURS)
    leads = np.tile(np.arange(1, MAX_LEAD_HOURS + 1), len(known))
    targets = pd.DatetimeIndex(known.index)[anchor_position] + pd.to_timedelta(leads, unit="h")
    weather = _by_hour(data.weather.dropna())
    weather_position = weather.index.get_indexer(targets)
    load_position = load.index.get_indexer(targets)
    target_load = np.where(load_position >= 0, load.to_numpy()[load_position], np.nan)
    keep = (weather_position >= 0) & ~np.isnan(target_load)
    rows = _target_rows(
        known,
        anchor_position[keep],
        targets[keep],
        _TargetWeather(weather, weather_position[keep]),
        params.day_off,
    )
    rows[LOAD_MW_COL] = target_load[keep]
    rows[LABEL_COL] = target_load[keep] > known[THRESHOLD_COL].to_numpy()[anchor_position[keep]]
    return rows


def _by_hour(frame: pd.DataFrame) -> pd.DataFrame:
    """Index rows by their hour; when an hour repeats, the last row stands."""
    hourly = frame.assign(**{DATETIME_COL: pd.to_datetime(frame[DATETIME_COL])})
    return hourly.drop_duplicates(DATETIME_COL, keep="last").set_index(DATETIME_COL)


def _load_series(load: pd.DataFrame) -> pd.Series:
    return _by_hour(load)[LOAD_MW_COL].astype(float).sort_index()


def _anchor_features(params: DirectClassificationParams, load: pd.Series) -> pd.DataFrame:
    """Everything known at each anchor hour; time-based windows never look past the anchor.

    The threshold covers the window (anchor - window_days, anchor]; anchors with
    fewer than ``window_hours`` load hours in that window get no threshold.
    """
    features = pd.DataFrame({ANCHOR_LOAD_COL: load}, index=load.index)
    for lag in params.lags:
        lagged = load.reindex(pd.DatetimeIndex(load.index) - pd.Timedelta(hours=lag))
        features[f"{LOAD_MW_COL}_lag_{lag}"] = lagged.to_numpy()
    for window in params.rolling_windows:
        rolling = load.rolling(f"{window}h")
        features[f"{LOAD_MW_COL}_rolling_mean_{window}"] = rolling.mean()
        features[f"{LOAD_MW_COL}_rolling_std_{window}"] = rolling.std().fillna(0.0)
    threshold_window = load.rolling(f"{params.threshold.window_hours}h")
    covered = threshold_window.count() >= params.threshold.window_hours
    features[THRESHOLD_COL] = threshold_window.quantile(params.threshold.quantile).where(covered)
    features.index.name = ANCHOR_COL
    return features


@dataclass(frozen=True)
class _TargetWeather:
    """Weather fields (no time column) and, per row, the position of its target hour in them."""

    fields: pd.DataFrame
    position: np.ndarray


def _target_rows(
    known: pd.DataFrame,
    anchor_position: np.ndarray,
    targets: pd.DatetimeIndex,
    weather: _TargetWeather,
    day_off: bool,
) -> pd.DataFrame:
    """Pair anchors with target hours, adding lead, the target's calendar and its weather.

    Training and prediction both build their rows here, so every feature column is
    ``FEATURE_DTYPE`` on both paths. Columns come straight from position-indexed arrays,
    so each anchor feature is copied once.
    """
    anchors = pd.DatetimeIndex(known.index)[anchor_position]
    columns: dict[str, Any] = {ANCHOR_COL: anchors}
    for column in known.columns:
        columns[column] = _feature(known[column], anchor_position)
    columns[DATETIME_COL] = targets
    lead = (targets - anchors) // pd.Timedelta(hours=1)
    columns[LEAD_HOURS_COL] = np.asarray(lead).astype(FEATURE_DTYPE)
    distinct = targets.unique()
    calendar = create_calendar_features(pd.DataFrame({DATETIME_COL: distinct}), day_off=day_off)
    distinct_position = distinct.get_indexer(targets)
    for column in calendar.columns.drop(DATETIME_COL):
        columns[column] = _feature(calendar[column], distinct_position)
    for column in weather.fields.columns:
        columns[column] = _feature(weather.fields[column], weather.position)
    return pd.DataFrame(columns, copy=False)


def _feature(values: pd.Series, position: np.ndarray) -> np.ndarray:
    """The values at ``position`` as a ``FEATURE_DTYPE`` feature column."""
    return np.take(values.to_numpy(dtype=FEATURE_DTYPE), position)


def _require_trained_leads(leads: np.ndarray) -> None:
    outside = leads[(leads < 1) | (leads > MAX_LEAD_HOURS)]
    if outside.size:
        raise ValueError(
            f"Target hours at lead {sorted({int(lead) for lead in outside})} fall outside the trained lead "
            f"range 1..{MAX_LEAD_HOURS} hours from the anchor"
        )
