"""Exporting the Forecast View's published JSON: local directory first, then S3 (ADR-0015 §2.3–2.4)."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from botocore.stub import Stubber
from dagster import materialize

from shiro_mlops.core.config import Settings
from shiro_mlops.core.forecast_view_publisher import ForecastViewPublisher
from shiro_mlops.core.io_managers import get_parquet_io_manager
from shiro_mlops.data.forecast_view import (
    FORECAST_TRACK_RECORD_FILE,
    LATEST_ISSUED_FORECAST_FILE,
)
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.forecast_track_record import (
    FORECAST_TRACK_RECORD_ASSET,
    forecast_track_record,
)
from shiro_mlops.pipelines.forecast_view_export import (
    FORECAST_VIEW_EXPORT_ASSET,
    forecast_view_export,
)

# 預報實績在 10:25 彙整（統計截至 10:00），匯出排在其後。
TRACK_RECORD_TICK = "2026-11-20T10:25:00"
ISSUED_AT = datetime(2026, 11, 20, 10, 15)
BUCKET = "shiro-mlops-forecast-view"


def _issued_forecast(issued_at: datetime = ISSUED_AT, *, steps: int = 4) -> IssuedForecast:
    """Degraded, with a model version; the load anchor lags two hours behind the issue time.

    So the first two steps (09:00 and 10:00 for a 10:15 issue) are not after the issue time.
    """
    anchor = issued_at.replace(minute=0) - timedelta(hours=2)
    return IssuedForecast(
        issued_at=issued_at,
        load_anchor=anchor,
        status="degraded",
        model_sha256="a" * 64,
        mlflow_model_version="7",
        steps=tuple(
            IssuedForecastStep(
                target_hour=anchor + timedelta(hours=k), predicted_load_mw=30000.0 + k
            )
            for k in range(1, steps + 1)
        ),
    )


def _local_publisher(data_dir: Path) -> ForecastViewPublisher:
    """The publisher a deployment without any S3 setting builds."""
    return ForecastViewPublisher.from_settings(Settings(_env_file=None, DATA_DIR=data_dir))


def _export(
    repo: TimeSeriesRepository,
    data_dir: Path,
    instance,
    publisher: ForecastViewPublisher | None = None,
    *,
    raise_on_error: bool = True,
):
    """Compile the track record, then export, the way the two hourly schedules run."""
    resources = {
        "time_series_repo": repo,
        "io_manager": get_parquet_io_manager(data_dir=data_dir),
        "forecast_view_publisher": publisher or _local_publisher(data_dir),
    }
    materialize(
        [forecast_track_record],
        resources=resources,
        run_config={
            "ops": {FORECAST_TRACK_RECORD_ASSET: {"config": {"scheduled_at": TRACK_RECORD_TICK}}}
        },
        instance=instance,
    )
    return materialize(
        [forecast_track_record, forecast_view_export],
        selection=[FORECAST_VIEW_EXPORT_ASSET],
        resources=resources,
        instance=instance,
        raise_on_error=raise_on_error,
    )


def _published(data_dir: Path, name: str) -> dict:
    return json.loads((data_dir / "published" / name).read_text(encoding="utf-8"))


def test_without_s3_settings_the_export_writes_only_the_local_directory(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance, mocker
) -> None:
    boto3_client = mocker.patch("boto3.client")
    test_repo.insert_issued_forecast(_issued_forecast())

    result = _export(test_repo, tmp_path, dagster_instance)

    assert result.success
    assert sorted(path.name for path in (tmp_path / "published").iterdir()) == [
        FORECAST_TRACK_RECORD_FILE,
        LATEST_ISSUED_FORECAST_FILE,
    ]
    boto3_client.assert_not_called()


def _stubbed_s3_publisher(data_dir: Path) -> tuple[ForecastViewPublisher, Stubber]:
    """A publisher configured for S3 whose client never leaves the process."""
    settings = Settings(
        _env_file=None,
        DATA_DIR=data_dir,
        FORECAST_VIEW_S3_BUCKET=BUCKET,
        AWS_ACCESS_KEY_ID="AKIAEXAMPLEONLY",
        AWS_SECRET_ACCESS_KEY="offline-test-secret",
    )
    publisher = ForecastViewPublisher.from_settings(settings)
    assert publisher.s3 is not None
    return publisher, Stubber(publisher.s3.client)


def _expect_upload(stubber: Stubber, data_dir: Path, name: str) -> None:
    """Exactly these parameters: the local bytes, JSON type, and no Cache-Control metadata."""
    stubber.add_response(
        "put_object",
        {},
        {
            "Bucket": BUCKET,
            "Key": f"published/{name}",
            "Body": (data_dir / "published" / name).read_bytes(),
            "ContentType": "application/json",
        },
    )


def test_with_a_bucket_set_the_export_uploads_the_local_files_to_the_published_prefix(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    test_repo.insert_issued_forecast(_issued_forecast())
    # 先以純地端匯出產生期望的位元組，再讓上傳端比對同一份內容。
    _export(test_repo, tmp_path, dagster_instance)
    publisher, stubber = _stubbed_s3_publisher(tmp_path)
    _expect_upload(stubber, tmp_path, LATEST_ISSUED_FORECAST_FILE)
    _expect_upload(stubber, tmp_path, FORECAST_TRACK_RECORD_FILE)

    with stubber:
        result = _export(test_repo, tmp_path, dagster_instance, publisher)

    assert result.success
    stubber.assert_no_pending_responses()
    [materialization] = result.asset_materializations_for_node(FORECAST_VIEW_EXPORT_ASSET)
    assert materialization.metadata["uploaded_to_s3"].value is True


def test_a_failed_upload_fails_the_export_after_the_local_directory_is_current(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    publisher, stubber = _stubbed_s3_publisher(tmp_path)
    stubber.add_client_error("put_object", service_error_code="AccessDenied", http_status_code=403)
    test_repo.insert_issued_forecast(_issued_forecast())

    with stubber:
        result = _export(test_repo, tmp_path, dagster_instance, publisher, raise_on_error=False)

    assert not result.success
    assert _published(tmp_path, LATEST_ISSUED_FORECAST_FILE)["issued_at"] == (
        "2026-11-20T10:15:00+08:00"
    )
    assert (tmp_path / "published" / FORECAST_TRACK_RECORD_FILE).is_file()


def test_latest_forecast_publishes_only_issue_time_target_hours_and_predicted_load(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    """09:00 and 10:00 are not after the 10:15 issue time.

    No run status, load anchor, weather value, weather source or model version is published.
    """
    test_repo.insert_issued_forecast(_issued_forecast())

    _export(test_repo, tmp_path, dagster_instance)

    assert _published(tmp_path, LATEST_ISSUED_FORECAST_FILE) == {
        "issued_at": "2026-11-20T10:15:00+08:00",
        "steps": [
            {"target_hour": "2026-11-20T11:00:00+08:00", "predicted_load_mw": 30003.0},
            {"target_hour": "2026-11-20T12:00:00+08:00", "predicted_load_mw": 30004.0},
        ],
    }


def test_the_latest_issue_time_wins_over_earlier_issues(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    test_repo.insert_issued_forecast(_issued_forecast(ISSUED_AT))
    test_repo.insert_issued_forecast(_issued_forecast(ISSUED_AT - timedelta(hours=1)))

    result = _export(test_repo, tmp_path, dagster_instance)

    assert _published(tmp_path, LATEST_ISSUED_FORECAST_FILE)["issued_at"] == (
        "2026-11-20T10:15:00+08:00"
    )
    [materialization] = result.asset_materializations_for_node(FORECAST_VIEW_EXPORT_ASSET)
    assert materialization.metadata["issued_at"].value == "2026-11-20T10:15:00+08:00"
    assert materialization.metadata["published_steps"].value == 2


def test_before_the_first_issue_both_documents_are_empty_states(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    result = _export(test_repo, tmp_path, dagster_instance)

    assert result.success
    assert _published(tmp_path, LATEST_ISSUED_FORECAST_FILE) == {"issued_at": None, "steps": []}
    assert _published(tmp_path, FORECAST_TRACK_RECORD_FILE) == {
        "cutoff": "2026-11-20T10:00:00+08:00",
        "accumulated_days": 0,
        "metrics": None,
    }


def test_track_record_publishes_its_public_fields_and_cutoff(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    """Daily 09:15 issues over 8 days; every step predicts 30000 MW against 25000 MW observed.

    That is 20 % and 5000 MW at every lead time with a pair.
    """
    for day in range(8):
        issued_at = datetime(2026, 11, 12, 9, 15) + timedelta(days=day)
        anchor = issued_at.replace(minute=0) - timedelta(hours=1)
        test_repo.insert_issued_forecast(
            IssuedForecast(
                issued_at=issued_at,
                load_anchor=anchor,
                status="normal",
                model_sha256="b" * 64,
                mlflow_model_version=None,
                steps=tuple(
                    IssuedForecastStep(anchor + timedelta(hours=k), 30000.0) for k in range(1, 169)
                ),
            )
        )
    cutoff = datetime(2026, 11, 20, 10, 0)
    hours = [cutoff - timedelta(hours=offset) for offset in range(1, 200)]
    test_repo.upsert_taipower_load(
        pd.DataFrame({"datetime": hours, "load_mw": [25000.0] * len(hours)})
    )

    _export(test_repo, tmp_path, dagster_instance)

    document = _published(tmp_path, FORECAST_TRACK_RECORD_FILE)
    assert document.keys() == {"cutoff", "accumulated_days", "metrics"}
    assert document["cutoff"] == "2026-11-20T10:00:00+08:00"
    assert document["accumulated_days"] == 9
    metrics = document["metrics"]
    assert metrics.keys() == {"lead_time_curve", "lead_24", "lead_24_series"}
    curve = metrics["lead_time_curve"]
    assert [cell["lead_time_hours"] for cell in curve] == list(range(1, 169))
    assert curve[167] == {"lead_time_hours": 168, "mape": None, "mae": None}
    assert metrics["lead_24"].keys() == {"lead_time_hours", "mape", "mae"}
    assert metrics["lead_24"]["lead_time_hours"] == 24
    assert metrics["lead_24"]["mape"] == pytest.approx(20.0)
    assert metrics["lead_24"]["mae"] == pytest.approx(5000.0)
    assert metrics["lead_24_series"][0] == {
        "target_hour": "2026-11-13T09:00:00+08:00",
        "actual_load_mw": 25000.0,
        "predicted_load_mw": 30000.0,
    }
    assert len(metrics["lead_24_series"]) == 8


def test_each_export_overwrites_the_same_file_names(
    test_repo: TimeSeriesRepository, tmp_path: Path, dagster_instance
) -> None:
    test_repo.insert_issued_forecast(_issued_forecast(ISSUED_AT))
    _export(test_repo, tmp_path, dagster_instance)
    test_repo.insert_issued_forecast(_issued_forecast(ISSUED_AT + timedelta(hours=1)))

    _export(test_repo, tmp_path, dagster_instance)

    assert sorted(path.name for path in (tmp_path / "published").iterdir()) == [
        FORECAST_TRACK_RECORD_FILE,
        LATEST_ISSUED_FORECAST_FILE,
    ]
    assert _published(tmp_path, LATEST_ISSUED_FORECAST_FILE)["issued_at"] == (
        "2026-11-20T11:15:00+08:00"
    )
