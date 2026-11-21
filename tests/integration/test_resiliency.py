"""Offline resiliency tests for CWA ingestion failures and degraded or refused serving."""

from datetime import datetime

import httpx
import pandas as pd
import pytest
from dagster import Definitions, RetryPolicy, define_asset_job
from fastapi.testclient import TestClient

from shiro_mlops.data.cwa_client import (
    CWAClient,
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import raw_cwa_station_observation, raw_cwa_township_forecast
from shiro_mlops.pipelines.schedules import (
    CWA_INGESTION_RETRY_POLICY,
    cwa_forecast_job,
    cwa_observation_job,
)
from shiro_mlops.service.api import app, model_store
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.types.base import TaskModel
from tests.helpers import insert_legacy_load_row, override_task_policies, with_complete_lookback

# taipower_sample.json 的最後一筆實際負載即為遞迴預報起點。
LOAD_ANCHOR = pd.Timestamp("2026-08-21 23:00")
FRESH_REQUEST_TIME = pd.Timestamp("2026-08-22 00:30")
STALE_REQUEST_TIME = LOAD_ANCHOR + pd.Timedelta(hours=3, minutes=1)
TAIPEI_STATION_ID = "466920"
TAIPEI_GEOCODE = "63000000"
HORIZON_HOURS = 3
PREVIOUS_DAY_TEMPERATURES = (27.0, 26.5, 26.0)
# 8/14–8/20 七個不同日期、全日 24 小時的觀測，恰好滿足常模的最低日期數且涵蓋 /ready 的 168 小時。
CLIMATOLOGY_TEMPERATURE = 25.0
CLIMATOLOGY_HUMIDITY_BY_DAY = {14: 60.0, 15: 62.0, 16: 64.0, 17: 66.0, 18: 68.0, 19: 70.0, 20: 72.0}
EXPECTED_CLIMATOLOGY_HUMIDITY = 66.0
TOTAL_ATTEMPTS = CWA_INGESTION_RETRY_POLICY.max_retries + 1


def _observation(
    observed_at: pd.Timestamp, temperature: float | None, humidity: float | None
) -> CWAStationObservation:
    return CWAStationObservation(
        observed_at=observed_at,
        station_id=TAIPEI_STATION_ID,
        station_name="臺北",
        town_code="63000050",
        temperature_c=temperature,
        relative_humidity_pct=humidity,
        air_pressure_hpa=None,
        precipitation_mm=None,
        wind_speed_m_s=None,
        wind_direction_deg=None,
    )


def _observation_batch(observations: list[CWAStationObservation]) -> CWAObservationBatch:
    return CWAObservationBatch(
        fetched_at=datetime(2026, 8, 21, 23, 10),
        status="complete",
        missing_station_ids=(),
        raw_payload={"fixture": "resiliency"},
        observations=tuple(observations),
    )


def _degraded_weather_observations() -> CWAObservationBatch:
    """Previous-day rows carry only temperature, so humidity must come from climatology."""
    previous_day = [
        _observation(LOAD_ANCHOR + pd.Timedelta(hours=1 + offset - 24), temperature, None)
        for offset, temperature in enumerate(PREVIOUS_DAY_TEMPERATURES)
    ]
    climatology = [
        _observation(pd.Timestamp(2026, 8, day, hour), CLIMATOLOGY_TEMPERATURE, humidity)
        for day, humidity in CLIMATOLOGY_HUMIDITY_BY_DAY.items()
        for hour in range(24)
    ]
    return _observation_batch([*previous_day, *climatology])


def _forecast_release(issued_at: pd.Timestamp, temperature: float) -> CWAForecastRelease:
    return CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=issued_at,
        source_updated_at=issued_at + pd.Timedelta(minutes=10),
        fetched_at=(issued_at + pd.Timedelta(minutes=20)).to_pydatetime(),
        status="complete",
        missing_geocodes=(),
        raw_payload={"fixture": "resiliency"},
        forecasts=tuple(
            CWATownshipForecast(
                valid_from=LOAD_ANCHOR + pd.Timedelta(hours=hour),
                valid_to=LOAD_ANCHOR + pd.Timedelta(hours=hour),
                geocode=TAIPEI_GEOCODE,
                location_name="臺北市",
                temperature_c=temperature,
                dew_point_c=None,
                apparent_temperature_c=None,
                relative_humidity_pct=80.0,
                probability_of_precipitation_pct=None,
                wind_speed_m_s=None,
                wind_direction=None,
            )
            for hour in range(1, HORIZON_HOURS + 1)
        ),
    )


def _stale_forecast_release() -> CWAForecastRelease:
    """Issued 7.5 hours before the fresh request; its sentinel values must never be served."""
    return _forecast_release(FRESH_REQUEST_TIME - pd.Timedelta(hours=7, minutes=30), 99.0)


@pytest.fixture
def serving_repo(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    fitted_task_model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> TimeSeriesRepository:
    """A loaded model reading persisted nationwide load history, with no weather yet."""
    test_repo.upsert_taipower_load(
        with_complete_lookback(taipower_raw_df), default_subject="nationwide"
    )
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, fitted_task_model)
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", test_repo)
    return test_repo


@pytest.fixture
def degraded_weather_repo(serving_repo: TimeSeriesRepository) -> TimeSeriesRepository:
    serving_repo.upsert_cwa_forecast_release(_stale_forecast_release())
    serving_repo.upsert_cwa_observation_batch(_degraded_weather_observations())
    return serving_repo


def _request_at(monkeypatch: pytest.MonkeyPatch, request_time: pd.Timestamp) -> None:
    monkeypatch.setattr("shiro_mlops.service.api.request_clock", lambda: request_time)


def _predict(horizon_hours: int = HORIZON_HOURS) -> httpx.Response:
    return TestClient(app).post(
        "/predict", json={"horizon_hours": horizon_hours, "location": "Taipei"}
    )


def _ready() -> httpx.Response:
    return TestClient(app).get("/ready")


# --- CWA ingestion: bounded retries never mutate persisted data ---------------------------


def _fail_every_cwa_request(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Route every CWA HTTP call to an HTTP 500 and record the attempted URLs."""
    attempted: list[str] = []
    real_client = httpx.Client

    def respond_500(request: httpx.Request) -> httpx.Response:
        attempted.append(str(request.url.copy_with(params=None)))
        return httpx.Response(500, request=request)

    def client_factory(**kwargs: object) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(respond_500), **kwargs)

    monkeypatch.setattr("shiro_mlops.data.cwa_client.httpx.Client", client_factory)
    return attempted


def _execute_without_retry_delay(job, repo: TimeSeriesRepository, instance):
    """Run the production selection and retry count, skipping only the real backoff sleep."""
    job_without_delay = define_asset_job(
        name=job.name,
        selection=job.selection,
        op_retry_policy=RetryPolicy(max_retries=CWA_INGESTION_RETRY_POLICY.max_retries, delay=0),
    )
    defs = Definitions(
        assets=[raw_cwa_station_observation, raw_cwa_township_forecast],
        jobs=[job_without_delay],
        resources={"time_series_repo": repo},
    )
    return defs.resolve_job_def(job.name).execute_in_process(
        instance=instance, raise_on_error=False
    )


def _persisted_cwa_state(repo: TimeSeriesRepository) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        repo.fetch_cwa_station_observations(station_id=TAIPEI_STATION_ID),
        repo.fetch_cwa_forecast_rows(geocode=TAIPEI_GEOCODE),
    )


@pytest.mark.parametrize("job", [cwa_observation_job, cwa_forecast_job], ids=lambda job: job.name)
def test_cwa_http_500_exhausts_retries_fails_run_and_keeps_existing_data(
    job,
    test_repo: TimeSeriesRepository,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_repo.upsert_cwa_observation_batch(cwa_observation_batch)
    test_repo.upsert_cwa_forecast_release(_stale_forecast_release())
    observations_before, forecasts_before = _persisted_cwa_state(test_repo)
    attempted = _fail_every_cwa_request(monkeypatch)

    result = _execute_without_retry_delay(job, test_repo, dagster_instance)

    assert not result.success
    assert len(attempted) == TOTAL_ATTEMPTS
    observations_after, forecasts_after = _persisted_cwa_state(test_repo)
    pd.testing.assert_frame_equal(observations_after, observations_before)
    pd.testing.assert_frame_equal(forecasts_after, forecasts_before)


def test_second_cwa_product_failure_keeps_forecast_versions_unchanged(
    test_repo: TimeSeriesRepository,
    dagster_instance,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_repo.upsert_cwa_forecast_release(_stale_forecast_release())
    before = test_repo.fetch_cwa_forecast_rows(geocode=TAIPEI_GEOCODE)
    new_release = _forecast_release(FRESH_REQUEST_TIME, 32.0)

    def fetch_release(self, dataset_id: str, locations: object) -> CWAForecastRelease:
        if dataset_id == "F-D0047-089":
            return new_release
        request = httpx.Request("GET", "https://opendata.cwa.gov.tw/failed-product")
        raise httpx.HTTPStatusError(
            "CWA returned HTTP 500",
            request=request,
            response=httpx.Response(500, request=request),
        )

    monkeypatch.setattr(CWAClient, "fetch_forecast_release", fetch_release)

    result = _execute_without_retry_delay(cwa_forecast_job, test_repo, dagster_instance)

    assert not result.success
    pd.testing.assert_frame_equal(test_repo.fetch_cwa_forecast_rows(geocode=TAIPEI_GEOCODE), before)


# --- Serving: degraded weather keeps the service up ------------------------------------------


def test_stale_forecast_degrades_predict_with_per_field_fallback_sources(
    degraded_weather_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _request_at(monkeypatch, FRESH_REQUEST_TIME)

    response = _predict()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["mode"] == "degraded"
    assert [item["temperature"] for item in body["predictions"]] == list(PREVIOUS_DAY_TEMPERATURES)
    for item in body["predictions"]:
        assert item["relative_humidity"] == pytest.approx(EXPECTED_CLIMATOLOGY_HUMIDITY)
        assert item["weather_sources"] == {
            "temperature": {"Taipei": {"source": "previous_day_observation"}},
            "relative_humidity": {"Taipei": {"source": "climatology"}},
        }


def test_fresh_forecast_keeps_predict_in_normal_mode(
    serving_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Separates request success from forecast quality: the same success status, normal mode."""
    serving_repo.upsert_cwa_forecast_release(
        _forecast_release(FRESH_REQUEST_TIME - pd.Timedelta(hours=1), 30.0)
    )
    _request_at(monkeypatch, FRESH_REQUEST_TIME)

    response = _predict()

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["mode"] == "normal"


def test_missing_forecast_and_fallback_weather_returns_503(
    serving_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _request_at(monkeypatch, FRESH_REQUEST_TIME)

    predict_response = _predict()
    ready_response = _ready()

    assert predict_response.status_code == 503
    assert "No weather coverage" in predict_response.json()["detail"]
    assert ready_response.status_code == 503
    assert ready_response.json()["status"] == "not_ready"


# --- Serving: a stale load anchor refuses rather than degrades ------------------------------


def test_stale_load_anchor_refuses_predict_and_ready(
    degraded_weather_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    _request_at(monkeypatch, STALE_REQUEST_TIME)

    predict_response = _predict()
    ready_response = _ready()

    assert predict_response.status_code == 503
    assert "stale load anchor" in predict_response.json()["detail"].lower()
    assert ready_response.status_code == 503
    ready_body = ready_response.json()
    assert ready_body["status"] == "not_ready"
    assert ready_body["mode"] is None
    assert "stale load anchor" in ready_body["reason"].lower()


def test_newer_legacy_rows_never_anchor_serving(
    legacy_upgraded_engine,
    taipower_raw_df: pd.DataFrame,
    fitted_task_model: TaskModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Under ADR-0008, newer legacy rows cannot mask a stale derived-load anchor."""
    repository = TimeSeriesRepository(engine=legacy_upgraded_engine, auto_init=False)
    repository.upsert_taipower_load(taipower_raw_df, default_subject="nationwide")
    insert_legacy_load_row(
        legacy_upgraded_engine, STALE_REQUEST_TIME.floor("h").to_pydatetime(), load_mw=26500.0
    )
    monkeypatch.setitem(model_store.models, DYNAMIC_HORIZON_FORECAST, fitted_task_model)
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    _request_at(monkeypatch, STALE_REQUEST_TIME)

    predict_response = _predict()
    ready_response = _ready()

    assert predict_response.status_code == 503
    detail = predict_response.json()["detail"]
    assert f"Stale load anchor: latest actual load at {LOAD_ANCHOR.isoformat()}" in detail
    assert ready_response.status_code == 503
    assert "stale load anchor" in ready_response.json()["reason"].lower()


def test_load_anchor_lag_threshold_is_configurable(
    degraded_weather_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_task_policies(monkeypatch, stale_anchor_max_lag_hours=6)
    _request_at(monkeypatch, STALE_REQUEST_TIME)

    assert _predict().status_code == 200
    assert _ready().status_code == 200


def test_load_anchor_lag_threshold_defaults_to_three_hours() -> None:
    task = deployed_task(DYNAMIC_HORIZON_FORECAST)

    assert task.policies.stale_anchor_max_lag_hours == 3


# --- Serving never crosses the CWA ingestion boundary ---------------------------------------


def test_serving_path_never_constructs_a_cwa_client(
    degraded_weather_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse_construction(*_: object, **__: object) -> None:
        raise AssertionError("Serving must read canonical tables instead of calling CWA")

    monkeypatch.setattr(CWAClient, "__init__", refuse_construction)
    _request_at(monkeypatch, FRESH_REQUEST_TIME)

    assert _predict().status_code == 200
    assert _ready().status_code == 200
