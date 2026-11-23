"""Publish the Forecast View's JSON: always to the local directory, then to S3 when set (ADR-0015 §2.3).

Local Nginx serves the local directory under ``/published/``; CloudFront serves
the bucket's ``published/`` prefix under the same path. Every export overwrites
the same file names, and neither side keeps history.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from shiro_mlops.core.config import Settings

# 地端上傳用 IAM 使用者只能 PutObject 到此 prefix，CloudFront 的 /published/* behavior
# 也以無 origin path 的 origin 對應到它（docs/reference/forecast-view-hosting.md 第 1、2 節）。
PUBLISHED_S3_PREFIX = "published/"
JSON_CONTENT_TYPE = "application/json"


@dataclass(frozen=True)
class S3Destination:
    """The bucket the export uploads to, and the S3 client that writes it."""

    bucket: str
    client: Any


class ForecastViewPublisher:
    """Write each file to ``local_dir``; with an S3 destination, then upload the same bytes."""

    def __init__(self, local_dir: Path, s3: S3Destination | None = None) -> None:
        self.local_dir = local_dir
        self.s3 = s3

    @classmethod
    def from_settings(cls, settings: Settings) -> ForecastViewPublisher:
        """Upload only when a bucket is set; without one the export stays local."""
        if not settings.FORECAST_VIEW_S3_BUCKET:
            return cls(settings.published_dir)
        client = boto3.client(
            "s3",
            region_name=settings.AWS_DEFAULT_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY.get_secret_value() or None,
        )
        return cls(settings.published_dir, S3Destination(settings.FORECAST_VIEW_S3_BUCKET, client))

    @property
    def uploads_to_s3(self) -> bool:
        return self.s3 is not None

    def publish(self, files: Mapping[str, bytes]) -> None:
        """Write every file locally before uploading any, so an S3 failure leaves local current.

        The upload sets no ``Cache-Control``: CloudFront's behavior decides caching.
        """
        self.local_dir.mkdir(parents=True, exist_ok=True)
        for name, body in files.items():
            _replace_atomically(self.local_dir / name, body)
        if self.s3 is None:
            return
        for name, body in files.items():
            self.s3.client.put_object(
                Bucket=self.s3.bucket,
                Key=PUBLISHED_S3_PREFIX + name,
                Body=body,
                ContentType=JSON_CONTENT_TYPE,
            )


def _replace_atomically(path: Path, body: bytes) -> None:
    """Nginx serves the directory while the export runs; a rename never exposes half a file."""
    # WHY-NOT _replace_atomically: the temporary name is unique per call. With one fixed name,
    # two exports that overlap (a manual materialization during the scheduled run) write the
    # same file, and the slower one's rename fails because the faster one already moved it.
    # It is written with write_bytes, not tempfile, so it keeps the default mode Nginx can read.
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(body)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
