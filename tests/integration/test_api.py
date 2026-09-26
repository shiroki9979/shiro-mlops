"""Integration tests for FastAPI endpoints."""

from unittest.mock import MagicMock

import pandas as pd
from fastapi.testclient import TestClient

from shiro_mlops.data.weather_resolution import WeatherResolution
from shiro_mlops.features.transformers import build_feature_pipeline
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.service.api import app, model_store


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
    model_store.forecaster = None

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_api_ready_reports_normal_or_degraded_weather_mode(monkeypatch) -> None:
    """Readiness exposes a usable full-horizon weather mode from persisted sources."""
    repository = MagicMock()
    repository.fetch_load_range.return_value = pd.DataFrame(
        [{"datetime": pd.Timestamp("2026-08-20 12:00"), "load_mw": 30000.0, "location": "Taipei"}]
    )
    monkeypatch.setattr("shiro_mlops.service.api.repository_store", repository)
    monkeypatch.setattr(
        "shiro_mlops.service.api.request_clock", lambda: pd.Timestamp("2026-08-20 13:00")
    )
    model_store.forecaster = MagicMock()
    weather = WeatherResolution(
        dataframe=pd.DataFrame({"datetime": [pd.Timestamp("2026-08-20 13:00")]}),
        sources=({},),
        mode="degraded",
    )
    monkeypatch.setattr(
        "shiro_mlops.service.api._resolve_prediction_weather", lambda *args: weather
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["mode"] == "degraded"


def test_api_predict_dynamic_horizon(
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    monkeypatch,
) -> None:
    """Test dynamic horizon prediction endpoint."""
    # 1. Prepare and attach a fitted forecaster to model_store
    feat_df = build_feature_pipeline(
        load_df=taipower_raw_df,
        weather_df=cwa_obs_df,
        lags=[1, 2, 24],
        windows=[6],
    )
    forecaster = LightGBMRecursiveForecaster(
        lags=[1, 2, 24],
        windows=[6],
        params={"n_estimators": 5, "verbose": -1},
    )
    forecaster.fit(feat_df)
    model_store.forecaster = forecaster

    repository = MagicMock()
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

    client = TestClient(app)
    payload = {"horizon_hours": 12, "location": "Taipei"}
    response = client.post("/predict", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["horizon_hours"] == 12
    assert len(data["predictions"]) == 12
    assert data["predictions"][0]["predicted_load_mw"] > 0
