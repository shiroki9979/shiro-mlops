"""Unsupervised reconstruction task type: a shallow MLP AutoEncoder scoring sliding windows.

Each window holds ``window_hours`` consecutive hours of actual load and observed
weather plus the calendar position of its end hour. The AutoEncoder reconstructs
its own input; the reconstruction error of the load part is the anomaly score, so
weather and calendar only describe the conditions a load shape is judged against
(GLOSSARY.md, load-pattern anomaly). Training needs no labels: validation windows alternate
by calendar day between calibration, whose error quantile is the decision
threshold, and holdout, where the clean false positive rate and the recall on
injected synthetic anomalies are measured.

Models are persisted as ``.npz`` arrays (``allow_pickle=False``) plus JSON and
served by a numpy forward pass (ADR-0010; tests/unit/test_model_persistence_boundary.py
enforces ``allow_pickle=False`` on every ``np.load``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from pydantic import BaseModel, ConfigDict, Field, NonNegativeFloat, PositiveFloat, PositiveInt
from sklearn.neural_network import MLPRegressor

from shiro_mlops.core.constants import (
    DATETIME_COL,
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
    LOAD_MW_COL,
    MAX_HORIZON_HOURS,
    SATURDAY,
)
from shiro_mlops.tasks.types.base import (
    HealthAssessment,
    HealthStatus,
    InputRequirements,
    PredictionData,
    Trained,
    TrainingData,
    WeatherInput,
)
from shiro_mlops.tasks.types.metadata import ModelFormat, read_metadata, write_metadata

TASK_TYPE_NAME = "unsupervised_reconstruction"
ARRAYS_FILE = "model.npz"
MODEL_FORMAT = ModelFormat(TASK_TYPE_NAME, version=1)
# ADR-0010：numpy 前向計算只實作這兩種激活函數，訓練時固定之。
HIDDEN_ACTIVATION = "relu"
OUTPUT_ACTIVATION = "identity"
RANDOM_STATE = 42
# 與 recursive_regression 訓練特徵相同：觀測天氣最多向前補兩小時，更長的缺口不補值。
WEATHER_FILL_LIMIT_HOURS = 2
# 逐時週末旗標讓週五→週六、週日→週一的階梯落在窗內任一位置時仍可重建；
# 只以結束小時編碼星期時，這類常態轉換會被誤判為異常。
IS_WEEKEND_COL = "is_weekend"
CALENDAR_FEATURES = ("hour_sin", "hour_cos", "dayofweek_sin", "dayofweek_cos")
SCORE_COL = "anomaly_score"
IS_ANOMALY_COL = "is_anomaly"
THRESHOLD_COL = "threshold"
THRESHOLD_METRIC = "threshold"
RECALL_METRIC = "recall"
FALSE_POSITIVE_RATE_METRIC = "false_positive_rate"
# 合成異常強度以常態負載的比例表示；對應颱風停班停課、大規模停電等用電型態異常的量級。
SUDDEN_DROP_HOURS = 6
SUDDEN_DROP_FRACTION = 0.2
LEVEL_SHIFT_FRACTION = 0.1


class AutoEncoderParams(BaseModel):
    """Tunable MLP hyperparameters; activations, solver and seed stay fixed for this task type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # 淺層：至多三個隱藏層，瓶頸層寬度由設定決定。
    hidden_layer_sizes: list[PositiveInt] = Field(min_length=1, max_length=3)
    alpha: NonNegativeFloat
    learning_rate_init: PositiveFloat
    max_iter: PositiveInt


class UnsupervisedReconstructionParams(BaseModel):
    """Window length, decision quantile and AutoEncoder hyperparameters from the task definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    window_hours: int = Field(ge=SUDDEN_DROP_HOURS)
    threshold_quantile: float = Field(gt=0.0, lt=1.0)
    model: AutoEncoderParams

    @property
    def lookback_hours(self) -> int:
        """History that covers a full window for each of the most window end hours served."""
        return self.window_hours + MAX_HORIZON_HOURS


class UnsupervisedReconstructionPrediction(BaseModel):
    """One scored window, reported at its end hour."""

    datetime: str
    anomaly_score: float
    is_anomaly: bool
    threshold: float


class UnsupervisedReconstructionHealth(BaseModel):
    """Monitoring thresholds read from the task definition's ``[health]`` table."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_recall: float = Field(gt=0.0, le=1.0)
    max_false_positive_rate: float = Field(ge=0.0, lt=1.0)


class UnsupervisedReconstruction:
    """Task type adapter for window reconstruction anomaly detection."""

    name: ClassVar[str] = TASK_TYPE_NAME
    params_model: ClassVar[type[UnsupervisedReconstructionParams]] = (
        UnsupervisedReconstructionParams
    )
    prediction_item: ClassVar[type[UnsupervisedReconstructionPrediction]] = (
        UnsupervisedReconstructionPrediction
    )
    health_model: ClassVar[type[UnsupervisedReconstructionHealth]] = (
        UnsupervisedReconstructionHealth
    )

    def requirements(self, params: UnsupervisedReconstructionParams) -> InputRequirements:
        return InputRequirements(
            weather=WeatherInput.OBSERVED,
            lookback_hours=params.lookback_hours,
            # WHY-NOT(history_coverage): 不要求 lookback 完整；任務類型只跳過有缺口的時間窗，
            # 要求完整會讓負載缺一小時就使整個異常偵測任務不可用。
            history_coverage=None,
        )

    def train(self, params: UnsupervisedReconstructionParams, data: TrainingData) -> Trained:
        """Fit on windows ending before the split; calibrate and evaluate on alternate days after it.

        Measuring the false positive rate on the windows that set the threshold
        would pin it near ``1 - threshold_quantile`` whatever the model does.
        Alternating whole days, rather than cutting the period in two, keeps both
        halves spread over the same weekdays and weekends when validation is
        shorter than a week.
        """
        weather_columns = data.weather_columns
        windows = _build_windows(data.load, data.weather, weather_columns, params.window_hours)
        is_validation = windows.end_times >= data.validation_start
        training = windows.features[~is_validation]
        calibration, holdout = _alternate_days(windows.select(is_validation))
        _require_enough_windows(training, calibration, data.validation_start)
        model = UnsupervisedReconstructionModel.fit(params, training, calibration, weather_columns)
        metrics = {
            "calibration_windows": float(len(calibration)),
            "validation_windows": float(len(holdout)),
            **model.evaluate(holdout),
        }
        return Trained(model=model, metrics=metrics)

    def load(self, directory: Path) -> UnsupervisedReconstructionModel:
        return UnsupervisedReconstructionModel.load(directory)

    def assess_health(
        self, thresholds: UnsupervisedReconstructionHealth, metrics: Mapping[str, float]
    ) -> HealthAssessment:
        """Healthy while recall reaches ``min_recall`` and false positives stay within bounds."""
        limits = (
            f"min_recall={thresholds.min_recall}, "
            f"max_false_positive_rate={thresholds.max_false_positive_rate}"
        )
        missing = [m for m in (RECALL_METRIC, FALSE_POSITIVE_RATE_METRIC) if m not in metrics]
        if missing:
            return HealthAssessment(
                HealthStatus.WARNING, f"No {', '.join(missing)} metric to compare with {limits}"
            )
        recall = float(metrics[RECALL_METRIC])
        false_positive_rate = float(metrics[FALSE_POSITIVE_RATE_METRIC])
        observed = f"recall={recall:.4g}, false_positive_rate={false_positive_rate:.4g}"
        healthy = (
            recall >= thresholds.min_recall
            and false_positive_rate <= thresholds.max_false_positive_rate
        )
        status = HealthStatus.HEALTHY if healthy else HealthStatus.WARNING
        return HealthAssessment(status, f"{observed} against {limits}")


# --- numpy forward pass --------------------------------------------------------------------


@dataclass(frozen=True)
class NumpyMLP:
    """Forward pass of a fitted ReLU ``MLPRegressor`` with an identity output layer."""

    coefs: tuple[np.ndarray, ...]
    intercepts: tuple[np.ndarray, ...]

    @classmethod
    def from_regressor(cls, regressor: MLPRegressor) -> NumpyMLP:
        activations = (regressor.activation, regressor.out_activation_)
        if activations != (HIDDEN_ACTIVATION, OUTPUT_ACTIVATION):
            raise ValueError(
                f"Only {HIDDEN_ACTIVATION} hidden layers with an {OUTPUT_ACTIVATION} output "
                f"layer are supported, got {activations}"
            )
        return cls(
            coefs=tuple(np.array(coef, dtype=float) for coef in regressor.coefs_),
            intercepts=tuple(
                np.array(intercept, dtype=float) for intercept in regressor.intercepts_
            ),
        )

    def predict(self, inputs: np.ndarray) -> np.ndarray:
        activations = np.asarray(inputs, dtype=float)
        output_layer = len(self.coefs) - 1
        for layer, (coef, intercept) in enumerate(zip(self.coefs, self.intercepts, strict=True)):
            activations = activations @ coef + intercept
            if layer < output_layer:
                activations = np.maximum(activations, 0.0)
        return activations


# --- Model ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Scaler:
    """Per-feature standardization fitted on training windows; constant features keep scale 1."""

    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, features: np.ndarray) -> _Scaler:
        # WHY-NOT _Scaler: constant features are found by their range, not by std > 0; the std of
        # a repeated inexact float (70.1) is round-off near 1e-14, and dividing by it turns the
        # first different reading at serving into a score trillions of times the threshold.
        is_constant = np.ptp(features, axis=0) == 0.0
        return cls(
            mean=features.mean(axis=0), scale=np.where(is_constant, 1.0, features.std(axis=0))
        )

    def transform(self, features: np.ndarray) -> np.ndarray:
        return (features - self.mean) / self.scale


class UnsupervisedReconstructionModel:
    """Fitted AutoEncoder, its input scaling, and the decision threshold on anomaly scores."""

    def __init__(
        self,
        network: NumpyMLP,
        scaler: _Scaler,
        *,
        threshold: float,
        window_hours: int,
        weather_columns: list[str],
    ):
        self.network = network
        self.scaler = scaler
        self.threshold = threshold
        self.window_hours = window_hours
        self.weather_columns = weather_columns

    @classmethod
    def fit(
        cls,
        params: UnsupervisedReconstructionParams,
        training: np.ndarray,
        calibration: np.ndarray,
        weather_columns: list[str],
    ) -> UnsupervisedReconstructionModel:
        scaler = _Scaler.fit(training)
        scaled = scaler.transform(training)
        regressor = MLPRegressor(
            hidden_layer_sizes=tuple(params.model.hidden_layer_sizes),
            activation=HIDDEN_ACTIVATION,
            solver="adam",
            alpha=params.model.alpha,
            learning_rate_init=params.model.learning_rate_init,
            max_iter=params.model.max_iter,
            random_state=RANDOM_STATE,
        )
        regressor.fit(scaled, scaled)
        network = NumpyMLP.from_regressor(regressor)
        errors = _load_reconstruction_errors(network, scaler, calibration, params.window_hours)
        return cls(
            network,
            scaler,
            threshold=float(np.quantile(errors, params.threshold_quantile)),
            window_hours=params.window_hours,
            weather_columns=weather_columns,
        )

    def score(self, features: np.ndarray) -> np.ndarray:
        """Anomaly score of each window row."""
        return _load_reconstruction_errors(self.network, self.scaler, features, self.window_hours)

    def evaluate(self, clean: np.ndarray) -> dict[str, float]:
        """False positive rate on clean windows and recall on each injected anomaly kind.

        Without clean windows only the threshold is reported, so health warns.
        """
        if len(clean) == 0:
            return {THRESHOLD_METRIC: self.threshold}
        metrics = {
            THRESHOLD_METRIC: self.threshold,
            FALSE_POSITIVE_RATE_METRIC: self._flagged_fraction(clean),
        }
        recalls = {
            f"{RECALL_METRIC}_{kind}": self._flagged_fraction(inject(clean, self.window_hours))
            for kind, inject in SYNTHETIC_ANOMALIES.items()
        }
        return {**metrics, **recalls, RECALL_METRIC: float(np.mean(list(recalls.values())))}

    def _flagged_fraction(self, features: np.ndarray) -> float:
        return float(np.mean(self.score(features) > self.threshold))

    def predict(self, data: PredictionData) -> pd.DataFrame:
        """Score complete windows ending within the last ``horizon_hours`` hours up to the anchor."""
        windows = _build_windows(
            data.load_history, data.weather, self.weather_columns, self.window_hours
        )
        selected = windows.end_times <= data.anchor
        if data.horizon_hours is not None:
            selected &= windows.end_times > data.anchor - pd.Timedelta(hours=data.horizon_hours)
        scores = self.score(windows.features[selected])
        return pd.DataFrame(
            {
                DATETIME_COL: windows.end_times[selected],
                SCORE_COL: scores,
                IS_ANOMALY_COL: scores > self.threshold,
                THRESHOLD_COL: self.threshold,
            }
        )

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez(directory / ARRAYS_FILE, **self._arrays())
        metadata = {
            "hidden_activation": HIDDEN_ACTIVATION,
            "output_activation": OUTPUT_ACTIVATION,
            "layers": len(self.network.coefs),
            "window_hours": self.window_hours,
            "weather_columns": self.weather_columns,
            "feature_names": _feature_names(self.window_hours, self.weather_columns),
            "threshold": self.threshold,
        }
        write_metadata(directory, MODEL_FORMAT, metadata)

    def _arrays(self) -> dict[str, np.ndarray]:
        layers = {}
        for layer, (coef, intercept) in enumerate(
            zip(self.network.coefs, self.network.intercepts, strict=True)
        ):
            layers[f"coef_{layer}"] = coef
            layers[f"intercept_{layer}"] = intercept
        return {"scaler_mean": self.scaler.mean, "scaler_scale": self.scaler.scale, **layers}

    @classmethod
    def load(cls, directory: Path) -> UnsupervisedReconstructionModel:
        metadata = read_metadata(directory, MODEL_FORMAT)
        _require_supported_activations(directory, metadata)
        with np.load(directory / ARRAYS_FILE, allow_pickle=False) as arrays:
            layers = range(metadata["layers"])
            network = NumpyMLP(
                coefs=tuple(arrays[f"coef_{layer}"] for layer in layers),
                intercepts=tuple(arrays[f"intercept_{layer}"] for layer in layers),
            )
            scaler = _Scaler(mean=arrays["scaler_mean"], scale=arrays["scaler_scale"])
        expected_inputs = len(metadata["feature_names"])
        if network.coefs[0].shape[0] != expected_inputs or scaler.mean.shape != (expected_inputs,):
            raise ValueError(f"Model arrays in {directory} do not match {expected_inputs} features")
        return cls(
            network,
            scaler,
            threshold=float(metadata["threshold"]),
            window_hours=int(metadata["window_hours"]),
            weather_columns=list(metadata["weather_columns"]),
        )


def _load_reconstruction_errors(
    network: NumpyMLP, scaler: _Scaler, features: np.ndarray, window_hours: int
) -> np.ndarray:
    """Mean squared reconstruction error over the standardized load hours of each window."""
    scaled = scaler.transform(features)
    reconstructed = network.predict(scaled)
    load = slice(0, window_hours)
    return np.mean((reconstructed[:, load] - scaled[:, load]) ** 2, axis=1)


def _require_supported_activations(directory: Path, metadata: Mapping[str, object]) -> None:
    activations = (metadata.get("hidden_activation"), metadata.get("output_activation"))
    if activations != (HIDDEN_ACTIVATION, OUTPUT_ACTIVATION):
        raise ValueError(f"Unsupported activations {activations} in {directory}")


# --- Windows -------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Windows:
    """Complete windows only: their end hours and raw feature rows in the same order."""

    end_times: pd.DatetimeIndex
    features: np.ndarray

    def select(self, mask: np.ndarray) -> _Windows:
        return _Windows(self.end_times[mask], self.features[mask])


def _build_windows(
    load: pd.DataFrame, weather: pd.DataFrame, weather_columns: list[str], window_hours: int
) -> _Windows:
    """Flatten each run of ``window_hours`` hours into one row; windows with any gap are dropped.

    Row layout: the window's load hours oldest first, then each weather column's
    and the weekend flag's hours oldest first, then the calendar encoding of the
    end hour.
    """
    hourly = _hourly_frame(load, weather, weather_columns)
    if len(hourly) < window_hours:
        return _Windows(
            pd.DatetimeIndex([]), np.empty((0, _input_width(window_hours, weather_columns)))
        )
    series = hourly[_series_columns(weather_columns)].to_numpy(dtype=float)
    stacked = sliding_window_view(series, window_hours, axis=0)
    flattened = stacked.reshape(len(stacked), -1)
    end_times = pd.DatetimeIndex(hourly[DATETIME_COL].iloc[window_hours - 1 :])
    features = np.hstack([flattened, _calendar_encoding(end_times)])
    complete = ~np.isnan(features).any(axis=1)
    return _Windows(end_times[complete], features[complete])


def _hourly_frame(
    load: pd.DataFrame, weather: pd.DataFrame, weather_columns: list[str]
) -> pd.DataFrame:
    """Load and weather on a gap-free hourly grid; missing load hours stay NaN."""
    load = _by_time(load[[DATETIME_COL, LOAD_MW_COL]])
    weather = _by_time(weather[[DATETIME_COL, *weather_columns]])
    if load.empty:
        return pd.DataFrame(columns=[DATETIME_COL, *_series_columns(weather_columns)])
    grid = pd.DataFrame(
        {DATETIME_COL: pd.date_range(load[DATETIME_COL].min(), load[DATETIME_COL].max(), freq="h")}
    )
    hourly = grid.merge(load, on=DATETIME_COL, how="left").merge(
        weather, on=DATETIME_COL, how="left"
    )
    hourly[weather_columns] = hourly[weather_columns].ffill(limit=WEATHER_FILL_LIMIT_HOURS)
    hourly[IS_WEEKEND_COL] = (hourly[DATETIME_COL].dt.dayofweek >= SATURDAY).astype(float)
    return hourly


def _series_columns(weather_columns: list[str]) -> list[str]:
    return [LOAD_MW_COL, *weather_columns, IS_WEEKEND_COL]


def _by_time(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result[DATETIME_COL] = pd.to_datetime(result[DATETIME_COL]).astype("datetime64[ns]")
    return result.drop_duplicates(DATETIME_COL, keep="last").sort_values(DATETIME_COL)


def _calendar_encoding(end_times: pd.DatetimeIndex) -> np.ndarray:
    hour = 2 * np.pi * end_times.hour.to_numpy() / HOURS_PER_DAY
    day = 2 * np.pi * end_times.dayofweek.to_numpy() / DAYS_PER_WEEK
    return np.column_stack([np.sin(hour), np.cos(hour), np.sin(day), np.cos(day)])


def _input_width(window_hours: int, weather_columns: list[str]) -> int:
    return window_hours * len(_series_columns(weather_columns)) + len(CALENDAR_FEATURES)


def _feature_names(window_hours: int, weather_columns: list[str]) -> list[str]:
    positions = range(window_hours - 1, -1, -1)
    series = [
        f"{column}_t-{position}"
        for column in _series_columns(weather_columns)
        for position in positions
    ]
    return [*series, *CALENDAR_FEATURES]


def _alternate_days(validation: _Windows) -> tuple[np.ndarray, np.ndarray]:
    """Calibration windows end on the 1st, 3rd, ... validation day; holdout on the 2nd, 4th, ..."""
    if len(validation.end_times) == 0:
        return validation.features, validation.features
    days = validation.end_times.normalize()
    day_position = (days - days.min()) // pd.Timedelta(days=1)
    is_holdout = np.asarray(day_position % 2 == 1)
    return validation.features[~is_holdout], validation.features[is_holdout]


def _require_enough_windows(
    training: np.ndarray, calibration: np.ndarray, validation_start: pd.Timestamp
) -> None:
    if len(training) == 0:
        raise ValueError(
            f"No complete training windows end before validation start "
            f"{validation_start.isoformat()}"
        )
    if len(calibration) == 0:
        raise ValueError(
            f"No complete validation windows end at or after {validation_start.isoformat()} "
            "to set the anomaly threshold"
        )


# --- Synthetic anomalies -------------------------------------------------------------------


def _sudden_drop(features: np.ndarray, window_hours: int) -> np.ndarray:
    """The latest hours of the window lose a fraction of their load, as in a large outage."""
    injected = features.copy()
    injected[:, window_hours - SUDDEN_DROP_HOURS : window_hours] *= 1.0 - SUDDEN_DROP_FRACTION
    return injected


def _pattern_swap(features: np.ndarray, window_hours: int) -> np.ndarray:
    """The same load values rotated by half the window, e.g. night-time demand at noon.

    Half the window is twelve hours for a day-long window; a fixed twelve would hand a
    6- or 12-hour window back unchanged and report the false positive rate as recall.
    """
    injected = features.copy()
    injected[:, :window_hours] = np.roll(features[:, :window_hours], window_hours // 2, axis=1)
    return injected


def _level_shift(features: np.ndarray, window_hours: int) -> np.ndarray:
    """The whole window keeps its shape at a higher level than its conditions explain."""
    injected = features.copy()
    injected[:, :window_hours] *= 1.0 + LEVEL_SHIFT_FRACTION
    return injected


SYNTHETIC_ANOMALIES: Mapping[str, Callable[[np.ndarray, int], np.ndarray]] = {
    "sudden_drop": _sudden_drop,
    "pattern_swap": _pattern_swap,
    "level_shift": _level_shift,
}
