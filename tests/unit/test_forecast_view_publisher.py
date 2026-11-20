"""Which destinations the Forecast View export writes, from the deployment's settings (ADR-0015 §2.3)."""

from pathlib import Path

import boto3

from shiro_mlops.core.config import Settings
from shiro_mlops.core.forecast_view_publisher import ForecastViewPublisher


def test_without_a_bucket_the_publisher_writes_only_under_data_dir(tmp_path: Path) -> None:
    publisher = ForecastViewPublisher.from_settings(Settings(_env_file=None, DATA_DIR=tmp_path))

    assert publisher.local_dir == tmp_path / "published"
    assert publisher.s3 is None
    assert publisher.uploads_to_s3 is False


def test_with_a_bucket_the_publisher_uploads_with_the_configured_key_and_region(
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
