"""Direct classification task type: one LightGBM classifier answers every lead hour at once.

Used by the high-load alert (高負載預警): each row pairs what is known at an
anchor hour (its load, load lags and rolling statistics, and the high-load
threshold) with one target hour's calendar, weather and lead time. Unlike the
recursive strategy, no forecast output is fed back in. Models are persisted as
LightGBM's native text format plus JSON metadata (ADR-0010).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import lightgbm as lgb
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
    WeatherInput,
    split_at_validation,
)
from shiro_mlops.tasks.types.recursive_regression import LightGBMParams

TASK_TYPE_NAME = "direct_classification"
MODEL_FILE = "model.txt"
METADATA_FILE = "metadata.json"
FORMAT_VERSION = 1
ANCHOR_COL = "anchor"
ANCHOR_LOAD_COL = f"anchor_{LOAD_MW_COL}"
LEAD_HOURS_COL = "lead_hours"
THRESHOLD_COL = "threshold_mw"
LABEL_COL = "is_high_load"
PROBABILITY_COL = "probability"
# 視界上限與 API 接受的最長 horizon 一致，單一模型才能涵蓋任何請求的每個小時。
MAX_LEAD_HOURS = MAX_HORIZON_HOURS
# 門檻窗內至少九成小時有實際負載才計算門檻；推算序列偶有上游中斷缺口，要求全滿會讓
# 單一缺漏小時使預警停擺 28 日，缺漏過多則分位數不再代表該窗的負載分布。
MIN_THRESHOLD_WINDOW_COVERAGE = 0.9
# 以機率 0.5 判定是否預警，與 LightGBM 二元分類的預設決策界線一致。
ALERT_PROBABILITY = 0.5
METRIC_NAMES = ("precision", "recall", "f1")
NON_FEATURE_COLUMNS = frozenset({ANCHOR_COL, DATETIME_COL, LOAD_MW_COL, LABEL_COL})
FIXED_LIGHTGBM_PARAMS = {
    "objective": "binary",
    "boosting_type": "gbdt",
    "random_state": 42,
    "verbose": -1,
}


class HighLoadThresholdParams(BaseModel):
    """How the high-load threshold is derived from load known at the anchor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_days: PositiveInt
    quantile: float = Field(gt=0.0, lt=1.0)

    @property
    def window_hours(self) -> int:
        return self.window_days * HOURS_PER_DAY

    @property
    def min_valid_hours(self) -> int:
        return math.ceil(self.window_hours * MIN_THRESHOLD_WINDOW_COVERAGE)


class DirectClassificationParams(BaseModel):
    """Threshold rule, anchor feature recipe and model hyperparameters from the task definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    threshold: HighLoadThresholdParams
    lags: list[PositiveInt] = Field(min_length=1)
    rolling_windows: list[PositiveInt] = Field(min_length=1)
    model: LightGBMParams

    @property
    def lookback_hours(self) -> int:
        """History that covers the threshold window plus the longest lag or rolling window."""
        return self.threshold.window_hours + max(*self.lags, *self.rolling_windows)


class DirectClassificationPrediction(BaseModel):
    """One served alert hour: the verdict, its probability and threshold, with the weather."""

    datetime: str
    is_high_load: bool
    probability: float
    threshold_mw: float
    temperature: float
    relative_humidity: float
    weather_sources: dict[str, dict[str, str]]


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
    prediction_item: ClassVar[type[DirectClassificationPrediction]] = DirectClassificationPrediction
    health_model: ClassVar[type[DirectClassificationHealth]] = DirectClassificationHealth

    def requirements(self, params: DirectClassificationParams) -> InputRequirements:
        threshold = params.threshold
        return InputRequirements(
            weather=WeatherInput.FORECAST,
            lookback_hours=params.lookback_hours,
            history_coverage=HistoryCoverage(threshold.window_hours, threshold.min_valid_hours),
        )

    def train(self, params: DirectClassificationParams, data: TrainingData) -> Trained:
        """Label every (anchor, lead) pair, fit on targets before the split, evaluate after it."""
        fitting_rows, validation_rows = split_at_validation(
            training_rows(params, data), data.validation_start
        )
        weather_columns = [column for column in data.weather.columns if column != DATETIME_COL]
        model = DirectClassificationModel.fit(params, fitting_rows, weather_columns)
        return Trained(model=model, metrics=model.evaluate(validation_rows))

    def load(self, directory: Path) -> DirectClassificationModel:
        return DirectClassificationModel.load(directory)

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
                f"Load history has fewer than {self.params.threshold.min_valid_hours} hours in "
                f"the {self.params.threshold.window_days}-day high-load threshold window "
                f"ending at anchor {anchor.isoformat()}"
            )
        targets = pd.to_datetime(data.weather[DATETIME_COL])
        rows = _target_rows(known.loc[[anchor] * len(targets)], targets)
        _require_trained_leads(rows[LEAD_HOURS_COL])
        for column in self.weather_columns:
            rows[column] = data.weather[column].to_numpy(dtype=float)
        probability = self._probabilities(rows)
        return pd.DataFrame(
            {
                DATETIME_COL: rows[DATETIME_COL],
                LABEL_COL: [bool(value) for value in probability >= ALERT_PROBABILITY],
                PROBABILITY_COL: probability,
                THRESHOLD_COL: rows[THRESHOLD_COL].astype(float),
            }
        )

    def _probabilities(self, rows: pd.DataFrame) -> pd.Series:
        return pd.Series(self.booster.predict(rows[self.feature_names]), index=rows.index)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / MODEL_FILE))
        metadata = {
            "format_version": FORMAT_VERSION,
            "task_type": TASK_TYPE_NAME,
            "params": self.params.model_dump(),
            "max_lead_hours": MAX_LEAD_HOURS,
            "feature_names": self.feature_names,
            "weather_columns": self.weather_columns,
        }
        (directory / METADATA_FILE).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> DirectClassificationModel:
        metadata = json.loads((directory / METADATA_FILE).read_text(encoding="utf-8"))
        if metadata.get("task_type") != TASK_TYPE_NAME:
            raise ValueError(
                f"Model in {directory} belongs to task type {metadata.get('task_type')!r}, "
                f"not {TASK_TYPE_NAME!r}"
            )
        if metadata.get("format_version") != FORMAT_VERSION:
            raise ValueError(
                f"Unsupported model format version {metadata.get('format_version')!r} "
                f"in {directory}"
            )
        return cls(
            lgb.Booster(model_file=str(directory / MODEL_FILE)),
            params=DirectClassificationParams.model_validate(metadata["params"]),
            feature_names=metadata["feature_names"],
            weather_columns=metadata["weather_columns"],
        )


def training_rows(params: DirectClassificationParams, data: TrainingData) -> pd.DataFrame:
    """Every (anchor, lead 1..MAX_LEAD_HOURS) pair with a covered threshold window, target and weather.

    Columns: ``anchor``, ``datetime`` (target hour), ``lead_hours``, the anchor
    features (including ``threshold_mw``), the target hour's calendar features and
    weather, the target ``load_mw`` and the label ``is_high_load``.
    """
    load = _load_series(data.load)
    known = _anchor_features(params, load).dropna(subset=[THRESHOLD_COL])
    targets = known.index.repeat(MAX_LEAD_HOURS) + pd.to_timedelta(
        list(range(1, MAX_LEAD_HOURS + 1)) * len(known), unit="h"
    )
    rows = _target_rows(known.loc[known.index.repeat(MAX_LEAD_HOURS)], pd.Series(targets))
    weather = data.weather.assign(**{DATETIME_COL: pd.to_datetime(data.weather[DATETIME_COL])})
    # 觀測天氣缺漏的小時直接捨棄，不以常數或未來值補值。
    rows = rows.merge(weather.dropna(), on=DATETIME_COL)
    rows[LOAD_MW_COL] = load.reindex(rows[DATETIME_COL]).to_numpy()
    rows = rows.dropna(subset=[LOAD_MW_COL]).reset_index(drop=True)
    rows[LABEL_COL] = rows[LOAD_MW_COL] > rows[THRESHOLD_COL]
    return rows


def _load_series(load: pd.DataFrame) -> pd.Series:
    series = load.assign(**{DATETIME_COL: pd.to_datetime(load[DATETIME_COL])})
    series = series.drop_duplicates(DATETIME_COL, keep="last").set_index(DATETIME_COL)
    return series[LOAD_MW_COL].astype(float).sort_index()


def _anchor_features(params: DirectClassificationParams, load: pd.Series) -> pd.DataFrame:
    """Everything known at each anchor hour; time-based windows never look past the anchor.

    The threshold covers the window (anchor - window_days, anchor]; anchors with
    fewer than ``min_valid_hours`` load hours in that window get no threshold.
    """
    features = pd.DataFrame({ANCHOR_LOAD_COL: load}, index=load.index)
    for lag in params.lags:
        lagged = load.reindex(load.index - pd.Timedelta(hours=lag))
        features[f"{LOAD_MW_COL}_lag_{lag}"] = lagged.to_numpy()
    for window in params.rolling_windows:
        rolling = load.rolling(f"{window}h")
        features[f"{LOAD_MW_COL}_rolling_mean_{window}"] = rolling.mean()
        features[f"{LOAD_MW_COL}_rolling_std_{window}"] = rolling.std().fillna(0.0)
    window = load.rolling(f"{params.threshold.window_hours}h")
    covered = window.count() >= params.threshold.min_valid_hours
    features[THRESHOLD_COL] = window.quantile(params.threshold.quantile).where(covered)
    features.index.name = ANCHOR_COL
    return features


def _target_rows(known: pd.DataFrame, targets: pd.Series) -> pd.DataFrame:
    """Pair anchor rows with target hours, adding the lead time and the target's calendar."""
    rows = known.reset_index()
    rows[DATETIME_COL] = targets.to_numpy()
    rows[LEAD_HOURS_COL] = (rows[DATETIME_COL] - rows[ANCHOR_COL]) // pd.Timedelta(hours=1)
    return create_calendar_features(rows)


def _require_trained_leads(leads: pd.Series) -> None:
    outside = leads[(leads < 1) | (leads > MAX_LEAD_HOURS)]
    if not outside.empty:
        raise ValueError(
            f"Target hours at lead {sorted(set(outside))} fall outside the trained lead "
            f"range 1..{MAX_LEAD_HOURS} hours from the anchor"
        )
