"""Unit tests for LightGBM Recursive Forecaster."""

from pathlib import Path

import pandas as pd

from shiro_mlops.features.transformers import build_feature_pipeline
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster


def test_forecaster_fit_and_predict(
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    cwa_forecast_df: pd.DataFrame,
    tmp_path: Path,
) -> None:
    """Test fitting, saving, loading, and recursive multi-step forecasting."""
    lags = [1, 2, 24]
    windows = [6]

    train_features_df = build_feature_pipeline(
        load_df=taipower_raw_df,
        weather_df=cwa_obs_df,
        lags=lags,
        windows=windows,
        drop_na=True,
    )

    forecaster = LightGBMRecursiveForecaster(
        lags=lags,
        windows=windows,
        params={
            "objective": "regression",
            "metric": "rmse",
            "n_estimators": 10,
            "learning_rate": 0.1,
            "verbose": -1,
        },
    )

    forecaster.fit(train_features_df)
    assert forecaster.model is not None
    assert len(forecaster.feature_names) > 0

    # Save and reload
    save_path = tmp_path / "model.joblib"
    forecaster.save(save_path)
    loaded_forecaster = LightGBMRecursiveForecaster.load(save_path)

    # Test recursive multi-step forecasting for 12 hours
    horizon_hours = 12
    predictions_df = loaded_forecaster.predict_recursive(
        history_df=taipower_raw_df,
        future_weather_df=cwa_forecast_df,
        horizon_hours=horizon_hours,
    )

    assert len(predictions_df) == horizon_hours
    assert "predicted_load_mw" in predictions_df.columns
    assert "temperature" in predictions_df.columns
    assert "relative_humidity" in predictions_df.columns
    assert (predictions_df["predicted_load_mw"] > 0).all()
