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
    taipower_load_feature_source,
)


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


def test_taipower_load_feature_source_fails_without_derived_load(
    test_repo: TimeSeriesRepository,
) -> None:
    """尚無推算負載時訓練特徵來源必須明確失敗，不得改抓外部來源。"""
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with pytest.raises(RuntimeError, match="No derived hourly actual load"):
        taipower_load_feature_source(context)


def test_dagster_materialize_ingestion_and_feature_pipeline(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    dagster_instance,
):
    """Verify Dagster materialize reads persisted load and weather through feature engineering."""
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
    test_repo.upsert_taipower_load(taipower_raw_df)
    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
        return_value=observation_batch,
    ):
        raw_cwa_station_observation(build_asset_context(resources={"time_series_repo": test_repo}))
    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
        return_value=observation_batch,
    ):
        res = materialize(
            assets=[
                taipower_load_feature_source,
                cwa_observation_feature_source,
                engineered_feature_set,
            ],
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

    persisted_load = test_repo.fetch_load_range(location="Taipei")
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(location="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)
