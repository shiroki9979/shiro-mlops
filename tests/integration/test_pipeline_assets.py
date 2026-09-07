"""Integration tests for Dagster ingestion assets and database persistence."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import build_asset_context, materialize

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import FeastPublicationTarget, get_feast_parquet_io_manager
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import (
    cwa_observation_feature_source,
    engineered_feature_set,
    raw_cwa_station_observation,
    raw_cwa_township_forecast,
    raw_taipower_load_data,
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


def test_canonical_cwa_observation_asset_persists_batch_and_returns_complete(
    monkeypatch: pytest.MonkeyPatch,
):
    batch = MagicMock(spec=CWAObservationBatch)
    batch.status = "complete"
    batch.missing_station_ids = ()
    monkeypatch.setattr(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
        lambda *args, **kwargs: batch,
    )
    repository = MagicMock(spec=TimeSeriesRepository)
    context = build_asset_context(resources={"time_series_repo": repository})

    result = raw_cwa_station_observation(context)

    assert result is batch
    repository.upsert_cwa_observation_batch.assert_called_once_with(batch)


def test_canonical_cwa_forecast_asset_persists_both_products(
    monkeypatch: pytest.MonkeyPatch,
):
    releases = [
        MagicMock(spec=CWAForecastRelease, status="complete"),
        MagicMock(spec=CWAForecastRelease, status="complete"),
    ]
    monkeypatch.setattr(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_forecast_release",
        lambda self, dataset_id, locations: releases[0 if dataset_id.endswith("089") else 1],
    )
    repository = MagicMock(spec=TimeSeriesRepository)
    context = build_asset_context(resources={"time_series_repo": repository})

    result = raw_cwa_township_forecast(context)

    assert result == releases
    assert repository.upsert_cwa_forecast_release.call_count == 2


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
    observation_batch = CWAObservationBatch(
        fetched_at=cwa_obs_df["datetime"].max().to_pydatetime(),
        status="complete",
        observations=tuple(
            CWAStationObservation(
                observed_at=row.datetime.to_pydatetime(),
                station_id="466920",
                station_name="Taipei",
                town_code="63000050",
                temperature_c=float(row.temperature),
                relative_humidity_pct=float(row.relative_humidity),
                air_pressure_hpa=None,
                precipitation_mm=None,
                wind_speed_m_s=None,
                wind_direction_deg=None,
            )
            for row in cwa_obs_df.itertuples()
        ),
        missing_station_ids=(),
        raw_payload={},
    )
    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
        return_value=observation_batch,
    ):
        raw_cwa_station_observation(build_asset_context(resources={"time_series_repo": test_repo}))
    with (
        patch(
            "shiro_mlops.pipelines.assets.TaipowerClient.fetch_load_data",
            return_value=taipower_raw_df,
        ),
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
            return_value=observation_batch,
        ),
    ):
        res = materialize(
            assets=[raw_taipower_load_data, cwa_observation_feature_source, engineered_feature_set],
            resources={
                "time_series_repo": test_repo,
                "feast_io_manager": get_feast_parquet_io_manager(
                    FeastPublicationTarget.from_settings(settings)
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
