"""Recursive regression task type: LightGBM one-step model rolled forward over a horizon.

The recursive strategy (ADR-0003) applies only to tasks of this type. Models are
persisted as LightGBM's native text format plus JSON metadata (ADR-0010).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, LOCATION_COL, SUBJECT_COL
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime
from shiro_mlops.features.transformers import build_feature_pipeline, create_calendar_features
from shiro_mlops.models.evaluator import evaluate_forecast
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

TASK_TYPE_NAME = "recursive_regression"
PREDICTION_COL = f"predicted_{LOAD_MW_COL}"
MODEL_FILES = NativeBoosterFiles(ModelFormat(TASK_TYPE_NAME, version=1))
HEALTH_METRIC = "mape"
NON_FEATURE_COLUMNS = frozenset({DATETIME_COL, LOAD_MW_COL, LOCATION_COL, SUBJECT_COL})
FIXED_LIGHTGBM_PARAMS = {**LIGHTGBM_BASE_PARAMS, "objective": "regression", "metric": "rmse"}


class RecursiveRegressionParams(BaseModel):
    """Feature recipe and model hyperparameters; the task definition is their only source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lags: list[PositiveInt] = Field(min_length=1)
    rolling_windows: list[PositiveInt] = Field(min_length=1)
    # 放假日特徵（GLOSSARY）：依各小時自身日期判定，預設關閉以維持既有特徵集。
    day_off: bool = False
    model: LightGBMParams

    @property
    def lookback_hours(self) -> int:
        """History each recursive step needs for its longest lag or rolling window."""
        return max(*self.lags, *self.rolling_windows)


class RecursiveRegressionPrediction(WeatherEchoingItem):
    """One served forecast hour: the predicted load, served with the weather that drove it."""

    datetime: str
    predicted_load_mw: float


class RecursiveRegressionHealth(BaseModel):
    """Monitoring thresholds read from the task definition's ``[health]`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_mape: PositiveFloat


class RecursiveRegression:
    """Task type adapter for recursive multi-step regression."""

    name: ClassVar[str] = TASK_TYPE_NAME
    params_model: ClassVar[type[RecursiveRegressionParams]] = RecursiveRegressionParams
    prediction_item: ClassVar[type[RecursiveRegressionPrediction]] = RecursiveRegressionPrediction
    health_model: ClassVar[type[RecursiveRegressionHealth]] = RecursiveRegressionHealth

    def requirements(self, params: RecursiveRegressionParams) -> InputRequirements:
        # WHY-NOT(lookback): 要求整段 lookback 完整而非只查各步用到的 lag 小時；實際負載無替代來源
        # （GLOSSARY），滾動窗同樣不得以缺值推演，且與回測起點有效性一致。
        lookback = params.lookback_hours
        return InputRequirements(
            weather=WeatherInput.FORECAST,
            lookback_hours=lookback,
            history_coverage=HistoryCoverage.complete(lookback),
        )

    def train(self, params: RecursiveRegressionParams, data: TrainingData) -> Trained:
        """Engineer features, fit on rows before the split, and evaluate one step ahead after it."""
        features = training_features(params, data)
        training_rows, validation_rows = split_at_validation(features, data.validation_start)
        model = RecursiveRegressionModel.fit(params, training_rows, data.weather_columns)
        return Trained(model=model, metrics=model.evaluate(validation_rows))

    def load(self, directory: Path) -> RecursiveRegressionModel:
        return RecursiveRegressionModel.load(directory)

    def assess_health(
        self, thresholds: RecursiveRegressionHealth, metrics: Mapping[str, float]
    ) -> HealthAssessment:
        """Healthy while validation MAPE stays below ``max_mape``; a missing MAPE warns."""
        if HEALTH_METRIC not in metrics:
            return HealthAssessment(
                HealthStatus.WARNING,
                f"No {HEALTH_METRIC} metric to compare with max_mape={thresholds.max_mape}",
            )
        mape = float(metrics[HEALTH_METRIC])
        if mape < thresholds.max_mape:
            return HealthAssessment(
                HealthStatus.HEALTHY, f"{HEALTH_METRIC}={mape:.4g} < max_mape={thresholds.max_mape}"
            )
        return HealthAssessment(
            HealthStatus.WARNING, f"{HEALTH_METRIC}={mape:.4g} >= max_mape={thresholds.max_mape}"
        )


class RecursiveRegressionModel:
    """Fitted LightGBM booster plus the feature recipe it was trained with."""

    def __init__(
        self,
        booster: lgb.Booster,
        *,
        lags: list[int],
        rolling_windows: list[int],
        feature_names: list[str],
        weather_columns: list[str],
        day_off: bool = False,
    ):
        self.booster = booster
        self.lags = lags
        self.rolling_windows = rolling_windows
        self.day_off = day_off
        self.feature_names = feature_names
        self.weather_columns = weather_columns

    @classmethod
    def fit(
        cls,
        params: RecursiveRegressionParams,
        training_rows: pd.DataFrame,
        weather_columns: list[str],
    ) -> RecursiveRegressionModel:
        # WHY-NOT(lgb): 用到時才 import；lightgbm 4.7.0 在 python -OO 下一 import 就崩潰，
        # 放在模組頂層會讓只讀任務設定的 CLI（smoke check 的 --help）在解析參數前就失敗。
        import lightgbm as lgb

        feature_names = [c for c in training_rows.columns if c not in NON_FEATURE_COLUMNS]
        regressor = lgb.LGBMRegressor(**FIXED_LIGHTGBM_PARAMS, **params.model.model_dump())
        regressor.fit(training_rows[feature_names], training_rows[LOAD_MW_COL])
        return cls(
            regressor.booster_,
            lags=list(params.lags),
            rolling_windows=list(params.rolling_windows),
            feature_names=feature_names,
            weather_columns=weather_columns,
            day_off=params.day_off,
        )

    def evaluate(self, validation_rows: pd.DataFrame) -> dict[str, float]:
        """One-step-ahead metrics on validation rows whose lags hold actual load; none without rows."""
        if validation_rows.empty:
            return {}
        predicted = self.booster.predict(validation_rows[self.feature_names])
        return evaluate_forecast(validation_rows[LOAD_MW_COL].to_numpy(), predicted)

    def predict(self, data: PredictionData) -> pd.DataFrame:
        """Roll the one-step model forward, feeding each prediction into later lags."""
        weather = _sorted_by_time(data.weather)
        if data.horizon_hours is not None:
            weather = weather.head(data.horizon_hours)
        step_inputs = create_calendar_features(weather[[DATETIME_COL]], day_off=self.day_off)
        for column in self.weather_columns:
            step_inputs[column] = weather[column].astype(float)
        history = _LoadHistory.from_frame(data.load_history)
        predictions: list[float] = []
        for step in step_inputs.to_dict("records"):
            moment = step[DATETIME_COL]
            step.update(history.features_at(moment, self.lags, self.rolling_windows))
            row = np.array([[step[name] for name in self.feature_names]], dtype=float)
            value = float(self.booster.predict(row)[0])
            history.append(moment, value)
            predictions.append(value)
        return pd.DataFrame({DATETIME_COL: weather[DATETIME_COL], PREDICTION_COL: predictions})

    def save(self, directory: Path) -> None:
        metadata = {
            "lags": self.lags,
            "rolling_windows": self.rolling_windows,
            "feature_names": self.feature_names,
            "weather_columns": self.weather_columns,
            "day_off": self.day_off,
        }
        MODEL_FILES.save(directory, self.booster, metadata)

    @classmethod
    def load(cls, directory: Path) -> RecursiveRegressionModel:
        booster, metadata = MODEL_FILES.load(directory)
        return cls(
            booster,
            lags=metadata["lags"],
            rolling_windows=metadata["rolling_windows"],
            feature_names=metadata["feature_names"],
            weather_columns=metadata["weather_columns"],
            # 放假日特徵加入前保存的模型沒有此鍵，即未使用該特徵。
            day_off=metadata.get("day_off", False),
        )


def training_features(params: RecursiveRegressionParams, data: TrainingData) -> pd.DataFrame:
    """Feature rows that `train` splits at `validation_start`; rows lacking a lag or weather are dropped."""
    # Weather joins by time only: it already comes from the subject's weather reference point.
    return build_feature_pipeline(
        load_df=data.load,
        weather_df=data.weather,
        lags=params.lags,
        windows=params.rolling_windows,
        location_col=SUBJECT_COL,
        day_off=params.day_off,
    )


_HOUR_NS = 3_600_000_000_000


class _LoadHistory:
    """Time-ordered load that yields one hour's lag and rolling features without a full recompute.

    The values match ``create_lag_features`` and ``create_rolling_features``: a lag is the load
    exactly that many hours earlier or missing, and a rolling statistic covers the observed
    loads in ``[moment - window, moment)``. Recomputing those transformers over the whole
    buffer at every step made a 168-hour forecast spend most of its time rebuilding features
    of hours it had already predicted.
    """

    def __init__(self, times: np.ndarray, loads: np.ndarray) -> None:
        self._times = times
        self._loads = loads

    @classmethod
    def from_frame(cls, load_history: pd.DataFrame) -> _LoadHistory:
        times = _nanoseconds(standardize_taiwan_datetime(load_history[DATETIME_COL]))
        order = np.argsort(times, kind="stable")
        loads = load_history[LOAD_MW_COL].to_numpy(dtype=float)
        return cls(times[order], loads[order])

    def append(self, moment: pd.Timestamp, load: float) -> None:
        position = np.searchsorted(self._times, moment.value, side="right")
        self._times = np.insert(self._times, position, moment.value)
        self._loads = np.insert(self._loads, position, load)

    def features_at(
        self, moment: pd.Timestamp, lags: list[int], rolling_windows: list[int]
    ) -> dict[str, float]:
        now = moment.value
        features: dict[str, float] = {}
        for lag in lags:
            features[f"{LOAD_MW_COL}_lag_{lag}"] = self._load_at(now - lag * _HOUR_NS)
        end = np.searchsorted(self._times, now, side="left")
        for window in rolling_windows:
            start = np.searchsorted(self._times, now - window * _HOUR_NS, side="left")
            observed = self._loads[start:end]
            observed = observed[~np.isnan(observed)]
            features[f"{LOAD_MW_COL}_rolling_mean_{window}"] = (
                float(observed.mean()) if observed.size else np.nan
            )
            features[f"{LOAD_MW_COL}_rolling_std_{window}"] = _sample_std(observed)
        return features

    def _load_at(self, instant: int) -> float:
        position = np.searchsorted(self._times, instant, side="right") - 1
        if position < 0 or self._times[position] != instant:
            return np.nan
        return float(self._loads[position])


def _nanoseconds(times: pd.Series) -> np.ndarray:
    return pd.DatetimeIndex(times).as_unit("ns").asi8


def _sample_std(observed: np.ndarray) -> float:
    """Sample standard deviation as the rolling feature defines it: 0 for a lone observation."""
    if observed.size == 0:
        return np.nan
    if observed.size == 1:
        return 0.0
    return float(observed.std(ddof=1))


def _sorted_by_time(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result[DATETIME_COL] = standardize_taiwan_datetime(result[DATETIME_COL])
    return result.sort_values(DATETIME_COL).reset_index(drop=True)
