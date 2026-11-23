"""Integration tests for Dagster ingestion assets and database persistence."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import (
    AssetKey,
    Definitions,
    Failure,
    MetadataValue,
    build_asset_context,
    load_assets_from_modules,
    materialize,
)

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import get_feast_parquet_io_manager, get_parquet_io_manager
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
)
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines import assets as assets_module
from shiro_mlops.pipelines.assets import (
    CWA_SOURCE,
    feast_feature_export,
    raw_cwa_station_observation,
    raw_cwa_township_forecast,
)
from shiro_mlops.pipelines.task_pipelines import (
    TaskPipelineNames,
    build_task_pipeline,
    build_task_pipelines,
)
from shiro_mlops.pipelines.tracking import TrackedRun
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_tasks
from shiro_mlops.tasks.model_store import model_directory_sha256
from tests.helpers import (
    FixtureCWASource,
    derived_hourly_load,
    derived_load_series,
    insert_other_source_load_row,
    override_task_policies,
    unfetched_source_resources,
    write_derived_load,
)

LAST_LOAD_HOUR = datetime(2026, 9, 26, 13, 0)
NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)


def _features(repository: TimeSeriesRepository) -> pd.DataFrame:
    """Invoke the task's features asset the way a training run does."""
    features_asset = build_task_pipeline(deployed_tasks(), DYNAMIC_HORIZON_FORECAST).assets[0]
    with build_asset_context(resources={"time_series_repo": repository}) as context:
        return features_asset(context).value


def test_canonical_cwa_observation_asset_persists_batch_and_returns_complete():
    batch = MagicMock(spec=CWAObservationBatch)
    batch.status = "complete"
    batch.missing_station_ids = ()
    store = MagicMock(spec=CWAWeatherStore)
    resources = {
        "time_series_repo": SimpleNamespace(cwa_weather_store=store),
        CWA_SOURCE: FixtureCWASource(batch),
    }
    with build_asset_context(resources=resources) as context:
        result = raw_cwa_station_observation(context)

    assert result is batch
    store.upsert_cwa_observation_batch.assert_called_once_with(batch)


def test_canonical_cwa_forecast_asset_persists_both_products():
    releases = [
        MagicMock(spec=CWAForecastRelease, status="complete"),
        MagicMock(spec=CWAForecastRelease, status="complete"),
    ]
    source = FixtureCWASource(
        forecast_releases={"F-D0047-089": releases[0], "F-D0047-091": releases[1]}
    )
    store = MagicMock(spec=CWAWeatherStore)
    resources = {"time_series_repo": SimpleNamespace(cwa_weather_store=store), CWA_SOURCE: source}
    with build_asset_context(resources=resources) as context:
        result = raw_cwa_township_forecast(context)

    assert result == releases
    store.upsert_cwa_forecast_releases.assert_called_once_with(releases)


def test_task_features_fail_without_derived_load(test_repo: TimeSeriesRepository) -> None:
    """Task features fail clearly without derived load instead of fetching an external source."""
    with pytest.raises(Failure, match="0 valid hourly observations"):
        _features(test_repo)


def test_task_features_read_weather_from_configured_reference_station(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The weather reference station comes from runtime CWA settings rather than a fixed Taipei code."""
    monkeypatch.setattr(
        settings,
        "CWA_LOCATION_ALLOWLIST",
        '{"Taipei": {"station_id": "999999", "geocode": "99999999"}}',
    )
    override_task_policies(monkeypatch, min_training_hours=2)
    write_derived_load(test_repo.engine, derived_hourly_load(2, LAST_LOAD_HOUR))
    test_repo.upsert_cwa_observation_batch(
        CWAObservationBatch(
            fetched_at=LAST_LOAD_HOUR,
            status="complete",
            missing_station_ids=(),
            raw_payload={},
            observations=tuple(
                _station_observation(station_id, temperature)
                for station_id, temperature in (("999999", 30.0), ("466920", 10.0))
            ),
        )
    )

    table = _features(test_repo)

    assert (
        table.loc[table["datetime"] == pd.Timestamp(LAST_LOAD_HOUR), "temperature"].item() == 30.0
    )


def _station_observation(station_id: str, temperature: float) -> CWAStationObservation:
    return CWAStationObservation(
        observed_at=LAST_LOAD_HOUR,
        station_id=station_id,
        station_name=station_id,
        town_code=None,
        temperature_c=temperature,
        relative_humidity_pct=70.0,
        air_pressure_hpa=None,
        precipitation_mm=None,
        wind_speed_m_s=None,
        wind_direction_deg=None,
    )


def test_task_features_refuse_training_below_minimum_accumulation(
    test_repo: TimeSeriesRepository,
) -> None:
    """With min_training_hours=672, even one missing hour blocks training and reports the gap."""
    write_derived_load(test_repo.engine, derived_hourly_load(671, LAST_LOAD_HOUR))
    with pytest.raises(Failure, match="671 valid hourly observations; 672 required") as error:
        _features(test_repo)

    assert error.value.metadata["valid_hours"].value == 671
    assert error.value.metadata["required_hours"].value == 672


def test_task_features_return_target_rows_once_minimum_accumulation_is_met(
    test_repo: TimeSeriesRepository,
) -> None:
    write_derived_load(test_repo.engine, derived_hourly_load(672, LAST_LOAD_HOUR))

    table = _features(test_repo)

    assert len(table) == 672
    assert table["datetime"].max() == pd.Timestamp(LAST_LOAD_HOUR)


def test_training_load_source_excludes_other_provenance(
    test_repo: TimeSeriesRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    override_task_policies(monkeypatch, min_training_hours=2)
    write_derived_load(test_repo.engine, derived_hourly_load(2, LAST_LOAD_HOUR))
    insert_other_source_load_row(test_repo.engine, datetime(2026, 9, 26, 11, 0), 99999.0)

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
    write_derived_load(test_repo.engine, taipower_raw_df)
    resources = {"time_series_repo": test_repo, CWA_SOURCE: FixtureCWASource(observation_batch)}
    with build_asset_context(resources=resources) as context:
        raw_cwa_station_observation(context)
    features_asset = build_task_pipeline(deployed_tasks(), DYNAMIC_HORIZON_FORECAST).assets[0]
    res = materialize(
        assets=[features_asset, feast_feature_export],
        resources={
            "time_series_repo": test_repo,
            "feast_io_manager": get_feast_parquet_io_manager(data_dir=settings.DATA_DIR),
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

    persisted_load = derived_load_series(test_repo.engine)
    assert len(persisted_load) == len(taipower_raw_df)

    persisted_weather = test_repo.fetch_weather_range(reference_point="Taipei")
    assert len(persisted_weather) == len(cwa_obs_df)


def _trainable_task_definitions(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> Definitions:
    """Task jobs over a repository holding exactly enough history to train."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    override_task_policies(monkeypatch, min_training_hours=len(taipower_raw_df))
    write_derived_load(test_repo.engine, taipower_raw_df)
    test_repo.upsert_cwa_observation_batch(cwa_observation_batch)
    pipelines = build_task_pipelines(deployed_tasks())
    return Definitions(
        assets=[
            *load_assets_from_modules([assets_module]),
            *(asset for pipeline in pipelines for asset in pipeline.assets),
        ],
        jobs=[job for pipeline in pipelines for job in pipeline.jobs],
        resources={
            "time_series_repo": test_repo,
            "io_manager": get_parquet_io_manager(data_dir=tmp_path),
            "feast_io_manager": get_feast_parquet_io_manager(data_dir=tmp_path),
            **unfetched_source_resources(),
        },
    )


def _latest_model_metadata(instance) -> dict:
    event = instance.get_latest_materialization_event(AssetKey(NAMES.model))
    return event.asset_materialization.metadata


def test_model_materialization_records_the_saved_model_hash_and_mlflow_version(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_defs = _trainable_task_definitions(
        test_repo, taipower_raw_df, cwa_observation_batch, tmp_path, monkeypatch
    )

    with patch(
        "shiro_mlops.pipelines.task_pipelines.log_training_run",
        return_value=TrackedRun(run_id="run-1", model_version="7"),
    ):
        training = job_defs.resolve_job_def(NAMES.training_job).execute_in_process(
            instance=dagster_instance
        )

    assert training.success
    metadata = _latest_model_metadata(dagster_instance)
    installed = model_directory_sha256(settings.models_dir / DYNAMIC_HORIZON_FORECAST)
    assert metadata["model_sha256"] == MetadataValue.text(installed)
    assert metadata["mlflow_model_version"] == MetadataValue.text("7")


def test_model_materialization_keeps_the_model_hash_when_mlflow_is_unavailable(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_defs = _trainable_task_definitions(
        test_repo, taipower_raw_df, cwa_observation_batch, tmp_path, monkeypatch
    )

    with patch(
        "shiro_mlops.pipelines.task_pipelines.log_training_run",
        side_effect=ConnectionError("MLflow is down"),
    ):
        training = job_defs.resolve_job_def(NAMES.training_job).execute_in_process(
            instance=dagster_instance
        )

    assert training.success
    assert training.output_for_node(NAMES.model)["run_id"] == "local_run"
    metadata = _latest_model_metadata(dagster_instance)
    installed = model_directory_sha256(settings.models_dir / DYNAMIC_HORIZON_FORECAST)
    assert metadata["model_sha256"] == MetadataValue.text(installed)
    assert metadata["mlflow_model_version"] == MetadataValue.null()


def test_training_then_monitoring_jobs_read_latest_persisted_actual_load(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_observation_batch: CWAObservationBatch,
    dagster_instance,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monitoring uses the latest persisted actual load and prior model without running ingestion assets."""
    job_defs = _trainable_task_definitions(
        test_repo, taipower_raw_df, cwa_observation_batch, tmp_path, monkeypatch
    )

    with patch(
        "shiro_mlops.pipelines.task_pipelines.log_training_run",
        return_value=TrackedRun(run_id="run-1", model_version="1"),
    ) as log_training_run:
        training = job_defs.resolve_job_def(NAMES.training_job).execute_in_process(
            instance=dagster_instance
        )
    next_hour = taipower_raw_df["datetime"].max() + pd.Timedelta(hours=1)
    write_derived_load(test_repo.engine, derived_hourly_load(1, next_hour.to_pydatetime()))

    def refuse_full_history(*_: object, **__: object) -> None:
        raise AssertionError("Hourly monitoring must not read the full load history")

    monkeypatch.setattr(test_repo.hourly_actual_load_store, "series", refuse_full_history)
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
    assert report["latest_target_time"] == next_hour.isoformat()
    assert report["target_hours"] == len(taipower_raw_df) + 1
    assert report["training_rows"] == len(taipower_raw_df)
