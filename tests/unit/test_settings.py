"""Unit tests for the application settings' environment and storage contracts."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from shiro_mlops.core.config import Settings


def test_settings_rejects_aws_environment() -> None:
    """`aws` 已無部署目標（ADR-0015 §2.2），載入時應拒收。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENVIRONMENT="aws")


def test_feature_parquet_uris_resolve_under_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """舊的 S3 切換設定即使殘留，特徵 Parquet 仍只寫在 DATA_DIR 之下。"""
    monkeypatch.setenv("FEAST_OFFLINE_STORE_TYPE", "s3")
    monkeypatch.setenv("S3_BUCKET_NAME", "stale-bucket")
    cfg = Settings(_env_file=None, DATA_DIR=tmp_path)

    assert cfg.taipower_parquet_uri == str(tmp_path.resolve() / "taipower_features.parquet")
    assert cfg.weather_parquet_uri == str(tmp_path.resolve() / "weather_features.parquet")
