"""Integration tests for Feast Parquet export, offline feature retrieval, and full pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
from dagster import build_asset_context, materialize
from feast import FeatureStore
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.features.definitions import (
    location_entity,
    taipower_load_feature_view,
    weather_feature_view,
)
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.pipelines.assets import (
    drift_monitoring_report,
    engineered_features,
    raw_taipower_load_data,
    raw_weather_obs_data,
    trained_forecaster_model,
)


def test_engineered_features_extracts_db_and_materializes_feast_parquet(
    populated_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
    monkeypatch,
):
    """Verify engineered_features extracts from DB, saves Feast Parquet files, and returns df."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    context = build_asset_context(resources={"time_series_repo": populated_repo})

    features_df = engineered_features(
        context=context,
        raw_taipower_load_data=taipower_raw_df,
        raw_weather_obs_data=cwa_obs_df,
    )

    assert isinstance(features_df, pd.DataFrame)
    assert not features_df.empty

    # Verify Parquet files generated on disk in DATA_DIR
    taipower_parquet = tmp_path / "taipower_features.parquet"
    weather_parquet = tmp_path / "weather_features.parquet"

    assert taipower_parquet.exists(), f"Expected {taipower_parquet} to exist"
    assert weather_parquet.exists(), f"Expected {weather_parquet} to exist"

    # Verify schema of taipower_features.parquet
    tp_df = pd.read_parquet(taipower_parquet)
    assert "datetime" in tp_df.columns
    assert "location" in tp_df.columns
    assert "load_mw" in tp_df.columns
    assert "hour" in tp_df.columns
    assert "is_weekend" in tp_df.columns

    # Verify schema of weather_features.parquet
    w_df = pd.read_parquet(weather_parquet)
    assert "datetime" in w_df.columns
    assert "location" in w_df.columns
    assert "temperature" in w_df.columns
    assert "relative_humidity" in w_df.columns


def test_engineered_features_multi_location_isolation_and_export(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
    monkeypatch,
):
    """Verify engineered_features isolates multiple locations and produces unique composite Feast keys."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    repo = TimeSeriesRepository(engine=sqlite_engine)

    # Upsert Taipei data
    repo.upsert_taipower_load(taipower_raw_df, default_location="Taipei")
    repo.upsert_cwa_weather(cwa_obs_df, default_location="Taipei")

    # Upsert Kaohsiung data with different values
    kh_taipower = taipower_raw_df.copy()
    kh_taipower["load_mw"] = kh_taipower["load_mw"] * 0.6
    kh_taipower["location"] = "Kaohsiung"
    repo.upsert_taipower_load(kh_taipower, default_location="Kaohsiung")

    kh_weather = cwa_obs_df.copy()
    kh_weather["temperature"] = kh_weather["temperature"] + 3.0
    kh_weather["location"] = "Kaohsiung"
    repo.upsert_cwa_weather(kh_weather, default_location="Kaohsiung")

    context = build_asset_context(resources={"time_series_repo": repo})
    features_df = engineered_features(
        context=context,
        raw_taipower_load_data=taipower_raw_df,
        raw_weather_obs_data=cwa_obs_df,
    )

    assert not features_df.empty
    assert set(features_df["location"]) == {"Taipei", "Kaohsiung"}

    # Verify Feast Parquet export has unique (datetime, location) keys
    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert set(tp_df["location"]) == {"Taipei", "Kaohsiung"}
    assert not tp_df.duplicated(subset=["datetime", "location"]).any()

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert set(w_df["location"]) == {"Taipei", "Kaohsiung"}
    assert not w_df.duplicated(subset=["datetime", "location"]).any()


def test_short_dataset_feast_parquet_schema_contract(
    sqlite_engine: Engine,
    tmp_path: Path,
    monkeypatch,
):
    """Verify short data windows (e.g. 5 records) produce complete Feast Parquet schemas with float32/int64 types."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    repo = TimeSeriesRepository(engine=sqlite_engine)

    short_load = pd.DataFrame(
        [
            {
                "datetime": f"2026-08-20 0{i}:00:00",
                "load_mw": 25000.0 + i * 100,
                "location": "Taipei",
            }
            for i in range(5)
        ]
    )
    short_weather = pd.DataFrame(
        [
            {
                "datetime": f"2026-08-20 0{i}:00:00",
                "temperature": 28.0 + i * 0.5,
                "relative_humidity": 80.0 - i,
                "location": "Taipei",
            }
            for i in range(5)
        ]
    )

    repo.upsert_taipower_load(short_load)
    repo.upsert_cwa_weather(short_weather)

    context = build_asset_context(resources={"time_series_repo": repo})
    features_df = engineered_features(
        context=context,
        raw_taipower_load_data=short_load,
        raw_weather_obs_data=short_weather,
    )

    assert not features_df.empty
    assert len(features_df) == 5

    # Check Parquet on disk
    tp_path = tmp_path / "taipower_features.parquet"
    tp_df = pd.read_parquet(tp_path)
    assert len(tp_df) == 5

    # Verify all FeatureView fields are present in the Parquet file
    expected_tp_fields = [
        "load_mw",
        "load_mw_lag_1",
        "load_mw_lag_2",
        "load_mw_lag_24",
        "load_mw_rolling_mean_6",
        "load_mw_rolling_mean_24",
        "hour",
        "dayofweek",
        "is_weekend",
        "hour_sin",
        "hour_cos",
    ]
    for field in expected_tp_fields:
        assert field in tp_df.columns, f"Missing required Feast field: {field}"

    # Verify types
    assert tp_df["load_mw_lag_24"].dtype == "float32"
    assert tp_df["load_mw_rolling_mean_24"].dtype == "float32"
    assert tp_df["hour"].dtype == "int64"

    w_path = tmp_path / "weather_features.parquet"
    w_df = pd.read_parquet(w_path)
    assert len(w_df) == 5
    assert "temperature" in w_df.columns
    assert "relative_humidity" in w_df.columns
    assert w_df["temperature"].dtype == "float32"
    assert w_df["relative_humidity"].dtype == "float32"


def test_feast_offline_feature_retrieval(
    populated_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
):
    """Verify Feast get_historical_features retrieves features and trains forecaster without error."""
    context = build_asset_context(resources={"time_series_repo": populated_repo})

    engineered_features(
        context=context,
        raw_taipower_load_data=taipower_raw_df,
        raw_weather_obs_data=cwa_obs_df,
    )

    store = FeatureStore(repo_path=str(settings.FEAST_REPO_PATH))
    store.apply([location_entity, taipower_load_feature_view, weather_feature_view])

    # Construct entity DataFrame across multiple timestamps
    entity_df = pd.DataFrame(
        {
            "location": ["Taipei", "Taipei"],
            "datetime": [
                pd.Timestamp("2026-08-21 12:00:00"),
                pd.Timestamp("2026-08-21 13:00:00"),
            ],
        }
    )

    all_features = [
        "taipower_load_features:load_mw",
        "taipower_load_features:load_mw_lag_1",
        "taipower_load_features:load_mw_lag_2",
        "taipower_load_features:load_mw_lag_24",
        "taipower_load_features:load_mw_rolling_mean_6",
        "taipower_load_features:load_mw_rolling_mean_24",
        "taipower_load_features:hour",
        "taipower_load_features:dayofweek",
        "taipower_load_features:is_weekend",
        "taipower_load_features:hour_sin",
        "taipower_load_features:hour_cos",
        "cwa_weather_features:temperature",
        "cwa_weather_features:relative_humidity",
    ]

    training_df = store.get_historical_features(
        entity_df=entity_df,
        features=all_features,
    ).to_df()

    assert not training_df.empty
    assert "load_mw" in training_df.columns
    assert "temperature" in training_df.columns
    assert "relative_humidity" in training_df.columns
    assert "load_mw_lag_1" in training_df.columns

    # Verify Feast training DataFrame compatibility with LightGBM forecaster fit
    forecaster = LightGBMRecursiveForecaster(
        params={"n_estimators": 5, "min_child_samples": 1, "verbose": -1}
    )
    forecaster.fit(training_df)
    assert forecaster.model is not None


def test_full_dagster_mlops_pipeline_materialization(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    lightweight_forecaster: LightGBMRecursiveForecaster,
    dagster_instance,
    tmp_path: Path,
    monkeypatch,
):
    """Verify full Dagster pipeline executes end-to-end from ingestion to monitoring offline and fast."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    repo = TimeSeriesRepository(engine=sqlite_engine)

    with (
        patch(
            "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
            return_value=taipower_raw_df,
        ),
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
            return_value=cwa_obs_df,
        ),
        patch("shiro_mlops.pipelines.assets.mlflow") as mock_mlflow,
    ):
        mock_run = MagicMock()
        mock_run.info.run_id = "test_run_123"
        mock_mlflow.start_run.return_value.__enter__.return_value = mock_run

        res = materialize(
            assets=[
                raw_taipower_load_data,
                raw_weather_obs_data,
                engineered_features,
                trained_forecaster_model,
                drift_monitoring_report,
            ],
            resources={
                "time_series_repo": repo,
                "forecaster": lightweight_forecaster,
            },
            instance=dagster_instance,
        )

    assert res.success

    # Verify model trained and saved in DATA_DIR
    model_path = tmp_path / "model.joblib"
    assert model_path.exists()

    # Verify drift report metadata
    report = res.output_for_node("drift_monitoring_report")
    assert "status" in report
    assert report["status"] in {"HEALTHY", "WARNING"}
    assert report["feature_count"] > 0
