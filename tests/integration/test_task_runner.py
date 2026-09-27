"""Runner behaviour over a SQLite repository with explicit point-in-time ``as_of`` values."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from shiro_mlops.data.cwa_client import CWAForecastRelease, CWATownshipForecast
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import (
    MissingLoadHistoryError,
    StaleLoadAnchorError,
    TaskNotReady,
    TaskRuntime,
    check_task_ready,
    fit_task,
    load_training_data,
    monitor_task,
    predict_task,
    train_task,
    training_data_from_table,
    training_table,
)
from shiro_mlops.tasks.types.base import HealthStatus, TaskModel
from tests.helpers import canonical_observation_batch, hourly_load_with_weather

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
ANCHOR = pd.Timestamp(LAST_HOUR)
HOURS = 24 * 21
HORIZON_HOURS = 6
FRESH_AS_OF = ANCHOR + pd.Timedelta(minutes=30)
STALE_AS_OF = ANCHOR + pd.Timedelta(hours=3, minutes=1)


@pytest.fixture
def task() -> TaskDefinition:
    """The shipped task with a threshold the 21-day fixture meets and a faster model."""
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    params = shipped.params.model_copy(
        update={"model": shipped.params.model.model_copy(update={"n_estimators": 20})}
    )
    policies = shipped.policies.model_copy(update={"min_training_hours": HOURS})
    return replace(shipped, params=params, policies=policies)


@pytest.fixture
def runtime(test_repo: TimeSeriesRepository) -> TaskRuntime:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    test_repo.upsert_taipower_load(load)
    test_repo.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return TaskRuntime(repository=test_repo)


@pytest.fixture
def model(task: TaskDefinition, runtime: TaskRuntime) -> TaskModel:
    return train_task(task, runtime, as_of=FRESH_AS_OF).model


def _fresh_forecast_release() -> CWAForecastRelease:
    issued_at = ANCHOR - pd.Timedelta(hours=1)
    return CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=issued_at,
        source_updated_at=issued_at,
        fetched_at=issued_at.to_pydatetime(),
        status="complete",
        missing_geocodes=(),
        raw_payload={"fixture": "runner"},
        forecasts=tuple(
            CWATownshipForecast(
                valid_from=ANCHOR + pd.Timedelta(hours=hour),
                valid_to=ANCHOR + pd.Timedelta(hours=hour),
                geocode="63000000",
                location_name="臺北市",
                temperature_c=30.0,
                dew_point_c=None,
                apparent_temperature_c=None,
                relative_humidity_pct=70.0,
                probability_of_precipitation_pct=None,
                wind_speed_m_s=None,
                wind_direction=None,
            )
            for hour in range(1, HORIZON_HOURS + 1)
        ),
    )


# --- Training ------------------------------------------------------------------------------


def test_training_below_minimum_accumulation_raises_task_not_ready(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    short_of_threshold = replace(
        task, policies=task.policies.model_copy(update={"min_training_hours": HOURS + 1})
    )

    with pytest.raises(TaskNotReady, match=f"{HOURS} valid hourly observations") as error:
        train_task(short_of_threshold, runtime, as_of=FRESH_AS_OF)

    assert error.value.readiness.required_hours == HOURS + 1


def test_training_data_splits_the_latest_validation_fraction_of_target_hours(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    data = load_training_data(task, runtime, as_of=FRESH_AS_OF)

    expected_split = data.load["datetime"].iloc[int(HOURS * 0.8)]
    assert data.validation_start == expected_split
    assert list(data.weather.columns) == ["datetime", "temperature", "relative_humidity"]


def test_training_reports_out_of_time_metrics(task: TaskDefinition, runtime: TaskRuntime) -> None:
    trained = train_task(task, runtime, as_of=FRESH_AS_OF)

    assert 0.0 < trained.metrics["mape"] < 5.0


def test_training_table_round_trip_trains_the_same_model(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    """資產以單一訓練表跨 run 保存；還原後須與直接讀取的訓練資料訓練出相同結果。"""
    data = load_training_data(task, runtime, as_of=FRESH_AS_OF)

    restored = training_data_from_table(task, training_table(data))

    assert restored.validation_start == data.validation_start
    assert len(restored.weather) == len(data.weather)
    assert fit_task(task, restored).metrics == train_task(task, runtime, as_of=FRESH_AS_OF).metrics


def test_training_table_round_trip_keeps_weather_gaps_as_gaps(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    data = load_training_data(task, runtime, as_of=FRESH_AS_OF)
    gap = data.weather["datetime"].iloc[100]
    with_gap = replace(data, weather=data.weather[data.weather["datetime"] != gap])

    restored = training_data_from_table(task, training_table(with_gap))

    assert gap not in set(restored.weather["datetime"])
    assert restored.weather[["temperature", "relative_humidity"]].notna().all().all()


# --- Monitoring ----------------------------------------------------------------------------


def test_monitoring_reports_latest_target_and_healthy_metrics(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    report = monitor_task(task, runtime, {"mape": 3.0, "rmse": 1.0}, as_of=FRESH_AS_OF)

    assert report.task_id == task.task_id
    assert report.health.status is HealthStatus.HEALTHY
    assert report.target_hours == HOURS
    assert report.latest_target_time == ANCHOR
    expected_load, _ = hourly_load_with_weather(HOURS, LAST_HOUR)
    assert report.latest_target_value == pytest.approx(expected_load["load_mw"].iloc[-1])


def test_monitoring_warns_when_metrics_breach_the_configured_threshold(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    strict = replace(task, health=task.health.model_copy(update={"max_mape": 2.0}))

    report = monitor_task(strict, runtime, {"mape": 3.0}, as_of=FRESH_AS_OF)

    assert report.health.status is HealthStatus.WARNING
    assert "max_mape=2.0" in report.health.reason


def test_monitoring_below_minimum_accumulation_raises_task_not_ready(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    short_of_threshold = replace(
        task, policies=task.policies.model_copy(update={"min_training_hours": HOURS + 1})
    )

    with pytest.raises(TaskNotReady):
        monitor_task(short_of_threshold, runtime, {"mape": 3.0}, as_of=FRESH_AS_OF)


# --- Serving -------------------------------------------------------------------------------


def test_stale_load_anchor_refuses_prediction_and_readiness(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    with pytest.raises(StaleLoadAnchorError, match=f"latest actual load at {ANCHOR.isoformat()}"):
        predict_task(task, model, runtime, as_of=STALE_AS_OF, horizon_hours=HORIZON_HOURS)

    readiness = check_task_ready(task, model, runtime, as_of=STALE_AS_OF)
    assert not readiness.ready
    assert readiness.mode is None
    assert "Stale load anchor" in readiness.reason


def test_missing_forecast_degrades_to_previous_day_observations(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    outcome = predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert outcome.mode == "degraded"
    assert outcome.subject == "nationwide"
    assert len(outcome.predictions) == HORIZON_HOURS
    assert {source["temperature"]["source"] for source in outcome.weather_sources} == {
        "previous_day_observation"
    }
    assert check_task_ready(task, model, runtime, as_of=FRESH_AS_OF).mode == "degraded"


def test_fresh_forecast_keeps_normal_mode(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    runtime.repository.upsert_cwa_forecast_release(_fresh_forecast_release())

    outcome = predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert outcome.mode == "normal"
    assert outcome.weather["temperature"].tolist() == [30.0] * HORIZON_HOURS


def test_serving_reads_load_history_bounded_by_the_task_lookback(
    task: TaskDefinition,
    runtime: TaskRuntime,
    model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = runtime.repository
    calls: list[dict] = []
    fetch_load_range = repository.fetch_load_range

    def record(**kwargs):
        calls.append(kwargs)
        return fetch_load_range(**kwargs)

    monkeypatch.setattr(repository, "fetch_load_range", record)

    predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert [(call["start_time"], call["end_time"]) for call in calls] == [
        (ANCHOR - pd.Timedelta(hours=168), ANCHOR)
    ]


def test_rows_persisted_after_as_of_never_anchor_the_forecast(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    earlier_as_of = ANCHOR - pd.Timedelta(hours=1, minutes=30)

    outcome = predict_task(task, model, runtime, as_of=earlier_as_of, horizon_hours=1)

    assert outcome.predictions["datetime"].tolist() == [ANCHOR - pd.Timedelta(hours=1)]


def test_missing_model_is_not_ready(task: TaskDefinition, runtime: TaskRuntime) -> None:
    readiness = check_task_ready(task, None, runtime, as_of=FRESH_AS_OF)

    assert not readiness.ready
    assert readiness.reason == "Model is not loaded or trained yet."


def test_subject_without_history_raises_missing_load_history(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    north = replace(task, subject="north")

    with pytest.raises(MissingLoadHistoryError, match="No persisted north load history"):
        predict_task(north, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)
