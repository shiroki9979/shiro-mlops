"""Integration tests for Dagster ingestion assets and database persistence."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pandas as pd
import pytest
from dagster import build_asset_context, materialize

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import get_feast_parquet_io_manager
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import (
    engineered_feature_set,
    raw_taipower_load_data,
    raw_weather_obs_data,
)


def test_raw_taipower_load_data_persists_to_db(
    test_repo: TimeSeriesRepository, taipower_raw_df: pd.DataFrame
):
    """Verify raw_taipower_load_data fetches from client, upserts to repository, and returns df."""
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        result_df = raw_taipower_load_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(taipower_raw_df)

    # Verify rows were persisted into the repository's SQLite database
    persisted = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted) == len(taipower_raw_df)
    assert persisted.iloc[0]["load_mw"] == pytest.approx(taipower_raw_df.iloc[0]["load_mw"])


def test_raw_weather_obs_data_persists_to_db(
    test_repo: TimeSeriesRepository, cwa_obs_df: pd.DataFrame
):
    """Verify raw_weather_obs_data fetches from client, upserts to repository, and returns df."""
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
        return_value=cwa_obs_df,
    ):
        result_df = raw_weather_obs_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(cwa_obs_df)

    # Verify rows were persisted into the repository's SQLite database
    persisted = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted) == len(cwa_obs_df)
    assert persisted.iloc[0]["temperature"] == pytest.approx(cwa_obs_df.iloc[0]["temperature"])


def test_raw_taipower_load_data_graceful_fallback_on_db_failure(
    taipower_raw_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_taipower_load_data continues safely and returns df if database raises exception in test env."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_taipower_load.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        result_df = raw_taipower_load_data(context)

    # Pipeline does not throw in test mode; still returns DataFrame
    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(taipower_raw_df)


def test_raw_weather_obs_data_graceful_fallback_on_db_failure(
    cwa_obs_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_weather_obs_data continues safely and returns df if database raises exception in test env."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "test")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_cwa_weather.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
        return_value=cwa_obs_df,
    ):
        result_df = raw_weather_obs_data(context)

    assert isinstance(result_df, pd.DataFrame)
    assert len(result_df) == len(cwa_obs_df)


def test_raw_taipower_load_data_raises_in_production(
    taipower_raw_df: pd.DataFrame,
    monkeypatch,
):
    """Verify raw_taipower_load_data raises exception if database fails in non-test environment."""
    monkeypatch.setattr(settings, "ENVIRONMENT", "local")
    failing_repo = MagicMock(spec=TimeSeriesRepository)
    failing_repo.upsert_taipower_load.side_effect = RuntimeError("Database connection timed out")
    context = build_asset_context(resources={"time_series_repo": failing_repo})

    with patch(
        "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
        return_value=taipower_raw_df,
    ):
        with pytest.raises(RuntimeError, match="Database connection timed out"):
            raw_taipower_load_data(context)


def test_dagster_materialize_ingestion_and_feature_pipeline(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    dagster_instance,
):
    """Verify Dagster materialize executes ingestion through feature engineering and persists to repository."""
    with (
        patch(
            "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
            return_value=taipower_raw_df,
        ),
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observations",
            return_value=cwa_obs_df,
        ),
    ):
        res = materialize(
            assets=[raw_taipower_load_data, raw_weather_obs_data, engineered_feature_set],
            resources={
                "time_series_repo": test_repo,
                "feast_io_manager": get_feast_parquet_io_manager(
                    offline_store_type="file",
                    s3_bucket=settings.S3_BUCKET_NAME,
                    s3_prefix=settings.FEAST_S3_PREFIX,
                    data_dir=settings.DATA_DIR,
                ),
            },
            instance=dagster_instance,
        )

    assert res.success
    engineered_df = res.output_for_node("engineered_feature_set", "engineered_features")
    assert isinstance(engineered_df, pd.DataFrame)
    assert not engineered_df.empty

    # Assert persistence to repository during materialization
    persisted_load = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)


def test_ingestion_pipeline_with_real_api_fixtures_persists_to_db(
    test_repo: TimeSeriesRepository,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify full ingestion pipeline: Real API fixtures -> Client standardization -> TimescaleDB upsert -> Returned DataFrame."""
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    with open(fixtures_dir / "taipower_sample.csv", encoding="utf-8") as f:
        taipower_csv_text = f.read()

    with open(fixtures_dir / "cwa_obs_nested_sample.json", encoding="utf-8") as f:
        cwa_nested_json_text = f.read()

    class MockTaipowerResponse:
        status_code = 200
        text = taipower_csv_text

        def raise_for_status(self) -> None:
            pass

    class MockCWAResponse:
        status_code = 200
        text = cwa_nested_json_text

        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, *args, **kwargs: (
            MockCWAResponse() if "cwa.gov.tw" in str(url) else MockTaipowerResponse()
        ),
    )

    context = build_asset_context(resources={"time_series_repo": test_repo})

    # Execute Taipower ingestion asset
    tp_df = raw_taipower_load_data(context)
    assert isinstance(tp_df, pd.DataFrame)
    assert len(tp_df) == 24
    assert "datetime" in tp_df.columns
    assert "load_mw" in tp_df.columns

    # Verify Taipower data persisted into TimescaleDB
    persisted_load = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted_load) == 24
    assert persisted_load.iloc[0]["load_mw"] == pytest.approx(26500.0)

    # Execute CWA ingestion asset
    cwa_df = raw_weather_obs_data(context)
    assert isinstance(cwa_df, pd.DataFrame)
    assert len(cwa_df) == 2
    assert "location" in cwa_df.columns
    assert "temperature" in cwa_df.columns
    assert "relative_humidity" in cwa_df.columns

    # Verify CWA data persisted into TimescaleDB for both Taipei and Kaohsiung
    persisted_taipei = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted_taipei) == 1
    assert persisted_taipei.iloc[0]["temperature"] == pytest.approx(35.7)
    assert persisted_taipei.iloc[0]["relative_humidity"] == pytest.approx(57.0)

    persisted_kaohsiung = test_repo.fetch_weather_range(location="Kaohsiung")
    assert len(persisted_kaohsiung) == 1
    assert persisted_kaohsiung.iloc[0]["temperature"] == pytest.approx(33.2)
    assert persisted_kaohsiung.iloc[0]["relative_humidity"] == pytest.approx(68.0)
