"""Integration tests for Dagster ingestion assets and database persistence."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import AssetKey, Definitions, Failure, build_asset_context, materialize

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
    feast_feature_export,
    raw_cwa_station_observation,
    raw_cwa_township_forecast,
)
from shiro_mlops.pipelines.definitions import all_assets
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames
from shiro_mlops.pipelines.tracking import TrackedRun
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST
from tests.helpers import derived_hourly_load, override_task_policies, task_jobs

LAST_LOAD_HOUR = datetime(2026, 9, 26, 13, 0)
NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)
FEATURES_ASSET = next(asset for asset in all_assets if AssetKey(NAMES.features) in asset.keys)


def _features(repository: TimeSeriesRepository) -> pd.DataFrame:
    """Invoke the task's features asset the way a training run does."""
    with build_asset_context(resources={"time_series_repo": repository}) as context:
        return FEATURES_ASSET(context).value


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


def test_task_features_fail_without_derived_load(test_repo: TimeSeriesRepository) -> None:
    """尚無推算負載時任務特徵必須明確失敗，不得改抓外部來源。"""
    with pytest.raises(Failure, match="0 valid hourly observations"):
        _features(test_repo)


def test_task_features_refuse_training_below_minimum_accumulation(
    test_repo: TimeSeriesRepository,
) -> None:
    """預設 policies.min_training_hours=672：差一小時也不得進入訓練，並揭露差距。"""
    test_repo.upsert_taipower_load(derived_hourly_load(671, LAST_LOAD_HOUR))
    with pytest.raises(Failure, match="671 valid hourly observations; 672 required") as error:
        _features(test_repo)

    assert error.value.metadata["valid_hours"].value == 671
    assert error.value.metadata["required_hours"].value == 672


def test_task_features_return_target_rows_once_minimum_accumulation_is_met(
    test_repo: TimeSeriesRepository,
) -> None:
    test_repo.upsert_taipower_load(derived_hourly_load(672, LAST_LOAD_HOUR))

    table = _features(test_repo)

    assert len(table) == 672
    assert table["datetime"].max() == pd.Timestamp(LAST_LOAD_HOUR)


def test_training_load_source_excludes_other_provenance(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_task_policies(monkeypatch, min_training_hours=2)
    test_repo.upsert_taipower_load(derived_hourly_load(2, LAST_LOAD_HOUR))
    test_repo.upsert_taipower_load(
        pd.DataFrame([{"datetime": "2026-09-26 11:00", "load_mw": 99999.0}]),
        source="other_source",
    )

    table = _features(test_repo)

    assert len(table) == 2
    assert 99999.0 not in table["load_mw"].tolist()


def test_dagster_materialize_ingestion_and_feature_pipeline(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    dagster_instance,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify Dagster materialize reads persisted load and weather through feature engineering."""
    # fixture 只有 48 小時；降低門檻以驗證特徵鏈路，門檻本身由上方測試涵蓋。
    override_task_policies(monkeypatch, min_training_hours=len(taipower_raw_df))
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
            assets=[FEATURES_ASSET, feast_feature_export],
            resources={
                "time_series_repo": test_repo,
                "feast_io_manager": get_feast_parquet_io_manager(
                    FeastPublicationTarget.from_settings(settings)
                ),
            },
            instance=dagster_instance,
        )

    assert res.success
    training_table = res.output_for_node(NAMES.features)
    assert list(training_table.columns) == [
        "datetime",
        "subject",
        "load_mw",
        "temperature",
        "relative_humidity",
    ]

    persisted_load = test_repo.fetch_load_range(subject="nationwide")
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(reference_point="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)


def test_training_then_monitoring_jobs_read_latest_persisted_actual_load(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """監控以最新入庫的逐時實際負載對照前次訓練產物，且不執行任何擷取資產。"""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    override_task_policies(monkeypatch, min_training_hours=len(taipower_raw_df))
    test_repo.upsert_taipower_load(taipower_raw_df)
    test_repo.upsert_cwa_observation_batch(cwa_observation_batch)
    job_defs = Definitions(
        assets=all_assets,
        jobs=task_jobs(),
        resources={
            "time_series_repo": test_repo,
            "io_manager": get_parquet_io_manager("local", "unused", tmp_path),
            "feast_io_manager": get_feast_parquet_io_manager(
                FeastPublicationTarget.local(tmp_path)
            ),
        },
    )

    with patch(
        "shiro_mlops.pipelines.task_pipelines.log_training_run",
        return_value=TrackedRun(run_id="run-1", model_version="1"),
    ) as log_training_run:
        training = job_defs.resolve_job_def(NAMES.training_job).execute_in_process(
            instance=dagster_instance
        )
    next_hour = taipower_raw_df["datetime"].max() + pd.Timedelta(hours=1)
    test_repo.upsert_taipower_load(derived_hourly_load(1, next_hour.to_pydatetime()))

    def refuse_full_history(*_: object, **__: object) -> None:
        raise AssertionError("Hourly monitoring must not read the full load history")

    monkeypatch.setattr(test_repo, "fetch_load_range", refuse_full_history)
    monitoring = job_defs.resolve_job_def(NAMES.monitoring_job).execute_in_process(
        instance=dagster_instance
    )

    assert training.success
    assert monitoring.success
    assert log_training_run.call_count == 1
    model = training.output_for_node(NAMES.model)
    assert (model["run_id"], model["model_version"]) == ("run-1", "1")
    report = monitoring.output_for_node(NAMES.monitoring)
    assert report["task_id"] == DYNAMIC_HORIZON_FORECAST
    assert report["latest_actual_load_time"] == next_hour.isoformat()
    assert report["actual_load_hours"] == len(taipower_raw_df) + 1
    assert report["training_rows"] == len(taipower_raw_df)
