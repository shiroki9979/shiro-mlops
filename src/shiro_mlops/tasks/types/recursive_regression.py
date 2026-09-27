"""Recursive regression task type: LightGBM one-step model rolled forward over a horizon.

The recursive strategy (ADR-0003) applies only to tasks of this type. Models are
persisted as LightGBM's native text format plus JSON metadata (ADR-0010).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar

import lightgbm as lgb
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, LOCATION_COL, SUBJECT_COL
from shiro_mlops.features.transformers import (
    build_feature_pipeline,
    create_calendar_features,
    create_lag_features,
    create_rolling_features,
)
from shiro_mlops.models.evaluator import evaluate_forecast
from shiro_mlops.tasks.types.base import (
    HealthAssessment,
    HealthStatus,
    InputRequirements,
    PredictionData,
    Trained,
    TrainingData,
    WeatherInput,
)

TASK_TYPE_NAME = "recursive_regression"
PREDICTION_COL = f"predicted_{LOAD_MW_COL}"
MODEL_FILE = "model.txt"
METADATA_FILE = "metadata.json"
FORMAT_VERSION = 1
HEALTH_METRIC = "mape"
NON_FEATURE_COLUMNS = frozenset({DATETIME_COL, LOAD_MW_COL, LOCATION_COL, SUBJECT_COL})
# 驗證期為空（資料過短）時沒有可比較的預測，以零值揭露而非中斷訓練。
EMPTY_VALIDATION_METRICS = {"mape": 0.0, "rmse": 0.0, "mae": 0.0}
FIXED_LIGHTGBM_PARAMS = {
    "objective": "regression",
    "metric": "rmse",
    "boosting_type": "gbdt",
    "random_state": 42,
    "verbose": -1,
}


class LightGBMParams(BaseModel):
    """Tunable LightGBM hyperparameters; objective and seed stay fixed for this task type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_estimators: PositiveInt
    learning_rate: PositiveFloat
    num_leaves: int = Field(ge=2)


class RecursiveRegressionParams(BaseModel):
    """Feature recipe and model hyperparameters; the task definition is their only source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lags: list[PositiveInt] = Field(min_length=1)
    rolling_windows: list[PositiveInt] = Field(min_length=1)
    model: LightGBMParams

    @property
    def lookback_hours(self) -> int:
        """History each recursive step needs for its longest lag or rolling window."""
        return max(*self.lags, *self.rolling_windows)


class RecursiveRegressionPrediction(BaseModel):
    """One served forecast hour: the predicted load with the weather that drove it."""

    datetime: str
    predicted_load_mw: float
    temperature: float
    relative_humidity: float
    weather_sources: dict[str, dict[str, str]]


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
        return InputRequirements(
            weather=WeatherInput.FORECAST, lookback_hours=params.lookback_hours
        )

    def train(self, params: RecursiveRegressionParams, data: TrainingData) -> Trained:
        """Engineer features, fit on rows before the split, and evaluate one step ahead after it."""
        features = _training_features(params, data)
        is_validation = features[DATETIME_COL] >= data.validation_start
        training_rows = features.loc[~is_validation]
        if training_rows.empty:
            raise ValueError(
                f"No training rows before validation start {data.validation_start.isoformat()}"
            )
        weather_columns = [column for column in data.weather.columns if column != DATETIME_COL]
        model = RecursiveRegressionModel.fit(params, training_rows, weather_columns)
        return Trained(model=model, metrics=model.evaluate(features.loc[is_validation]))

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
    ):
        self.booster = booster
        self.lags = lags
        self.rolling_windows = rolling_windows
        self.feature_names = feature_names
        self.weather_columns = weather_columns

    @classmethod
    def fit(
        cls,
        params: RecursiveRegressionParams,
        training_rows: pd.DataFrame,
        weather_columns: list[str],
    ) -> RecursiveRegressionModel:
        feature_names = [c for c in training_rows.columns if c not in NON_FEATURE_COLUMNS]
        regressor = lgb.LGBMRegressor(**FIXED_LIGHTGBM_PARAMS, **params.model.model_dump())
        regressor.fit(training_rows[feature_names], training_rows[LOAD_MW_COL])
        return cls(
            regressor.booster_,
            lags=list(params.lags),
            rolling_windows=list(params.rolling_windows),
            feature_names=feature_names,
            weather_columns=weather_columns,
        )

    def evaluate(self, validation_rows: pd.DataFrame) -> dict[str, float]:
        """One-step-ahead metrics on validation rows whose lags hold actual load."""
        if validation_rows.empty:
            return dict(EMPTY_VALIDATION_METRICS)
        predicted = self.booster.predict(validation_rows[self.feature_names])
        return evaluate_forecast(validation_rows[LOAD_MW_COL].to_numpy(), predicted)

    def predict(self, data: PredictionData) -> pd.DataFrame:
        """Roll the one-step model forward, feeding each prediction into later lags."""
        weather = _sorted_by_time(data.weather)
        if data.horizon_hours is not None:
            weather = weather.head(data.horizon_hours)
        buffer = _sorted_by_time(data.load_history[[DATETIME_COL, LOAD_MW_COL]])
        predictions: list[dict[str, object]] = []
        for _, step in weather.iterrows():
            value = self._predict_step(buffer, step)
            predictions.append({DATETIME_COL: step[DATETIME_COL], PREDICTION_COL: value})
            next_row = pd.DataFrame([{DATETIME_COL: step[DATETIME_COL], LOAD_MW_COL: value}])
            buffer = pd.concat([buffer, next_row], ignore_index=True)
        return pd.DataFrame(predictions, columns=[DATETIME_COL, PREDICTION_COL])

    def _predict_step(self, buffer: pd.DataFrame, step: pd.Series) -> float:
        candidate = pd.DataFrame([{DATETIME_COL: step[DATETIME_COL], LOAD_MW_COL: np.nan}])
        extended = pd.concat([buffer, candidate], ignore_index=True)
        extended = create_calendar_features(extended)
        extended = create_lag_features(extended, value_col=LOAD_MW_COL, lags=self.lags)
        extended = create_rolling_features(
            extended, value_col=LOAD_MW_COL, windows=self.rolling_windows
        )
        row = extended.iloc[[-1]].copy()
        for column in self.weather_columns:
            row[column] = float(step[column])
        return float(self.booster.predict(row[self.feature_names])[0])

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.booster.save_model(str(directory / MODEL_FILE))
        metadata = {
            "format_version": FORMAT_VERSION,
            "task_type": TASK_TYPE_NAME,
            "lags": self.lags,
            "rolling_windows": self.rolling_windows,
            "feature_names": self.feature_names,
            "weather_columns": self.weather_columns,
        }
        (directory / METADATA_FILE).write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> RecursiveRegressionModel:
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
            lags=metadata["lags"],
            rolling_windows=metadata["rolling_windows"],
            feature_names=metadata["feature_names"],
            weather_columns=metadata["weather_columns"],
        )


def _training_features(params: RecursiveRegressionParams, data: TrainingData) -> pd.DataFrame:
    # Weather joins by time only: it already comes from the subject's weather reference point.
    return build_feature_pipeline(
        load_df=data.load,
        weather_df=data.weather,
        lags=params.lags,
        windows=params.rolling_windows,
        location_col=SUBJECT_COL,
        strict_weather=True,
    )


def _sorted_by_time(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result[DATETIME_COL] = pd.to_datetime(result[DATETIME_COL])
    return result.sort_values(DATETIME_COL).reset_index(drop=True)
