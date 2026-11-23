"""Timezone utilities for standardizing Taiwan (Asia/Taipei) local timestamps."""

import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL, STORAGE_TIME_COL

TAIWAN_TZ = "Asia/Taipei"


def taiwan_now() -> pd.Timestamp:
    """The current instant as Taiwan-local naive time, matching persisted load time."""
    return pd.Timestamp.now(tz=TAIWAN_TZ).tz_localize(None)


def with_datetime_column(frame: pd.DataFrame) -> pd.DataFrame:
    """Persisted tables name their instant column ``time``; in-memory frames use ``datetime``."""
    if DATETIME_COL not in frame.columns and STORAGE_TIME_COL in frame.columns:
        return frame.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return frame


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

    if pd.api.types.is_datetime64_dtype(s.dtype):
        return s.astype("datetime64[ns]")

    def to_taiwan_local(value: object) -> pd.Timestamp:
        if pd.isna(value):
            return pd.NaT
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            return timestamp.tz_convert(TAIWAN_TZ).tz_localize(None)
        return timestamp

    return pd.to_datetime(s.map(to_taiwan_local), errors="coerce")
