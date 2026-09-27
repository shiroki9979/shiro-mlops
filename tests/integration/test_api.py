"""Integration tests for FastAPI endpoints."""

from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from shiro_mlops.core.config import settings
from shiro_mlops.data.weather_resolution import WeatherResolution
from shiro_mlops.service.api import app, model_store
from shiro_mlops.tasks.types.base import TaskModel


def test_api_health_endpoint() -> None:
    """Test /health status endpoint."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "environment" in data


def test_app_startup_skips_timescale_initialization_in_test_environment(monkeypatch) -> None:
    """測試環境啟動 API 時不得連線預設 TimescaleDB。"""
    initialization_calls: list[None] = []
    monkeypatch.setattr(
        "shiro_mlops.core.database.init_db", lambda: initialization_calls.append(None)
    )

    with TestClient(app):
        pass

    assert initialization_calls == []


def test_api_ready_reports_cold_start_without_constructing_a_cwa_client(monkeypatch) -> None:
    """An empty database is live but not ready until ingestion and training complete."""
    model_store.model = None

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_api_ready_reports_normal_or_degraded_weather_mode(monkeypatch) -> None:
    """Readiness exposes a usable full-horizon weather mode from persisted sources."""
    repository = MagicMock()
    latest_load = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-08-20 12:00"),
                "load_mw": 30000.0,
                "subject": "nationwide",
            }
        ]
    )
    repository.fetch_latest_load.return_value = latest_load
    repository.fetch_load_range.return_value = latest_load
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock", lambda: pd.Timestamp("2026-08-20 13:00")
    )
    model_store.model = MagicMock()
    weather = WeatherResolution(
        dataframe=pd.DataFrame(
            {
                "datetime": [pd.Timestamp("2026-08-20 13:00")],
                "temperature": [30.0],
                "relative_humidity": [70.0],
            }
        ),
        sources=({},),
        mode="degraded",
    )
    monkeypatch.setattr("shiro_mlops.tasks.runner.resolve_weather", lambda *args, **kwargs: weather)

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["mode"] == "degraded"


def _serve_fitted_forecaster(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> MagicMock:
    """Attach a fitted model and a repository holding fresh load and forecast rows."""
    model_store.model = fitted_task_model

    repository = MagicMock()
    repository.fetch_latest_load.return_value = taipower_raw_df.tail(1)
    repository.fetch_load_range.return_value = taipower_raw_df
    repository.fetch_cwa_station_observations.return_value = cwa_obs_df.rename(
        columns={
            "datetime": "observed_at",
            "temperature": "temperature_c",
            "relative_humidity": "relative_humidity_pct",
        }
    )
    repository.fetch_cwa_forecast_rows.return_value = cwa_forecast_df.assign(
        dataset_id="F-D0047-089",
        issued_at=pd.Timestamp("2026-08-21 22:00"),
        source_updated_at=pd.Timestamp("2026-08-21 22:10"),
        valid_from=lambda frame: frame["datetime"],
        valid_to=lambda frame: frame["datetime"],
        geocode="63000050",
    ).rename(columns={"temperature": "temperature_c", "relative_humidity": "relative_humidity_pct"})
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock", lambda: pd.Timestamp("2026-08-22 00:00")
    )

    return repository


def test_api_predict_dynamic_horizon(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Test dynamic horizon prediction endpoint."""
    _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    client = TestClient(app)
    response = client.post("/predict", json={"horizon_hours": 12})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["horizon_hours"] == 12
    assert len(data["predictions"]) == 12
    assert data["predictions"][0]["predicted_load_mw"] > 0
    assert data["subject"] == "nationwide"
    assert "location" not in data


def test_api_predict_ignores_legacy_location_and_reads_nationwide_subject(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """舊客戶端傳入的 location 不影響預測對象，負載一律以 nationwide 讀取。"""
    repository = _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    client = TestClient(app)
    response = client.post("/predict", json={"horizon_hours": 6, "location": "Kaohsiung"})

    assert response.status_code == 200
    assert response.json()["subject"] == "nationwide"
    assert repository.fetch_load_range.call_args.kwargs["subject"] == "nationwide"


def test_api_predict_reads_weather_from_the_weather_reference_point(
    fitted_task_model: TaskModel,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """天氣取自擷取目錄中的氣象代表點，而非預測對象。"""
    repository = _serve_fitted_forecaster(
        fitted_task_model, taipower_raw_df, cwa_obs_df, cwa_forecast_df, monkeypatch
    )

    TestClient(app).post("/predict", json={"horizon_hours": 1})

    taipei = settings.cwa_locations["Taipei"]
    assert repository.fetch_cwa_forecast_rows.call_args.kwargs["geocode"] == taipei.geocode
    assert (
        repository.fetch_cwa_station_observations.call_args.kwargs["station_id"]
        == taipei.station_id
    )


def test_openapi_marks_predict_location_as_optional_and_deprecated() -> None:
    schemas = app.openapi()["components"]["schemas"]
    request_schema = schemas["PredictionRequest"]

    assert "location" not in request_schema.get("required", [])
    assert request_schema["properties"]["location"]["deprecated"] is True
    assert "subject" in schemas["PredictionResponse"]["properties"]
    assert "location" not in schemas["PredictionResponse"]["properties"]
