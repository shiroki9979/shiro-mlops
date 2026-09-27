"""RFC 3339 timestamps labelled as Asia/Taipei with an explicit +08:00 offset."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from shiro_mlops.core.datetime_utils import TAIWAN_TZ, taiwan_local_to_utc
from shiro_mlops.data.repository_utils import utc_instant_to_taiwan

TAIWAN = ZoneInfo(TAIWAN_TZ)


def now_taiwan() -> datetime:
    """Return the current Taiwan-local naive timestamp."""
    return datetime.now(TAIWAN).replace(tzinfo=None)


def parse_api_time(value: datetime | str) -> datetime:
    """Parse an API timestamp as Taiwan local time."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Timestamp is required")
    if timestamp.tzinfo is None:
        return timestamp.to_pydatetime()
    return timestamp.tz_convert(TAIWAN).tz_localize(None).to_pydatetime()


def format_taiwan_time(value: datetime | str, *, timespec: str = "seconds") -> str:
    """Format a Taiwan-local naive timestamp as RFC 3339 with +08:00."""
    parsed = parse_api_time(value)
    return parsed.replace(tzinfo=TAIWAN).isoformat(timespec=timespec)


def format_utc_as_taiwan(value: object) -> str:
    """Format a UTC database timestamp as RFC 3339 with +08:00."""
    taiwan = utc_instant_to_taiwan(value)
    if taiwan is None:
        raise ValueError("Timestamp is required")
    return format_taiwan_time(taiwan)


def to_sql_utc(value: datetime | str) -> datetime:
    """Convert a Taiwan-local timestamp to the UTC instant used in SQL filters."""
    converted = taiwan_local_to_utc(pd.Series([parse_api_time(value)])).iloc[0]
    return pd.Timestamp(converted).to_pydatetime()


def to_naive_sql_utc(value: datetime | str) -> datetime:
    """回傳無時區 UTC，對齊 snapshot 入庫格式，避免 SQLite 把 aware/naive 當字串比較。"""
    instant = to_sql_utc(value)
    return instant.replace(tzinfo=None) if instant.tzinfo is not None else instant
