"""Task type seam: pure computation adapters fed with in-memory data by the runner (ADR-0009).

Task types never touch repositories. The runner applies the shared components
(accumulation gate, data retrieval, stale load anchor, weather resolution with
degradation) and hands each task type frames it can trust.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import ClassVar, Protocol, TypeVar

import pandas as pd
from pydantic import BaseModel

from shiro_mlops.core.constants import DATETIME_COL

P = TypeVar("P", bound=BaseModel)


class WeatherInput(Enum):
    """Which weather a task type consumes when predicting."""

    FORECAST = "forecast"
    OBSERVED = "observed"


@dataclass(frozen=True)
class HistoryCoverage:
    """Valid target hours a prediction needs in the ``window_hours`` ending at the anchor."""

    window_hours: int
    min_valid_hours: int


@dataclass(frozen=True)
class InputRequirements:
    """Inputs a task type needs, so the runner can fetch bounded history."""

    weather: WeatherInput
    lookback_hours: int
    # 歷史不足時由 runner 拒絕並回報不可用，任務類型不必在預測時自行失敗；None 表示不檢查。
    history_coverage: HistoryCoverage | None = None


@dataclass(frozen=True)
class TrainingData:
    """Training inputs; training always uses observed weather.

    ``load`` holds ``datetime``, ``subject`` and ``load_mw``; ``weather`` holds
    ``datetime`` and the task's weather fields from its weather reference point.
    """

    load: pd.DataFrame
    weather: pd.DataFrame
    # 共用時間切分點：target 時間 >= 此值者為驗證列，各任務類型不得自行切分。
    validation_start: pd.Timestamp

    @property
    def weather_columns(self) -> list[str]:
        """The task's weather fields: every weather column except the time key."""
        return [column for column in self.weather.columns if column != DATETIME_COL]


@dataclass(frozen=True)
class PredictionData:
    """Prediction inputs, delivered only with a fresh load anchor and full weather coverage."""

    anchor: pd.Timestamp
    load_history: pd.DataFrame
    weather: pd.DataFrame
    horizon_hours: int | None


def split_at_validation(
    rows: pd.DataFrame, validation_start: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rows to fit and rows to validate, by target ``datetime``; no rows to fit is refused.

    Validation may be empty: task types then report no metrics rather than
    placeholders, so ``assess_health`` warns about the unvalidated model.
    """
    is_validation = rows[DATETIME_COL] >= validation_start
    fitting, validation = rows.loc[~is_validation], rows.loc[is_validation]
    if fitting.empty:
        raise ValueError(f"No training rows before validation start {validation_start.isoformat()}")
    return fitting, validation


class WeatherEchoingItem(BaseModel):
    """Marks a prediction item that repeats the weather behind each predicted hour.

    The task type declares only its own fields; the serving layer adds the task's
    ``weather.fields`` and their ``weather_sources``, so items follow the task
    definition instead of a fixed weather list.
    """


class TaskModel(Protocol):
    """A trained model that predicts from in-memory data and saves itself natively."""

    def predict(self, data: PredictionData) -> pd.DataFrame: ...

    def save(self, directory: Path) -> None:
        """Write native, non-executable files only (ADR-0010)."""
        ...


@dataclass(frozen=True)
class Trained:
    """A fitted model with its out-of-time validation metrics."""

    model: TaskModel
    metrics: Mapping[str, float]


class HealthStatus(StrEnum):
    """Monitoring verdict on a trained model."""

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"


@dataclass(frozen=True)
class HealthAssessment:
    """A monitoring verdict with the metric and threshold that decided it."""

    status: HealthStatus
    reason: str


class TaskType(Protocol[P]):
    """How one family of tasks builds labels, trains, evaluates, predicts, and persists."""

    name: ClassVar[str]
    params_model: ClassVar[type[P]]
    # 回應 schema 依任務類型與任務設定的天氣欄位而定（ADR-0009）：服務層以此組成
    # /tasks/{task_id}/predict 的回應與 OpenAPI；繼承 WeatherEchoingItem 者另補上天氣欄位與來源。
    prediction_item: ClassVar[type[BaseModel]]
    # 健康判定門檻的 schema；門檻值來自任務設定 [health]，判定規則屬於任務類型。
    health_model: ClassVar[type[BaseModel]]

    def requirements(self, params: P) -> InputRequirements: ...

    def train(self, params: P, data: TrainingData) -> Trained: ...

    def load(self, directory: Path) -> TaskModel: ...

    def assess_health(
        self, thresholds: BaseModel, metrics: Mapping[str, float]
    ) -> HealthAssessment: ...
