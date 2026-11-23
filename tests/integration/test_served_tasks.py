"""The API process's deployed tasks: model state, readiness and prediction through one module."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy.exc import OperationalError

from shiro_mlops.core.constants import MAX_HORIZON_HOURS
from shiro_mlops.data.cwa_client import CWAForecastRelease, CWATownshipForecast
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.served_tasks import (
    Loaded,
    ServedTasks,
    ServingFailedError,
    ServingUnavailableError,
)
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, UnknownTaskError, deployed_task
from shiro_mlops.tasks.model_store import model_directory, save_model
from shiro_mlops.tasks.runner import TaskRuntime
from shiro_mlops.tasks.types.base import TaskModel
from tests.helpers import (
    canonical_observation_batch,
    hourly_load_with_weather,
    task_runtime,
    write_derived_load,
)

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
FRESH_AS_OF = pd.Timestamp(LAST_HOUR) + pd.Timedelta(minutes=30)
UNTRAINED_REASON = "Model is not loaded or trained yet."


@pytest.fixture
def serving_repo(test_repo: TimeSeriesRepository) -> TimeSeriesRepository:
    """Three weeks of fresh nationwide load and Taipei observations, without forecasts."""
    load, weather = hourly_load_with_weather(24 * 21, LAST_HOUR)
    write_derived_load(test_repo.engine, load)
    test_repo.cwa_weather_store.upsert_cwa_observation_batch(
        canonical_observation_batch(weather.assign(location="Taipei"))
    )
    return test_repo


def _load(root: Path, repository: TimeSeriesRepository) -> ServedTasks:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    return ServedTasks.load(
        {task.task_id: task}, root, runtime=task_runtime(repository), clock=lambda: FRESH_AS_OF
    )


def _serving(
    model: TaskModel, runtime: TaskRuntime, as_of: pd.Timestamp = FRESH_AS_OF
) -> ServedTasks:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    return ServedTasks(
        {task.task_id: task},
        {task.task_id: Loaded(model, "a" * 64)},
        runtime=runtime,
        clock=lambda: as_of,
    )


def test_a_loaded_model_is_ready_and_predicts_the_requested_horizon(
    serving_repo: TimeSeriesRepository, fitted_task_model: TaskModel
) -> None:
    """Without forecasts, previous-day observations keep the task serving in degraded mode."""
    served = _serving(fitted_task_model, task_runtime(serving_repo))

    readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
    outcome = served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert (readiness.ready, readiness.model_loaded, readiness.mode) == (True, True, "degraded")
    assert outcome.mode == "degraded"
    assert outcome.predictions["datetime"].tolist() == list(
        pd.date_range(LAST_HOUR + pd.Timedelta(hours=1), periods=3, freq="h")
    )


def test_an_untrained_task_is_not_ready_and_refuses_to_predict(
    tmp_path: Path, serving_repo: TimeSeriesRepository
) -> None:
    served = _load(tmp_path, serving_repo)

    readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
    with pytest.raises(ServingUnavailableError, match=UNTRAINED_REASON):
        served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert not readiness.ready
    assert not readiness.model_loaded
    assert readiness.reason == UNTRAINED_REASON
    status = served.model_status()[DYNAMIC_HORIZON_FORECAST]
    assert (status.model_loaded, status.model_sha256, status.reason) == (
        False,
        None,
        UNTRAINED_REASON,
    )


def test_a_model_that_fails_to_load_leaves_only_its_own_task_unserved(
    tmp_path: Path, serving_repo: TimeSeriesRepository, fitted_task_model: TaskModel
) -> None:
    """A load failure must not pass for "not trained yet" (#204) nor stop other tasks loading."""
    broken = deployed_task(DYNAMIC_HORIZON_FORECAST)
    other = replace(broken, task_id="other_forecast")
    saved = save_model(tmp_path, other.task_id, fitted_task_model)
    hand_copied = model_directory(tmp_path, broken.task_id)
    hand_copied.mkdir(parents=True)
    (hand_copied / "metadata.json").write_text("{}", encoding="utf-8")

    served = ServedTasks.load(
        {broken.task_id: broken, other.task_id: other},
        tmp_path,
        runtime=task_runtime(serving_repo),
        clock=lambda: FRESH_AS_OF,
    )

    failed = "Model failed to load: MissingModelLockError: "
    status = served.model_status()
    assert not status[broken.task_id].model_loaded
    assert status[broken.task_id].reason.startswith(failed)
    assert served.readiness(broken.task_id).reason == status[broken.task_id].reason
    with pytest.raises(ServingUnavailableError, match=f"^{failed}"):
        served.predict(broken.task_id, horizon_hours=3)
    assert (status[other.task_id].model_loaded, status[other.task_id].reason) == (True, None)
    assert status[other.task_id].model_sha256 == saved.sha256


def _fresh_forecast_release() -> CWAForecastRelease:
    """A Taipei release issued an hour before the anchor, covering the whole horizon."""
    anchor = pd.Timestamp(LAST_HOUR)
    issued_at = anchor - pd.Timedelta(hours=1)
    return CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=issued_at,
        source_updated_at=issued_at,
        fetched_at=issued_at.to_pydatetime(),
        status="complete",
        missing_geocodes=(),
        raw_payload={"fixture": "served_tasks"},
        forecasts=tuple(
            CWATownshipForecast(
                valid_from=anchor + pd.Timedelta(hours=hour),
                valid_to=anchor + pd.Timedelta(hours=hour),
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
            for hour in range(1, MAX_HORIZON_HOURS + 1)
        ),
    )


def test_a_fresh_forecast_keeps_the_task_ready_and_predicting_in_normal_mode(
    serving_repo: TimeSeriesRepository, fitted_task_model: TaskModel
) -> None:
    serving_repo.cwa_weather_store.upsert_cwa_forecast_releases([_fresh_forecast_release()])
    served = _serving(fitted_task_model, task_runtime(serving_repo))

    readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
    outcome = served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert (readiness.ready, readiness.mode) == (True, "normal")
    assert outcome.mode == "normal"
    assert outcome.weather["temperature"].tolist() == [30.0] * 3


def test_a_stale_load_anchor_makes_the_task_unavailable(
    serving_repo: TimeSeriesRepository, fitted_task_model: TaskModel
) -> None:
    served = _serving(
        fitted_task_model,
        task_runtime(serving_repo),
        as_of=pd.Timestamp(LAST_HOUR) + pd.Timedelta(hours=4),
    )

    readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
    with pytest.raises(ServingUnavailableError, match="^Stale load anchor"):
        served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert (readiness.ready, readiness.model_loaded) == (False, True)
    assert readiness.reason.startswith("Stale load anchor")


def _broken_runtime(error: Exception) -> TaskRuntime:
    """Every hourly actual load read raises ``error``; weather is never reached."""
    hourly_actual_load = MagicMock(spec=HourlyActualLoadStore)
    hourly_actual_load.latest_observation.side_effect = error
    return TaskRuntime(
        hourly_actual_load=hourly_actual_load, cwa_weather=MagicMock(spec=CWAWeatherStore)
    )


def test_unreachable_persistence_makes_the_task_unavailable(fitted_task_model: TaskModel) -> None:
    error = OperationalError("SELECT 1", {}, Exception("connection refused"))
    served = _serving(fitted_task_model, _broken_runtime(error))

    readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
    with pytest.raises(
        ServingUnavailableError, match="^Persistence unavailable: .*connection refused"
    ):
        served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert (readiness.ready, readiness.model_loaded) == (False, True)
    assert "connection refused" in readiness.reason


def test_unexpected_errors_fail_with_their_traceback_logged(
    fitted_task_model: TaskModel, caplog: pytest.LogCaptureFixture
) -> None:
    """Readiness reports an unexpected error as not ready; prediction fails with it."""
    served = _serving(fitted_task_model, _broken_runtime(RuntimeError("feature column mismatch")))

    with caplog.at_level("ERROR"):
        readiness = served.readiness(DYNAMIC_HORIZON_FORECAST)
        with pytest.raises(ServingFailedError, match="^Prediction error: feature column mismatch$"):
            served.predict(DYNAMIC_HORIZON_FORECAST, horizon_hours=3)

    assert (readiness.ready, readiness.reason) == (False, "feature column mismatch")
    logged = [record for record in caplog.records if record.exc_info]
    assert len(logged) == 2
    assert all(DYNAMIC_HORIZON_FORECAST in record.getMessage() for record in logged)


def test_an_unknown_task_is_not_mistaken_for_an_untrained_one(
    tmp_path: Path, test_repo: TimeSeriesRepository
) -> None:
    served = _load(tmp_path, test_repo)

    assert served.task(DYNAMIC_HORIZON_FORECAST).task_id == DYNAMIC_HORIZON_FORECAST
    for call in (
        lambda: served.task("no_such_task"),
        lambda: served.readiness("no_such_task"),
        lambda: served.predict("no_such_task", horizon_hours=1),
    ):
        with pytest.raises(UnknownTaskError, match="no_such_task"):
            call()
