"""High-load alert through the runner: shared components apply to it like any other task."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import deployed_task
from shiro_mlops.tasks.runner import (
    InputsUnavailable,
    InsufficientLoadHistoryError,
    StaleLoadAnchorError,
    TaskNotReady,
    TaskRuntime,
    check_task_ready,
    monitor_task,
    predict_task,
    train_task,
)
from shiro_mlops.tasks.types.base import HealthStatus, TaskModel
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

HIGH_LOAD_ALERT = "high_load_alert"
LAST_HOUR = datetime(2026, 9, 20, 23, 0)
ANCHOR = pd.Timestamp(LAST_HOUR)
HOURS = 24 * 21
HORIZON_HOURS = 6
FRESH_AS_OF = ANCHOR + pd.Timedelta(minutes=30)
STALE_AS_OF = ANCHOR + pd.Timedelta(hours=3, minutes=1)


@pytest.fixture
def shipped() -> TaskDefinition:
    return deployed_task(HIGH_LOAD_ALERT)


@pytest.fixture
def task(shipped: TaskDefinition) -> TaskDefinition:
    """The shipped task with a 7-day threshold window so 21 days of load can train it."""
    params = shipped.params.model_copy(
        update={
            "threshold": shipped.params.threshold.model_copy(update={"window_days": 7}),
            "model": shipped.params.model.model_copy(update={"n_estimators": 20}),
        }
    )
    policies = shipped.policies.model_copy(update={"min_training_hours": HOURS})
    return replace(shipped, params=params, policies=policies)


@pytest.fixture
def runtime(test_repo: TimeSeriesRepository) -> TaskRuntime:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    write_derived_load(test_repo.engine, load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return task_runtime(test_repo)


@pytest.fixture
def model(task: TaskDefinition, runtime: TaskRuntime) -> TaskModel:
    return train_task(task, runtime, as_of=FRESH_AS_OF).model


def test_shipped_minimum_accumulation_blocks_training(
    shipped: TaskDefinition, runtime: TaskRuntime
) -> None:
    with pytest.raises(TaskNotReady, match=f"{HOURS} valid hourly observations; 1344 required"):
        train_task(shipped, runtime, as_of=FRESH_AS_OF)


def test_runner_trains_and_reports_classification_metrics(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    trained = train_task(task, runtime, as_of=FRESH_AS_OF)

    assert set(trained.metrics) == {"precision", "recall", "f1"}


def test_missing_forecast_degrades_and_keeps_one_prediction_per_weather_hour(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    outcome = predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert outcome.mode == "degraded"
    assert outcome.predictions["datetime"].tolist() == outcome.weather["datetime"].tolist()
    assert len(outcome.weather_sources) == HORIZON_HOURS


def test_stale_load_anchor_refuses_the_alert(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    with pytest.raises(StaleLoadAnchorError):
        predict_task(task, model, runtime, as_of=STALE_AS_OF, horizon_hours=HORIZON_HOURS)


def _drop_load_hours(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch, start: pd.Timestamp, hours: int
) -> None:
    """Serve persisted load without ``hours`` consecutive hours from ``start``."""
    store = runtime.hourly_actual_load
    series = store.series
    end = start + pd.Timedelta(hours=hours - 1)

    def gapped(**kwargs):
        load = series(**kwargs)
        return load[~load["datetime"].between(start, end)]

    monkeypatch.setattr(store, "series", gapped)


@pytest.mark.parametrize(
    ("gap_start", "gap_hours"),
    [
        # A single missing hour leaves the threshold window incomplete.
        (ANCHOR - pd.Timedelta(hours=72), 1),
        # 只剩錨點前 101 小時：歷史未涵蓋門檻窗。
        (ANCHOR - pd.Timedelta(days=20), 24 * 20 - 100),
    ],
)
def test_threshold_window_without_enough_load_history_is_unavailable(
    task: TaskDefinition,
    runtime: TaskRuntime,
    model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
    gap_start: pd.Timestamp,
    gap_hours: int,
) -> None:
    _drop_load_hours(runtime, monkeypatch, gap_start, gap_hours)

    with pytest.raises(InsufficientLoadHistoryError, match="168-hour window"):
        predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    readiness = check_task_ready(task, model, runtime, as_of=FRESH_AS_OF)
    assert isinstance(readiness, InputsUnavailable)
    assert "168-hour window" in readiness.reason


def test_monitoring_judges_metrics_with_the_configured_floors(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    healthy = monitor_task(
        task, runtime, {"precision": 0.9, "recall": 0.9, "f1": 0.9}, as_of=FRESH_AS_OF
    )
    missing_f1 = monitor_task(task, runtime, {"precision": 0.9, "recall": 0.9}, as_of=FRESH_AS_OF)

    assert healthy.health.status is HealthStatus.HEALTHY
    assert missing_f1.health.status is HealthStatus.WARNING
