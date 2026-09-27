"""Integration tests for Feast Parquet export, offline feature retrieval, and full pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from dagster import AssetKey, build_asset_context, build_output_context, materialize
from feast import FeatureStore
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import settings
from shiro_mlops.core.io_managers import FeastPublicationTarget, get_feast_parquet_io_manager
from shiro_mlops.data.cwa_client import CWAObservationBatch, CWAStationObservation
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.features.definitions import (
    create_load_source,
    create_taipower_load_feature_view,
    create_weather_feature_view,
    create_weather_source,
    location_entity,
)
from shiro_mlops.features.feast_export import build_feast_feature_frames
from shiro_mlops.pipelines.assets import feast_feature_export, raw_cwa_station_observation
from shiro_mlops.pipelines.task_pipelines import TaskPipelineNames, build_task_pipeline
from shiro_mlops.pipelines.tracking import TrackedRun
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task, deployed_tasks
from shiro_mlops.tasks.runner import TaskRuntime, load_training_data
from shiro_mlops.tasks.types.base import TrainingData
from tests.helpers import canonical_observation_batch, override_task_policies

# 夾具最後一筆負載為 2026-08-21 23:00；以明確 as_of 使訓練資料時間點可重現。
FIXTURE_AS_OF = pd.Timestamp("2026-08-22 00:00").to_pydatetime()


def _training_data(
    repository: TimeSeriesRepository, monkeypatch, as_of=FIXTURE_AS_OF
) -> TrainingData:
    """Read training data through the runner with a threshold the fixture satisfies."""
    override_task_policies(monkeypatch, min_training_hours=1)
    return load_training_data(
        deployed_task(DYNAMIC_HORIZON_FORECAST), TaskRuntime(repository=repository), as_of=as_of
    )


def _dynamic_horizon_forecast_assets():
    return build_task_pipeline(deployed_tasks(), DYNAMIC_HORIZON_FORECAST).assets


def _feast_frames(repository: TimeSeriesRepository, monkeypatch):
    data = _training_data(repository, monkeypatch)
    return build_feast_feature_frames(data.load, data.weather)


def _publish_feast_frames(data_dir: Path, taipower: pd.DataFrame, weather: pd.DataFrame) -> None:
    """Publish Feast frames through the same I/O Manager boundary used by Dagster assets."""
    manager = get_feast_parquet_io_manager(FeastPublicationTarget.local(data_dir))
    manager.handle_output(
        build_output_context(asset_key=AssetKey(["taipower_features"])),
        taipower,
    )
    manager.handle_output(
        build_output_context(asset_key=AssetKey(["weather_features"])),
        weather,
    )


def test_training_data_from_db_materializes_feast_parquet(
    populated_repo: TimeSeriesRepository,
    tmp_path: Path,
    monkeypatch,
):
    """Runner training data from the DB feeds the Feast export the I/O Manager writes."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    frames = _feast_frames(populated_repo, monkeypatch)
    _publish_feast_frames(tmp_path, frames.taipower, frames.weather)

    assert (tmp_path / "taipower_features.parquet").exists()
    assert (tmp_path / "weather_features.parquet").exists()

    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert {"datetime", "location", "load_mw", "hour", "is_weekend"}.issubset(tp_df.columns)

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert {"datetime", "location", "temperature", "relative_humidity"}.issubset(w_df.columns)


def test_training_data_excludes_other_load_provenance(
    test_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    monkeypatch,
) -> None:
    derived = taipower_raw_df.iloc[:3].copy()
    test_repo.upsert_taipower_load(derived)
    other = derived.iloc[[1]].copy()
    other["datetime"] = other["datetime"] + pd.Timedelta(minutes=30)
    other["load_mw"] = 99999.0
    test_repo.upsert_taipower_load(other, source="other_source")
    test_repo.upsert_cwa_observation_batch(canonical_observation_batch(cwa_obs_df))

    data = _training_data(test_repo, monkeypatch)

    assert len(data.load) == 3
    assert 99999.0 not in data.load["load_mw"].tolist()


def test_training_data_isolates_subject_and_weather_reference_point(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    monkeypatch,
):
    """Only the task's subject trains, and weather comes only from its reference point."""
    repo = TimeSeriesRepository(engine=sqlite_engine)
    repo.upsert_taipower_load(taipower_raw_df, default_subject="nationwide")
    repo.upsert_cwa_observation_batch(canonical_observation_batch(cwa_obs_df))

    north_load = taipower_raw_df.copy()
    north_load["load_mw"] = north_load["load_mw"] * 0.6
    repo.upsert_taipower_load(north_load, default_subject="north")

    kh_weather = cwa_obs_df.copy()
    kh_weather["temperature"] = kh_weather["temperature"] + 30.0
    kh_weather["location"] = "Kaohsiung"
    repo.upsert_cwa_observation_batch(canonical_observation_batch(kh_weather))

    data = _training_data(repo, monkeypatch)

    assert set(data.load["subject"]) == {"nationwide"}
    assert data.load["load_mw"].tolist() == taipower_raw_df["load_mw"].tolist()
    assert data.weather["temperature"].max() <= cwa_obs_df["temperature"].max()


def test_feast_export_keeps_multiple_subjects_isolated_with_unique_keys(
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
):
    """Both frozen views keep one row per (datetime, subject) when several subjects export."""
    nationwide = taipower_raw_df.assign(subject="nationwide")
    north = taipower_raw_df.assign(subject="north", load_mw=taipower_raw_df["load_mw"] * 0.6)

    frames = build_feast_feature_frames(pd.concat([nationwide, north]), cwa_obs_df)
    _publish_feast_frames(tmp_path, frames.taipower, frames.weather)

    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert set(tp_df["location"]) == {"nationwide", "north"}
    assert not tp_df.duplicated(subset=["datetime", "location"]).any()
    north_lags = tp_df[tp_df["location"] == "north"].sort_values("datetime")["load_mw_lag_1"]
    assert north_lags.iloc[1] == pytest.approx(taipower_raw_df["load_mw"].iloc[0] * 0.6)

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert set(w_df["location"]) == {"nationwide", "north"}
    assert not w_df.duplicated(subset=["datetime", "location"]).any()


def test_training_data_excludes_rows_after_as_of(sqlite_engine: Engine, monkeypatch) -> None:
    """Training reads only target rows known at ``as_of`` and derives its window from them."""
    repository = TimeSeriesRepository(engine=sqlite_engine)
    source_load = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "subject": "nationwide"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "subject": "nationwide"},
            {"datetime": "2026-08-21 00:00:00", "load_mw": 9999.0, "subject": "nationwide"},
        ]
    )
    source_weather = pd.DataFrame(
        [
            {
                "datetime": moment,
                "temperature": 30.0,
                "relative_humidity": 70.0,
                "location": "Taipei",
            }
            for moment in source_load["datetime"]
        ]
    )
    repository.upsert_taipower_load(source_load)
    repository.upsert_cwa_observation_batch(canonical_observation_batch(source_weather))

    data = _training_data(repository, monkeypatch, as_of=pd.Timestamp("2026-08-20 12:00"))

    assert data.load["datetime"].max() == pd.Timestamp("2026-08-20 01:00:00")
    assert 9999.0 not in data.load["load_mw"].tolist()
    assert data.weather["datetime"].max() == pd.Timestamp("2026-08-20 01:00:00")


def test_short_dataset_feast_parquet_schema_contract(
    tmp_path: Path,
):
    """Verify Feast Parquet output maintains strict schema even on small sample datasets."""

    short_load = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-20", periods=5, freq="h"),
            "load_mw": [100.0, 110.0, 105.0, 120.0, 115.0],
            "subject": ["nationwide"] * 5,
        }
    )
    short_weather = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-20", periods=5, freq="h"),
            "temperature": [25.0, 26.0, 25.5, 27.0, 26.5],
            "relative_humidity": [70.0, 68.0, 72.0, 65.0, 67.0],
            "location": ["Taipei"] * 5,
        }
    )

    frames = build_feast_feature_frames(short_load, short_weather)
    _publish_feast_frames(tmp_path, frames.taipower, frames.weather)

    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert len(tp_df) == 5

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

    assert tp_df["load_mw_lag_24"].dtype == "float32"
    assert tp_df["load_mw_rolling_mean_24"].dtype == "float32"
    assert tp_df["hour"].dtype == "int64"

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert len(w_df) == 5
    assert w_df["temperature"].dtype == "float32"
    assert w_df["relative_humidity"].dtype == "float32"


def test_feast_offline_feature_retrieval(
    populated_repo: TimeSeriesRepository,
    tmp_path: Path,
    monkeypatch,
):
    """Verify Feast get_historical_features retrieves the frozen exported features."""
    frames = _feast_frames(populated_repo, monkeypatch)
    _publish_feast_frames(tmp_path, frames.taipower, frames.weather)

    store = FeatureStore(repo_path=str(settings.FEAST_REPO_PATH))
    load_view = create_taipower_load_feature_view(
        create_load_source(str(tmp_path / "taipower_features.parquet"))
    )
    weather_view = create_weather_feature_view(
        create_weather_source(str(tmp_path / "weather_features.parquet"))
    )
    store.apply([location_entity, load_view, weather_view])

    entity_df = pd.DataFrame(
        {
            "location": ["nationwide", "nationwide"],
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


def test_full_dagster_mlops_pipeline_materialization(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    dagster_instance,
    tmp_path: Path,
    monkeypatch,
):
    """Verify full Dagster pipeline executes end-to-end from ingestion to monitoring offline and fast."""
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
    repository = TimeSeriesRepository(engine=sqlite_engine)
    with patch(
        "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
        return_value=observation_batch,
    ):
        raw_cwa_station_observation(build_asset_context(resources={"time_series_repo": repository}))
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    # fixture 只有 48 小時；降低訓練最低累積門檻以驗證完整鏈路。
    override_task_policies(monkeypatch, min_training_hours=len(taipower_raw_df))
    repo = TimeSeriesRepository(engine=sqlite_engine)
    feast_io_manager = get_feast_parquet_io_manager(FeastPublicationTarget.local(tmp_path))

    repo.upsert_taipower_load(taipower_raw_df)

    with (
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
            return_value=observation_batch,
        ),
        patch(
            "shiro_mlops.pipelines.task_pipelines.log_training_run",
            return_value=TrackedRun(run_id="test_run_123", model_version="1"),
        ),
    ):
        res = materialize(
            assets=[*_dynamic_horizon_forecast_assets(), feast_feature_export],
            resources={
                "time_series_repo": repo,
                "feast_io_manager": feast_io_manager,
            },
            instance=dagster_instance,
        )

    assert res.success
    model_dir = tmp_path / "models" / "dynamic_horizon_forecast"
    assert sorted(path.name for path in model_dir.iterdir()) == ["metadata.json", "model.txt"]
    assert not (tmp_path / "model.joblib").exists()
    assert (tmp_path / "taipower_features.parquet").exists()
    assert (tmp_path / "weather_features.parquet").exists()

    report = res.output_for_node(TaskPipelineNames(DYNAMIC_HORIZON_FORECAST).monitoring)
    assert report["status"] in {"HEALTHY", "WARNING"}
    assert "max_mape=10.0" in report["health_reason"]
    assert report["training_rows"] == len(taipower_raw_df)
    assert report["target_hours"] == len(taipower_raw_df)
    assert report["latest_target_time"] == "2026-08-21T23:00:00"
    assert report["latest_target_value"] == 29100.0


def test_publish_parquet_feature_local_and_s3(tmp_path):
    """Verify publish_parquet_feature exports matching schemas to local disk and S3."""
    import io

    from shiro_mlops.features.storage import publish_parquet_feature

    sample_df = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-08-20 14:00:00"),
                "location": "nationwide",
                "load_mw": 35000.0,
            }
        ]
    )

    local_target = str(tmp_path / "test_feature.parquet")
    published_local = publish_parquet_feature(sample_df, local_target)
    assert Path(published_local).exists()
    local_read_df = pd.read_parquet(published_local)
    assert len(local_read_df) == 1

    mock_s3 = MagicMock()
    s3_target = "s3://test-bucket/features/test_feature.parquet"
    published_s3 = publish_parquet_feature(sample_df, s3_target, s3_client=mock_s3)
    assert published_s3 == s3_target
    assert mock_s3.put_object.called
    kwargs = mock_s3.put_object.call_args[1]
    assert kwargs["Bucket"] == "test-bucket"
    assert kwargs["Key"] == "features/test_feature.parquet"

    s3_read_df = pd.read_parquet(io.BytesIO(kwargs["Body"]))
    pd.testing.assert_frame_equal(local_read_df, s3_read_df)


def test_engineered_features_publishes_to_s3_via_io_manager(
    populated_repo: TimeSeriesRepository,
    monkeypatch,
):
    """Verify Feast I/O Manager publishes feature files to S3 when configured."""
    frames = _feast_frames(populated_repo, monkeypatch)
    taipower, weather = frames.taipower, frames.weather
    mock_s3 = MagicMock()
    feast_manager = get_feast_parquet_io_manager(
        FeastPublicationTarget.s3("my-s3-feast-bucket", "features", s3_client=mock_s3)
    )
    feast_manager.handle_output(
        build_output_context(asset_key=AssetKey(["taipower_features"])),
        taipower,
    )
    feast_manager.handle_output(
        build_output_context(asset_key=AssetKey(["weather_features"])),
        weather,
    )

    assert mock_s3.put_object.call_count == 2
    keys = {call.kwargs["Key"] for call in mock_s3.put_object.call_args_list}
    assert "features/taipower_features.parquet" in keys
    assert "features/weather_features.parquet" in keys


def test_feast_retrieves_s3_published_features_offline(
    populated_repo: TimeSeriesRepository,
    monkeypatch,
):
    """Feast retrieves feature contracts from S3 after the I/O Manager publishes them."""
    import boto3
    from moto.server import ThreadedMotoServer

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    moto_server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    moto_server.start()
    host, port = moto_server.get_host_and_port()
    endpoint_url = f"http://{host}:{port}"

    try:
        s3_client = boto3.client("s3", region_name="us-east-1", endpoint_url=endpoint_url)
        bucket = "feast-offline-test"
        prefix = "features"
        s3_client.create_bucket(Bucket=bucket)

        frames = _feast_frames(populated_repo, monkeypatch)
        taipower, weather = frames.taipower, frames.weather
        feast_manager = get_feast_parquet_io_manager(
            FeastPublicationTarget.s3(bucket, prefix, s3_client=s3_client)
        )
        feast_manager.handle_output(
            build_output_context(asset_key=AssetKey(["taipower_features"])),
            taipower,
        )
        feast_manager.handle_output(
            build_output_context(asset_key=AssetKey(["weather_features"])),
            weather,
        )

        store = FeatureStore(repo_path=str(settings.FEAST_REPO_PATH))
        load_view = create_taipower_load_feature_view(
            create_load_source(
                f"s3://{bucket}/{prefix}/taipower_features.parquet",
                s3_endpoint_override=endpoint_url,
            )
        )
        weather_view = create_weather_feature_view(
            create_weather_source(
                f"s3://{bucket}/{prefix}/weather_features.parquet",
                s3_endpoint_override=endpoint_url,
            )
        )
        store.apply([location_entity, load_view, weather_view])

        entity_df = pd.DataFrame(
            {
                "location": ["nationwide"],
                "datetime": [pd.Timestamp("2026-08-21 12:00:00")],
            }
        )
        result = store.get_historical_features(
            entity_df=entity_df,
            features=[
                "taipower_load_features:load_mw",
                "cwa_weather_features:temperature",
            ],
        ).to_df()
    finally:
        moto_server.stop()

    # 匯出直接由目標負載計算，不再隨訓練氣象缺口刪列，故取得 12:00 當時的實際負載。
    assert result.loc[0, "load_mw"] == 38500.0
    assert result.loc[0, "temperature"] == 28.0


def test_feature_calculation_is_decoupled_from_storage_target(
    populated_repo: TimeSeriesRepository,
    monkeypatch,
):
    """Feature calculation returns identical Feast contracts regardless of storage settings."""
    frames_a = _feast_frames(populated_repo, monkeypatch)
    monkeypatch.setattr(settings, "FEAST_OFFLINE_STORE_TYPE", "s3")
    frames_b = _feast_frames(populated_repo, monkeypatch)

    pd.testing.assert_frame_equal(frames_a.taipower, frames_b.taipower)
    pd.testing.assert_frame_equal(frames_a.weather, frames_b.weather)


def test_feast_feature_view_source_switching(monkeypatch):
    """Verify Feast FileSource adapts between local and S3 without requiring a cloud database."""
    from shiro_mlops.features.definitions import create_load_source, create_weather_source

    monkeypatch.setattr(settings, "FEAST_OFFLINE_STORE_TYPE", "file")
    local_load_src = create_load_source()
    assert not local_load_src.path.startswith("s3://")

    monkeypatch.setattr(settings, "FEAST_OFFLINE_STORE_TYPE", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", "hybrid-s3-bucket")
    s3_load_src = create_load_source()
    assert s3_load_src.path == "s3://hybrid-s3-bucket/features/taipower_features.parquet"
    s3_weather_src = create_weather_source()
    assert s3_weather_src.path == "s3://hybrid-s3-bucket/features/weather_features.parquet"
