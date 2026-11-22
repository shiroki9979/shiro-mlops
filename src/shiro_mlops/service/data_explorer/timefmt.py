"""RFC 3339 timestamps labelled as Asia/Taipei with an explicit +08:00 offset."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from shiro_mlops.core.storage_time import TAIWAN, to_storage_time


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


def parse_api_storage_time(value: datetime | str) -> datetime:
    """Parse an API timestamp as Taiwan local time and convert it to its stored instant."""
    return to_storage_time(parse_api_time(value))


def format_taiwan_time(value: datetime | str, *, timespec: str = "seconds") -> str:
    """Format a Taiwan-local naive timestamp as RFC 3339 with +08:00."""
    parsed = parse_api_time(value)
    return parsed.replace(tzinfo=TAIWAN).isoformat(timespec=timespec)
