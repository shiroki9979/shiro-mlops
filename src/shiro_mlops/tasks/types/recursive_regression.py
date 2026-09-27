"""Recursive regression task type: LightGBM one-step model rolled forward over a horizon.

The recursive strategy (ADR-0003) applies only to tasks of this type. Models are
persisted as LightGBM's native text format plus JSON metadata (ADR-0010).
"""

from __future__ import annotations

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
        return InputRequirements(
            weather=WeatherInput.FORECAST, lookback_hours=params.lookback_hours
        )

    def train(self, params: RecursiveRegressionParams, data: TrainingData) -> Trained:
        """Engineer features, fit on rows before the split, and evaluate one step ahead after it."""
        features = _training_features(params, data)
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
        metadata = {
            "lags": self.lags,
            "rolling_windows": self.rolling_windows,
            "feature_names": self.feature_names,
            "weather_columns": self.weather_columns,
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
