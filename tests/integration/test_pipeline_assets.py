"""Integration tests for Dagster ingestion assets and database persistence."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import Definitions, Failure, build_asset_context, materialize

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import (
    FeastPublicationTarget,
    get_feast_parquet_io_manager,
    get_parquet_io_manager,
)
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
from shiro_mlops.pipelines.definitions import all_assets
from shiro_mlops.pipelines.schedules import daily_training_job, hourly_drift_job
from tests.helpers import derived_hourly_load

LAST_LOAD_HOUR = datetime(2026, 9, 26, 13, 0)


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
    with build_asset_context(resources={"time_series_repo": repository}) as context:
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
    with build_asset_context(resources={"time_series_repo": repository}) as context:
        result = raw_cwa_township_forecast(context)

    assert result == releases
    repository.upsert_cwa_forecast_releases.assert_called_once_with(releases)


def test_taipower_load_feature_source_fails_without_derived_load(
    test_repo: TimeSeriesRepository,
) -> None:
    """尚無推算負載時訓練特徵來源必須明確失敗，不得改抓外部來源。"""
    with (
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
        pytest.raises(Failure, match="0 valid hourly observations"),
    ):
        taipower_load_feature_source(context)


def test_taipower_load_feature_source_refuses_training_below_minimum_accumulation(
    test_repo: TimeSeriesRepository,
) -> None:
    """預設 TRAINING_MIN_LOAD_HOURS=672：差一小時也不得進入訓練，並揭露差距。"""
    test_repo.upsert_taipower_load(derived_hourly_load(671, LAST_LOAD_HOUR))
    with (
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
        pytest.raises(Failure, match="671 valid hourly observations; 672 required") as error,
    ):
        taipower_load_feature_source(context)

    assert error.value.metadata["valid_hours"].value == 671
    assert error.value.metadata["required_hours"].value == 672


def test_taipower_load_feature_source_returns_load_once_minimum_accumulation_is_met(
    test_repo: TimeSeriesRepository,
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(672, LAST_LOAD_HOUR))
    with build_asset_context(resources={"time_series_repo": test_repo}) as context:
        load = taipower_load_feature_source(context)

    assert len(load) == 672
    assert load["datetime"].max() == pd.Timestamp(LAST_LOAD_HOUR)


def test_training_load_source_excludes_other_provenance(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "TRAINING_MIN_LOAD_HOURS", 2)
    test_repo.upsert_taipower_load(derived_hourly_load(2, LAST_LOAD_HOUR))
    test_repo.upsert_taipower_load(
        pd.DataFrame([{"datetime": "2026-09-26 11:00", "load_mw": 99999.0}]),
        source="other_source",
    )

    with build_asset_context(resources={"time_series_repo": test_repo}) as context:
        load = taipower_load_feature_source(context)

    assert len(load) == 2
    assert 99999.0 not in load["load_mw"].tolist()


def test_dagster_materialize_ingestion_and_feature_pipeline(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    dagster_instance,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify Dagster materialize reads persisted load and weather through feature engineering."""
    # fixture 只有 48 小時；降低門檻以驗證特徵鏈路，門檻本身由上方測試涵蓋。
    monkeypatch.setattr(settings, "TRAINING_MIN_LOAD_HOURS", len(taipower_raw_df))
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
    with (
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
            return_value=observation_batch,
        ),
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
    ):
        raw_cwa_station_observation(context)
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

    persisted_load = test_repo.fetch_load_range(subject="nationwide")
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(reference_point="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)


def test_training_then_hourly_drift_jobs_read_latest_persisted_actual_load(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """drift 以最新入庫的逐時實際負載對照前次訓練產物，且不執行任何擷取資產。"""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(settings, "TRAINING_MIN_LOAD_HOURS", len(taipower_raw_df))
    test_repo.upsert_taipower_load(taipower_raw_df)
    test_repo.upsert_cwa_observation_batch(cwa_observation_batch)
    job_defs = Definitions(
        assets=all_assets,
        jobs=[daily_training_job, hourly_drift_job],
        resources={
            "time_series_repo": test_repo,
            "io_manager": get_parquet_io_manager("local", "unused", tmp_path),
            "feast_io_manager": get_feast_parquet_io_manager(
                FeastPublicationTarget.local(tmp_path)
            ),
        },
    )

    with patch("shiro_mlops.pipelines.assets.mlflow") as mock_mlflow:
        mock_mlflow.start_run.return_value.__enter__.return_value.info.run_id = "run-1"
        training = job_defs.resolve_job_def("daily_training_job").execute_in_process(
            instance=dagster_instance
        )
    next_hour = taipower_raw_df["datetime"].max() + pd.Timedelta(hours=1)
    test_repo.upsert_taipower_load(derived_hourly_load(1, next_hour.to_pydatetime()))

    def refuse_full_history(*_: object, **__: object) -> None:
        raise AssertionError("Hourly drift must not read the full load history")

    monkeypatch.setattr(test_repo, "fetch_load_range", refuse_full_history)
    drift = job_defs.resolve_job_def("hourly_drift_job").execute_in_process(
        instance=dagster_instance
    )

    assert training.success
    assert drift.success
    report = drift.output_for_node("drift_monitoring_report")
    assert report["latest_actual_load_time"] == next_hour.isoformat()
    assert report["actual_load_hours"] == len(taipower_raw_df) + 1
