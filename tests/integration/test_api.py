"""Integration tests for FastAPI endpoints."""

import pandas as pd
from fastapi.testclient import TestClient

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

    # 2. Mock external client calls in api.py
    monkeypatch.setattr(
        "shiro_mlops.data.taipower_client.TaipowerClient.fetch_load_data",
        lambda self: taipower_raw_df,
    )
    monkeypatch.setattr(
        "shiro_mlops.data.cwa_client.CWAClient.fetch_forecast",
        lambda self, location, horizon_hours: cwa_forecast_df.head(horizon_hours),
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
