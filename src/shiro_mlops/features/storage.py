"""Storage publisher and loader for Feast offline features (Local FS & S3)."""

import io
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from shiro_mlops.core.config import settings

logger = logging.getLogger(__name__)


def publish_parquet_feature(
    df: pd.DataFrame,
    target_uri: str,
    s3_client: Any = None,
) -> str:
    """Publish a feature DataFrame to local file system or S3 based on target URI.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to export.
    target_uri : str
        Local file path or s3:// URI.
    s3_client : Any
        Optional boto3 S3 client (injected for testing).

    Returns
    -------
    str
        Resolved target URI where the file was written.
    """
    if target_uri.startswith("s3://"):
        import boto3

        bucket_and_key = target_uri[5:]
        bucket, key = bucket_and_key.split("/", 1)
        client = s3_client or boto3.client("s3", region_name=settings.AWS_REGION)

        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        buf.seek(0)
        client.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
        logger.info("Published feature parquet to S3: %s", target_uri)
        return target_uri

    path = Path(target_uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    logger.info("Published feature parquet to local path: %s", target_uri)
    return str(path)
