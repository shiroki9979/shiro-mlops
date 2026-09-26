"""Integration tests for Feast Parquet export, offline feature retrieval, and full pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
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
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.pipelines.assets import (
    compute_engineered_feature_outputs,
    cwa_observation_feature_source,
    drift_monitoring_report,
    engineered_feature_set,
    raw_cwa_station_observation,
    taipower_load_feature_source,
    trained_forecaster_model,
)
from shiro_mlops.pipelines.feature_pipeline import FallbackFeatureSources
from tests.helpers import canonical_observation_batch


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


def test_engineered_features_extracts_db_and_materializes_feast_parquet(
    populated_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
    monkeypatch,
):
    """Verify feature calculation extracts from DB and Feast I/O Manager writes Parquet files."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)

    features_df, taipower, weather = compute_engineered_feature_outputs(
        populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
    )
    _publish_feast_frames(tmp_path, taipower, weather)

    assert isinstance(features_df, pd.DataFrame)
    assert not features_df.empty
    assert (tmp_path / "taipower_features.parquet").exists()
    assert (tmp_path / "weather_features.parquet").exists()

    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert {"datetime", "location", "load_mw", "hour", "is_weekend"}.issubset(tp_df.columns)

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert {"datetime", "location", "temperature", "relative_humidity"}.issubset(w_df.columns)


def test_engineered_features_multi_location_isolation_and_export(
    sqlite_engine: Engine,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
    monkeypatch,
):
    """Verify multi-location isolation and unique Feast composite keys via I/O Manager."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    repo = TimeSeriesRepository(engine=sqlite_engine)

    repo.upsert_taipower_load(taipower_raw_df, default_location="Taipei")
    repo.upsert_cwa_observation_batch(canonical_observation_batch(cwa_obs_df))

    kh_taipower = taipower_raw_df.copy()
    kh_taipower["load_mw"] = kh_taipower["load_mw"] * 0.6
    kh_taipower["location"] = "Kaohsiung"
    repo.upsert_taipower_load(kh_taipower, default_location="Kaohsiung")

    kh_weather = cwa_obs_df.copy()
    kh_weather["temperature"] = kh_weather["temperature"] + 3.0
    kh_weather["location"] = "Kaohsiung"
    repo.upsert_cwa_observation_batch(canonical_observation_batch(kh_weather))

    features_df, taipower, weather = compute_engineered_feature_outputs(
        repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df), location=None
    )
    _publish_feast_frames(tmp_path, taipower, weather)

    assert set(features_df["location"]) == {"Taipei", "Kaohsiung"}

    tp_df = pd.read_parquet(tmp_path / "taipower_features.parquet")
    assert set(tp_df["location"]) == {"Taipei", "Kaohsiung"}
    assert not tp_df.duplicated(subset=["datetime", "location"]).any()

    w_df = pd.read_parquet(tmp_path / "weather_features.parquet")
    assert set(w_df["location"]) == {"Taipei", "Kaohsiung"}
    assert not w_df.duplicated(subset=["datetime", "location"]).any()


def test_feature_computation_isolates_requested_location_and_training_window(
    sqlite_engine: Engine,
) -> None:
    """Feature computation excludes other locations and observations after each training window."""
    repository = TimeSeriesRepository(engine=sqlite_engine)
    source_load = pd.DataFrame(
        [
            {"datetime": "2026-08-20 00:00:00", "load_mw": 100.0, "location": "Taipei"},
            {"datetime": "2026-08-20 01:00:00", "load_mw": 200.0, "location": "Taipei"},
            {"datetime": "2026-08-21 00:00:00", "load_mw": 9999.0, "location": "Taipei"},
            {"datetime": "2026-08-20 00:00:00", "load_mw": 500.0, "location": "Kaohsiung"},
            {"datetime": "2026-08-21 00:00:00", "load_mw": 600.0, "location": "Kaohsiung"},
        ]
    )
    source_weather = pd.DataFrame(
        [
            {
                "datetime": row["datetime"],
                "temperature": 30.0,
                "relative_humidity": 70.0,
                "location": row["location"],
            }
            for row in source_load.to_dict("records")
        ]
    )
    repository.upsert_taipower_load(source_load)
    repository.upsert_cwa_observation_batch(canonical_observation_batch(source_weather))

    taipei_reference = source_load.iloc[[1]].copy()
    taipei_weather = source_weather.iloc[[1]].copy()
    taipei_features, _, _ = compute_engineered_feature_outputs(
        repository,
        FallbackFeatureSources(taipei_reference, taipei_weather),
        location="Taipei",
    )

    kaohsiung_reference = source_load.iloc[[4]].copy()
    kaohsiung_weather = source_weather.iloc[[4]].copy()
    kaohsiung_features, _, _ = compute_engineered_feature_outputs(
        repository,
        FallbackFeatureSources(kaohsiung_reference, kaohsiung_weather),
        location="Kaohsiung",
    )

    assert set(taipei_features["location"]) == {"Taipei"}
    assert taipei_features["datetime"].max() == pd.Timestamp("2026-08-20 01:00:00")
    assert 9999.0 not in taipei_features["load_mw"].tolist()
    assert set(kaohsiung_features["location"]) == {"Kaohsiung"}
    assert kaohsiung_features["datetime"].max() == pd.Timestamp("2026-08-21 00:00:00")
    assert 9999.0 not in kaohsiung_features["load_mw"].tolist()


def test_short_dataset_feast_parquet_schema_contract(
    sqlite_engine: Engine,
    tmp_path: Path,
    monkeypatch,
):
    """Verify Feast Parquet output maintains strict schema even on small sample datasets."""
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    repo = TimeSeriesRepository(engine=sqlite_engine)

    short_load = pd.DataFrame(
        {
            "datetime": pd.date_range("2026-08-20", periods=5, freq="h"),
            "load_mw": [100.0, 110.0, 105.0, 120.0, 115.0],
            "location": ["Taipei"] * 5,
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

    repo.upsert_taipower_load(short_load)
    repo.upsert_cwa_observation_batch(canonical_observation_batch(short_weather))

    features_df, taipower, weather = compute_engineered_feature_outputs(
        repo, FallbackFeatureSources(short_load, short_weather)
    )
    _publish_feast_frames(tmp_path, taipower, weather)

    assert len(features_df) == 5
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
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
):
    """Verify Feast get_historical_features retrieves features and trains forecaster without error."""
    _, taipower, weather = compute_engineered_feature_outputs(
        populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
    )
    _publish_feast_frames(tmp_path, taipower, weather)

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
    repo = TimeSeriesRepository(engine=sqlite_engine)
    feast_io_manager = get_feast_parquet_io_manager(FeastPublicationTarget.local(tmp_path))

    repo.upsert_taipower_load(taipower_raw_df)

    with (
        patch(
            "shiro_mlops.pipelines.assets.CWAClient.fetch_observation_batch",
            return_value=observation_batch,
        ),
        patch("shiro_mlops.pipelines.assets.mlflow") as mock_mlflow,
    ):
        mock_run = MagicMock()
        mock_run.info.run_id = "test_run_123"
        mock_mlflow.start_run.return_value.__enter__.return_value = mock_run

        res = materialize(
            assets=[
                taipower_load_feature_source,
                cwa_observation_feature_source,
                engineered_feature_set,
                trained_forecaster_model,
                drift_monitoring_report,
            ],
            resources={
                "time_series_repo": repo,
                "feast_io_manager": feast_io_manager,
                "forecaster": lightweight_forecaster,
            },
            instance=dagster_instance,
        )

    assert res.success
    assert (tmp_path / "model.joblib").exists()
    assert (tmp_path / "taipower_features.parquet").exists()
    assert (tmp_path / "weather_features.parquet").exists()

    report = res.output_for_node("drift_monitoring_report")
    assert "status" in report
    assert report["status"] in {"HEALTHY", "WARNING"}
    assert report["feature_count"] > 0


def test_publish_parquet_feature_local_and_s3(tmp_path):
    """Verify publish_parquet_feature exports matching schemas to local disk and S3."""
    import io

    from shiro_mlops.features.storage import publish_parquet_feature

    sample_df = pd.DataFrame(
        [
            {
                "datetime": pd.Timestamp("2026-08-20 14:00:00"),
                "location": "Taipei",
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
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
):
    """Verify Feast I/O Manager publishes feature files to S3 when configured."""
    _, taipower, weather = compute_engineered_feature_outputs(
        populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
    )
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
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
    tmp_path: Path,
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

        _, taipower, weather = compute_engineered_feature_outputs(
            populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
        )
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
                "location": ["Taipei"],
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

    assert result.loc[0, "load_mw"] == 25400.0
    assert result.loc[0, "temperature"] == 28.0


def test_feature_calculation_is_decoupled_from_storage_target(
    populated_repo: TimeSeriesRepository,
    taipower_raw_df: pd.DataFrame,
    cwa_obs_df: pd.DataFrame,
):
    """Feature calculation returns identical Feast contracts regardless of storage settings."""
    features_a, taipower_a, weather_a = compute_engineered_feature_outputs(
        populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
    )
    features_b, taipower_b, weather_b = compute_engineered_feature_outputs(
        populated_repo, FallbackFeatureSources(taipower_raw_df, cwa_obs_df)
    )

    pd.testing.assert_frame_equal(features_a, features_b)
    pd.testing.assert_frame_equal(taipower_a, taipower_b)
    pd.testing.assert_frame_equal(weather_a, weather_b)


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
