"""Timezone utilities for standardizing Taiwan (Asia/Taipei) local timestamps."""

import pandas as pd

TAIWAN_TZ = "Asia/Taipei"


def standardize_taiwan_datetime(s: pd.Series) -> pd.Series:
    """Standardize timestamp Series to Taiwan local time (Asia/Taipei) as naive datetime64[ns].

    - If timestamps are already timezone-aware: convert to Asia/Taipei and remove tz offset.
    - If timestamps are timezone-naive: assume they already represent Taiwan local time.
    - If input contains ISO8601 strings with 'Z' or UTC offsets: parse as UTC, convert to Asia/Taipei, and drop tz.
    - Preserves null/NaN values safely.
    """
    if s.empty:
        return pd.to_datetime(s)

    if getattr(s.dtype, "tz", None) is not None:
        return s.dt.tz_convert(TAIWAN_TZ).dt.tz_localize(None)

    def to_taiwan_local(value: object) -> pd.Timestamp:
        if pd.isna(value):
            return pd.NaT
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            return timestamp.tz_convert(TAIWAN_TZ).tz_localize(None)
        return timestamp

    return pd.to_datetime(s.map(to_taiwan_local), errors="coerce")


def taiwan_local_to_utc(s: pd.Series) -> pd.Series:
    """Convert source timestamps to UTC for persistence and database filtering.

    Timezone-naive values represent Taiwan local time at the ingestion boundary;
    timezone-aware values retain their stated instant before conversion to UTC.
    """
    local_time = standardize_taiwan_datetime(s)
    return local_time.dt.tz_localize(TAIWAN_TZ).dt.tz_convert("UTC")


def utc_to_taiwan_datetime(s: pd.Series) -> pd.Series:
    """Convert UTC database timestamps to Taiwan-local, timezone-naive feature time."""
    return pd.to_datetime(s, utc=True).dt.tz_convert(TAIWAN_TZ).dt.tz_localize(None)
