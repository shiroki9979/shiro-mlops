"""Which destinations the Forecast View export writes, from the deployment's settings (ADR-0015 §2.3)."""

import os
from pathlib import Path

import boto3
import pytest

from shiro_mlops.core.config import Settings
from shiro_mlops.core.forecast_view_publisher import ForecastViewPublisher


def test_without_a_bucket_the_publisher_writes_only_under_data_dir(tmp_path: Path) -> None:
    publisher = ForecastViewPublisher.from_settings(Settings(_env_file=None, DATA_DIR=tmp_path))

    assert publisher.local_dir == tmp_path / "published"
    assert publisher.s3 is None
    assert publisher.uploads_to_s3 is False


def test_with_a_bucket_the_publisher_uploads_with_the_configured_key_and_default_region(
    tmp_path: Path, mocker
) -> None:
    create_client = mocker.patch("boto3.client", wraps=boto3.client)
    settings = Settings(
        _env_file=None,
        DATA_DIR=tmp_path,
        FORECAST_VIEW_S3_BUCKET="shiro-mlops-forecast-view",
        AWS_ACCESS_KEY_ID="AKIAEXAMPLEONLY",
        AWS_SECRET_ACCESS_KEY="offline-test-secret",
    )

    publisher = ForecastViewPublisher.from_settings(settings)

    assert publisher.local_dir == tmp_path / "published"
    assert publisher.s3 is not None
    assert publisher.s3.bucket == "shiro-mlops-forecast-view"
    assert publisher.s3.client.meta.region_name == "ap-northeast-1"
    create_client.assert_called_once_with(
        "s3",
        region_name="ap-northeast-1",
        aws_access_key_id="AKIAEXAMPLEONLY",
        aws_secret_access_key="offline-test-secret",
    )


def test_the_upload_region_follows_aws_default_region(tmp_path: Path) -> None:
    """Terraform's aws_region may differ from the default; the publisher must sign for it."""
    publisher = ForecastViewPublisher.from_settings(
        Settings(
            _env_file=None,
            DATA_DIR=tmp_path,
            FORECAST_VIEW_S3_BUCKET="bucket",
            AWS_DEFAULT_REGION="us-west-2",
        )
    )

    assert publisher.s3 is not None
    assert publisher.s3.client.meta.region_name == "us-west-2"


def test_with_a_bucket_but_no_key_boto3_falls_back_to_its_credential_chain(
    tmp_path: Path, mocker
) -> None:
    """Empty key settings are not passed as empty strings, which boto3 would sign with."""
    create_client = mocker.patch("boto3.client", wraps=boto3.client)

    ForecastViewPublisher.from_settings(
        Settings(_env_file=None, DATA_DIR=tmp_path, FORECAST_VIEW_S3_BUCKET="bucket")
    )

    create_client.assert_called_once_with(
        "s3", region_name="ap-northeast-1", aws_access_key_id=None, aws_secret_access_key=None
    )


def test_the_upload_key_never_appears_in_the_settings_repr() -> None:
    settings = Settings(_env_file=None, AWS_SECRET_ACCESS_KEY="offline-test-secret")

    assert "offline-test-secret" not in repr(settings)


def test_an_export_overlapping_another_does_not_lose_its_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manual materialization can overlap the scheduled export; both must finish."""
    published = tmp_path / "published"
    publisher = ForecastViewPublisher(published)
    real_replace = os.replace
    overlapped = False

    def replace_after_another_export_ran(source: object, target: object) -> None:
        nonlocal overlapped
        if not overlapped:
            overlapped = True
            publisher.publish({"latest.json": b"second"})
        real_replace(source, target)

    monkeypatch.setattr(os, "replace", replace_after_another_export_ran)

    publisher.publish({"latest.json": b"first"})

    assert (published / "latest.json").read_bytes() == b"first"
    assert [path.name for path in published.iterdir()] == ["latest.json"]


def test_a_failed_local_write_keeps_the_previous_file_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = tmp_path / "published"
    publisher = ForecastViewPublisher(published)
    publisher.publish({"latest.json": b"previous"})

    def disk_full(*_: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", disk_full)

    with pytest.raises(OSError, match="No space left"):
        publisher.publish({"latest.json": b"next"})

    assert (published / "latest.json").read_bytes() == b"previous"
    assert [path.name for path in published.iterdir()] == ["latest.json"]


def test_published_files_stay_readable_by_the_web_server(tmp_path: Path) -> None:
    """Nginx runs as another user; a private temporary file would be served as 403."""
    ForecastViewPublisher(tmp_path).publish({"latest.json": b"{}"})

    reference = tmp_path / "reference"
    reference.write_bytes(b"")
    assert (tmp_path / "latest.json").stat().st_mode == reference.stat().st_mode


def test_publishing_nothing_still_creates_the_directory(tmp_path: Path) -> None:
    target = tmp_path / "published"

    ForecastViewPublisher(target).publish({})

    assert target.is_dir()
    assert list(target.iterdir()) == []
