"""Runner behaviour over a SQLite repository with explicit point-in-time ``as_of`` values."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import CWAForecastRelease, CWATownshipForecast
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.tasks import runner
from shiro_mlops.tasks.definition import TaskDefinition, WeightedReferencePoint
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import (
    InsufficientLoadHistoryError,
    MissingLoadHistoryError,
    ObservedInputsIncompleteError,
    StaleLoadAnchorError,
    TaskNotReady,
    TaskRuntime,
    WeatherUnavailableError,
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
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

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
    write_derived_load(test_repo.engine, load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return task_runtime(test_repo)


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


def test_training_gate_counts_only_load_known_by_as_of(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    as_of = LAST_HOUR - pd.Timedelta(hours=1)

    with pytest.raises(TaskNotReady) as error:
        load_training_data(task, runtime, as_of=as_of)

    assert error.value.readiness.valid_hours == HOURS - 1
    assert error.value.readiness.required_hours == HOURS


def test_training_reads_no_target_hour_starting_after_as_of(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    as_of = LAST_HOUR - pd.Timedelta(minutes=30)
    known = replace(
        task, policies=task.policies.model_copy(update={"min_training_hours": HOURS - 1})
    )

    data = load_training_data(known, runtime, as_of=as_of)

    assert data.load["datetime"].max() == ANCHOR - pd.Timedelta(hours=1)


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
    """A stored training table must restore the same training outcome as direct data loading."""
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


def test_training_table_round_trip_preserves_weather_on_load_missing_hours(
    task: TaskDefinition, test_repo: TimeSeriesRepository
) -> None:
    """Seam: load_training_data -> training_table -> training_data_from_table -> fit_task.

    When load misses hour N and weather misses hour N+1, the weather observation at
    hour N must survive training_table serialization so backward weather alignment
    fills hour N+1 identically to direct database training.
    """
    load, weather = hourly_load_with_weather(HOURS + 1, LAST_HOUR)
    hour_n = pd.Timestamp(load["datetime"].iloc[200])
    hour_n_plus_1 = pd.Timestamp(load["datetime"].iloc[201])
    gapped_load = load[load["datetime"] != hour_n].reset_index(drop=True)
    gapped_weather = weather[weather["datetime"] != hour_n_plus_1].reset_index(drop=True)
    write_derived_load(test_repo.engine, gapped_load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(gapped_weather.assign(location="Taipei"))
    )
    gapped_runtime = task_runtime(test_repo)

    direct = load_training_data(task, gapped_runtime, as_of=FRESH_AS_OF)
    table = training_table(direct)
    restored = training_data_from_table(task, table)

    assert hour_n in set(table["datetime"])
    assert hour_n not in set(restored.load["datetime"])
    assert hour_n in set(restored.weather["datetime"])
    assert hour_n_plus_1 in set(restored.load["datetime"])
    assert hour_n_plus_1 not in set(restored.weather["datetime"])
    pd.testing.assert_frame_equal(restored.load, direct.load)
    pd.testing.assert_frame_equal(restored.weather, direct.weather)
    assert restored.validation_start == direct.validation_start

    direct_trained = train_task(task, gapped_runtime, as_of=FRESH_AS_OF)
    restored_trained = fit_task(task, restored)
    assert restored_trained.metrics == direct_trained.metrics
    assert restored_trained.model.booster.model_to_string() == (
        direct_trained.model.booster.model_to_string()
    )


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


def test_monitoring_gate_counts_only_load_known_by_as_of(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    as_of = LAST_HOUR - pd.Timedelta(hours=1)

    with pytest.raises(TaskNotReady) as error:
        monitor_task(task, runtime, {"mape": 3.0}, as_of=as_of)

    assert error.value.readiness.valid_hours == HOURS - 1


def test_monitoring_report_counts_only_load_known_by_as_of(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    threshold = replace(
        task, policies=task.policies.model_copy(update={"min_training_hours": HOURS - 1})
    )
    as_of = LAST_HOUR - pd.Timedelta(hours=1)

    report = monitor_task(threshold, runtime, {"mape": 3.0}, as_of=as_of)

    assert report.target_hours == HOURS - 1
    assert report.latest_target_time == as_of


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
    assert {source["temperature"]["Taipei"]["source"] for source in outcome.weather_sources} == {
        "previous_day_observation"
    }
    assert check_task_ready(task, model, runtime, as_of=FRESH_AS_OF).mode == "degraded"


def test_fresh_forecast_keeps_normal_mode(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    runtime.cwa_weather.upsert_cwa_forecast_releases([_fresh_forecast_release()])

    outcome = predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert outcome.mode == "normal"
    assert outcome.weather["temperature"].tolist() == [30.0] * HORIZON_HOURS


def test_serving_reads_load_history_bounded_by_the_task_lookback(
    task: TaskDefinition,
    runtime: TaskRuntime,
    model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = _record_load_reads(runtime, monkeypatch)

    predict_task(task, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)

    assert reads == [(ANCHOR - pd.Timedelta(hours=168), ANCHOR + pd.Timedelta(hours=1))]


def test_rows_persisted_after_as_of_never_anchor_the_forecast(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    earlier_as_of = ANCHOR - pd.Timedelta(hours=1, minutes=30)

    outcome = predict_task(task, model, runtime, as_of=earlier_as_of, horizon_hours=1)

    assert outcome.predictions["datetime"].tolist() == [ANCHOR - pd.Timedelta(hours=1)]


def test_prediction_reports_the_load_anchor_known_at_as_of(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    earlier_as_of = ANCHOR - pd.Timedelta(hours=1, minutes=30)

    outcome = predict_task(task, model, runtime, as_of=earlier_as_of, horizon_hours=1)

    assert outcome.load_anchor == ANCHOR - pd.Timedelta(hours=2)


def test_forecast_task_readiness_resolves_weather_for_the_full_horizon(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel, monkeypatch
) -> None:
    """Readiness checks weather across the full 168-hour forecast horizon required by docs/reference/ml-tasks.md §3."""
    requested_horizons: list[int] = []
    resolve = runner.resolve_weather

    def recording_resolve(*args, **kwargs):
        requested_horizons.append(kwargs["horizon_hours"])
        return resolve(*args, **kwargs)

    monkeypatch.setattr(runner, "resolve_weather", recording_resolve)

    readiness = check_task_ready(task, model, runtime, as_of=FRESH_AS_OF)

    assert readiness.ready
    assert requested_horizons == [168]


@pytest.fixture
def task_trainable_with_one_gap(task: TaskDefinition) -> TaskDefinition:
    """The runner task with a threshold the fixture still meets once one load hour is missing."""
    policies = task.policies.model_copy(update={"min_training_hours": HOURS - 1})
    return replace(task, policies=policies)


def _runtime_missing_load_hour(
    repository: TimeSeriesRepository, missing: pd.Timestamp
) -> TaskRuntime:
    """Persist the 21-day fixture without the actual load of one ``missing`` hour."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    write_derived_load(repository.engine, load[load["datetime"] != missing])
    repository.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return task_runtime(repository)


@pytest.mark.parametrize(
    "missing",
    [
        # 錨點前一小時：第一步的 lag 2。
        ANCHOR - pd.Timedelta(hours=1),
        # lookback 最早的一小時：第一步的 lag 168。
        ANCHOR - pd.Timedelta(hours=167),
    ],
)
def test_missing_load_hour_in_the_lookback_refuses_prediction_and_readiness(
    task_trainable_with_one_gap: TaskDefinition,
    test_repo: TimeSeriesRepository,
    missing: pd.Timestamp,
) -> None:
    """Missing actual load has no substitute, so the recursion never stands in 0 MW for a lag."""
    runtime = _runtime_missing_load_hour(test_repo, missing)
    model = train_task(task_trainable_with_one_gap, runtime, as_of=FRESH_AS_OF).model

    with pytest.raises(
        InsufficientLoadHistoryError, match="167 nationwide load hours in the 168-hour"
    ):
        predict_task(
            task_trainable_with_one_gap,
            model,
            runtime,
            as_of=FRESH_AS_OF,
            horizon_hours=HORIZON_HOURS,
        )

    readiness = check_task_ready(task_trainable_with_one_gap, model, runtime, as_of=FRESH_AS_OF)
    assert not readiness.ready
    assert readiness.mode is None
    assert "168-hour window" in readiness.reason


def test_missing_load_hour_in_the_lookback_refuses_before_reading_weather(
    task_trainable_with_one_gap: TaskDefinition,
    test_repo: TimeSeriesRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A load shortfall is reported first, so a refused request costs no weather query."""
    runtime = _runtime_missing_load_hour(test_repo, ANCHOR - pd.Timedelta(hours=1))
    model = train_task(task_trainable_with_one_gap, runtime, as_of=FRESH_AS_OF).model
    weather_reads: list[object] = []
    monkeypatch.setattr(
        runner, "resolve_weather", lambda *args, **kwargs: weather_reads.append(kwargs)
    )

    with pytest.raises(InsufficientLoadHistoryError):
        predict_task(
            task_trainable_with_one_gap,
            model,
            runtime,
            as_of=FRESH_AS_OF,
            horizon_hours=HORIZON_HOURS,
        )
    assert not check_task_ready(
        task_trainable_with_one_gap, model, runtime, as_of=FRESH_AS_OF
    ).ready

    assert weather_reads == []


def test_missing_load_hour_before_the_lookback_still_predicts(
    task_trainable_with_one_gap: TaskDefinition, test_repo: TimeSeriesRepository
) -> None:
    runtime = _runtime_missing_load_hour(test_repo, ANCHOR - pd.Timedelta(hours=168))
    model = train_task(task_trainable_with_one_gap, runtime, as_of=FRESH_AS_OF).model

    outcome = predict_task(
        task_trainable_with_one_gap, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
    )

    assert len(outcome.predictions) == HORIZON_HOURS
    assert check_task_ready(task_trainable_with_one_gap, model, runtime, as_of=FRESH_AS_OF).ready


def test_subject_without_history_raises_missing_load_history(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    north = replace(task, subject="north")

    with pytest.raises(MissingLoadHistoryError, match="No persisted north load history"):
        predict_task(north, model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS)


# --- Serving with observed weather (load_pattern_anomaly) ----------------------------------

ANOMALY_TASK = "load_pattern_anomaly"


@pytest.fixture
def anomaly_task() -> TaskDefinition:
    """The shipped anomaly task with a threshold the 21-day fixture meets."""
    shipped = deployed_task(ANOMALY_TASK)
    policies = shipped.policies.model_copy(update={"min_training_hours": HOURS})
    return replace(shipped, policies=policies)


@pytest.fixture
def anomaly_model(anomaly_task: TaskDefinition, runtime: TaskRuntime) -> TaskModel:
    return train_task(anomaly_task, runtime, as_of=FRESH_AS_OF).model


def test_observed_prediction_scores_window_end_hours_up_to_the_anchor(
    anomaly_task: TaskDefinition, runtime: TaskRuntime, anomaly_model: TaskModel
) -> None:
    """The observed-weather path stays normal and aligns each weather row with a scored window end."""
    outcome = predict_task(
        anomaly_task, anomaly_model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
    )

    expected_hours = [ANCHOR - pd.Timedelta(hours=h) for h in range(HORIZON_HOURS - 1, -1, -1)]
    assert outcome.mode == "normal"
    assert outcome.subject == "nationwide"
    assert outcome.predictions["datetime"].tolist() == expected_hours
    assert outcome.weather["datetime"].tolist() == expected_hours
    assert list(outcome.weather.columns) == ["datetime", "temperature", "relative_humidity"]
    assert len(outcome.weather_sources) == HORIZON_HOURS
    assert outcome.weather_sources[-1]["temperature"] == {
        "Taipei": {"source": "station_observation", "observed_at": ANCHOR.isoformat()}
    }
    assert check_task_ready(anomaly_task, anomaly_model, runtime, as_of=FRESH_AS_OF).mode == (
        "normal"
    )


def test_observed_prediction_reads_history_for_the_window_and_the_longest_horizon(
    anomaly_task: TaskDefinition,
    runtime: TaskRuntime,
    anomaly_model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = runtime.cwa_weather
    load_reads = _record_load_reads(runtime, monkeypatch)
    weather_calls: list[dict] = []
    fetch_weather_range = store.fetch_weather_range

    def record_weather(**kwargs):
        weather_calls.append(kwargs)
        return fetch_weather_range(**kwargs)

    monkeypatch.setattr(store, "fetch_weather_range", record_weather)

    predict_task(anomaly_task, anomaly_model, runtime, as_of=FRESH_AS_OF, horizon_hours=1)

    history_start = ANCHOR - pd.Timedelta(hours=24 + 168)
    assert load_reads == [(history_start, ANCHOR + pd.Timedelta(hours=1))]
    assert [(call["start_time"], call["end_time"]) for call in weather_calls] == [
        (history_start, ANCHOR)
    ]


def test_observed_prediction_still_refuses_a_stale_load_anchor(
    anomaly_task: TaskDefinition, runtime: TaskRuntime, anomaly_model: TaskModel
) -> None:
    with pytest.raises(StaleLoadAnchorError, match="Stale load anchor"):
        predict_task(anomaly_task, anomaly_model, runtime, as_of=STALE_AS_OF, horizon_hours=1)

    readiness = check_task_ready(anomaly_task, anomaly_model, runtime, as_of=STALE_AS_OF)
    assert not readiness.ready
    assert "Stale load anchor" in readiness.reason


def test_observed_prediction_without_observations_is_unavailable(
    anomaly_task: TaskDefinition, runtime: TaskRuntime, anomaly_model: TaskModel
) -> None:
    elsewhere = replace(
        anomaly_task,
        weather=replace(
            anomaly_task.weather,
            reference_points=(WeightedReferencePoint(settings.cwa_locations["Kaohsiung"], 1.0),),
        ),
    )

    with pytest.raises(WeatherUnavailableError, match="No observed weather"):
        predict_task(elsewhere, anomaly_model, runtime, as_of=FRESH_AS_OF, horizon_hours=1)

    assert not check_task_ready(elsewhere, anomaly_model, runtime, as_of=FRESH_AS_OF).ready


def test_observed_prediction_with_no_scorable_window_is_unavailable(
    anomaly_task: TaskDefinition,
    runtime: TaskRuntime,
    anomaly_model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without recent observations, an unscorable anchor window is unavailable rather than an empty result."""
    store = runtime.cwa_weather
    fetch_weather_range = store.fetch_weather_range
    last_observation = ANCHOR - pd.Timedelta(hours=3)

    def observations_until_three_hours_before_anchor(**kwargs):
        return fetch_weather_range(**{**kwargs, "end_time": last_observation})

    monkeypatch.setattr(store, "fetch_weather_range", observations_until_three_hours_before_anchor)

    with pytest.raises(ObservedInputsIncompleteError, match="No complete observed window"):
        predict_task(anomaly_task, anomaly_model, runtime, as_of=FRESH_AS_OF, horizon_hours=1)

    readiness = check_task_ready(anomaly_task, anomaly_model, runtime, as_of=FRESH_AS_OF)
    assert not readiness.ready
    assert "No complete observed window" in readiness.reason


# --- Weighted weather (ADR-0012) -----------------------------------------------------------

WEIGHTS = {"Taipei": 0.5, "Taichung": 0.3, "Kaohsiung": 0.2}
# 臺中比臺北低 2 度、高雄高 2 度：加權氣溫 = 臺北 × 0.5 + (臺北 − 2) × 0.3 + (臺北 + 2) × 0.2
# = 臺北 − 0.2；濕度同樣位移。
OFFSETS = {"Taichung": -2.0, "Kaohsiung": 2.0}
WEIGHTED_OFFSET = -0.2
GEOCODES = {"Taipei": "63000000", "Taichung": "66000000", "Kaohsiung": "64000000"}


def _weighted(task: TaskDefinition) -> TaskDefinition:
    points = tuple(
        WeightedReferencePoint(settings.cwa_locations[name], weight)
        for name, weight in WEIGHTS.items()
    )
    return replace(task, weather=replace(task.weather, reference_points=points))


def _observe(runtime: TaskRuntime, name: str, *, skip: pd.Timestamp | None = None) -> None:
    _, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    shifted = weather.assign(
        temperature=weather["temperature"] + OFFSETS[name],
        relative_humidity=weather["relative_humidity"] + OFFSETS[name],
        location=name,
    )
    if skip is not None:
        shifted = shifted[shifted["datetime"] != skip]
    runtime.cwa_weather.upsert_cwa_observation_batch(canonical_observation_batch(shifted))


def _release_for(*names: str) -> CWAForecastRelease:
    """A fresh three-day release where each point's forecast sits at its observation offset."""
    taipei = _fresh_forecast_release()
    forecasts = tuple(
        replace(
            forecast,
            geocode=GEOCODES[name],
            temperature_c=forecast.temperature_c + OFFSETS.get(name, 0.0),
            relative_humidity_pct=forecast.relative_humidity_pct + OFFSETS.get(name, 0.0),
        )
        for name in names
        for forecast in taipei.forecasts
    )
    return replace(taipei, forecasts=forecasts)


def test_training_weather_is_the_weighted_weather_of_every_reference_point(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    for name in OFFSETS:
        _observe(runtime, name)

    data = load_training_data(_weighted(task), runtime, as_of=FRESH_AS_OF)

    _, taipei = hourly_load_with_weather(HOURS, LAST_HOUR)
    weighted = data.weather.set_index("datetime").reindex(taipei["datetime"])
    assert weighted["temperature"].to_numpy() == pytest.approx(
        (taipei["temperature"] + WEIGHTED_OFFSET).to_numpy()
    )
    assert weighted["relative_humidity"].to_numpy() == pytest.approx(
        (taipei["relative_humidity"] + WEIGHTED_OFFSET).to_numpy()
    )


def test_training_weather_has_no_value_where_any_reference_point_misses_the_hour(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    gap = ANCHOR - pd.Timedelta(hours=30)
    _observe(runtime, "Taichung")
    _observe(runtime, "Kaohsiung", skip=gap)

    data = load_training_data(_weighted(task), runtime, as_of=FRESH_AS_OF)

    by_hour = data.weather.set_index("datetime").reindex([gap, gap - pd.Timedelta(hours=1)])
    assert by_hour.loc[gap].isna().all()
    assert by_hour.loc[gap - pd.Timedelta(hours=1)].notna().all()


def test_weighted_training_table_round_trip_is_lossless(
    task: TaskDefinition, runtime: TaskRuntime
) -> None:
    _observe(runtime, "Taichung")
    _observe(runtime, "Kaohsiung", skip=ANCHOR - pd.Timedelta(hours=30))
    weighted = _weighted(task)
    direct = load_training_data(weighted, runtime, as_of=FRESH_AS_OF)

    restored = training_data_from_table(weighted, training_table(direct))

    pd.testing.assert_frame_equal(restored.load, direct.load)
    pd.testing.assert_frame_equal(
        restored.weather,
        direct.weather.dropna(subset=["temperature", "relative_humidity"], how="all").reset_index(
            drop=True
        ),
    )
    assert restored.validation_start == direct.validation_start


def test_weighted_forecast_combines_every_point_and_reports_each_source(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    for name in OFFSETS:
        _observe(runtime, name)
    runtime.cwa_weather.upsert_cwa_forecast_releases([_release_for(*GEOCODES)])

    outcome = predict_task(
        _weighted(task), model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
    )

    assert outcome.mode == "normal"
    assert outcome.weather["temperature"].tolist() == pytest.approx([30.0 + WEIGHTED_OFFSET] * 6)
    assert outcome.weather["relative_humidity"].tolist() == pytest.approx([69.8] * 6)
    first = outcome.weather_sources[0]
    assert set(first["temperature"]) == set(GEOCODES)
    assert {source["source"] for source in first["temperature"].values()} == {"three_day"}


def test_one_stale_reference_point_degrades_the_whole_forecast(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    for name in OFFSETS:
        _observe(runtime, name)
    runtime.cwa_weather.upsert_cwa_forecast_releases([_release_for("Taipei", "Taichung")])

    outcome = predict_task(
        _weighted(task), model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
    )

    assert outcome.mode == "degraded"
    sources = outcome.weather_sources[0]["temperature"]
    assert sources["Taipei"]["source"] == "three_day"
    assert sources["Kaohsiung"]["source"] == "previous_day_observation"
    assert check_task_ready(_weighted(task), model, runtime, as_of=FRESH_AS_OF).mode == "degraded"


def test_reference_point_without_any_fallback_makes_the_forecast_unavailable(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    """No forecast and no observation at Kaohsiung: refuse rather than drop it and reweight."""
    _observe(runtime, "Taichung")
    runtime.cwa_weather.upsert_cwa_forecast_releases([_release_for("Taipei", "Taichung")])

    with pytest.raises(WeatherUnavailableError, match="Kaohsiung"):
        predict_task(
            _weighted(task), model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
        )
    assert not check_task_ready(_weighted(task), model, runtime, as_of=FRESH_AS_OF).ready


def test_first_reference_point_without_coverage_in_order_is_the_one_named(
    task: TaskDefinition, runtime: TaskRuntime, model: TaskModel
) -> None:
    """Taichung and Kaohsiung both lack coverage; the refusal names Taichung, listed first."""
    runtime.cwa_weather.upsert_cwa_forecast_releases([_release_for("Taipei")])

    with pytest.raises(WeatherUnavailableError, match=r"^Taichung: No weather coverage for "):
        predict_task(
            _weighted(task), model, runtime, as_of=FRESH_AS_OF, horizon_hours=HORIZON_HOURS
        )


def test_observed_prediction_weights_every_point_and_reports_each_observation(
    anomaly_task: TaskDefinition, runtime: TaskRuntime, anomaly_model: TaskModel
) -> None:
    for name in OFFSETS:
        _observe(runtime, name)

    outcome = predict_task(
        _weighted(anomaly_task),
        anomaly_model,
        runtime,
        as_of=FRESH_AS_OF,
        horizon_hours=HORIZON_HOURS,
    )

    _, taipei = hourly_load_with_weather(HOURS, LAST_HOUR)
    at_anchor = taipei.set_index("datetime").loc[ANCHOR, "temperature"]
    assert outcome.weather["temperature"].iloc[-1] == pytest.approx(at_anchor + WEIGHTED_OFFSET)
    observation = {"source": "station_observation", "observed_at": ANCHOR.isoformat()}
    assert outcome.weather_sources[-1]["temperature"] == dict.fromkeys(GEOCODES, observation)


def _record_load_reads(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[datetime | None, datetime]]:
    """Record the half-open window ``[start, end)`` of every target series the runner requests."""
    store = runtime.hourly_actual_load
    series = store.series
    reads: list[tuple[datetime | None, datetime]] = []

    def record(**kwargs):
        reads.append((kwargs.get("start"), kwargs["end"]))
        return series(**kwargs)

    monkeypatch.setattr(store, "series", record)
    return reads
