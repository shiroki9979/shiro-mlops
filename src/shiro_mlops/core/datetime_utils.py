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

    non_nulls = s.dropna()
    if not non_nulls.empty:
        sample = str(non_nulls.iloc[0])
        has_tz = (
            ("+" in sample)
            or ("Z" in sample)
            or ("-" in sample and "T" in sample and len(sample) > 19)
        )
        if has_tz:
            try:
                parsed = pd.to_datetime(s, utc=True)
                return parsed.dt.tz_convert(TAIWAN_TZ).dt.tz_localize(None)
            except Exception:
                pass

    parsed = pd.to_datetime(s, errors="coerce")
    if getattr(parsed.dtype, "tz", None) is not None:
        return parsed.dt.tz_convert(TAIWAN_TZ).dt.tz_localize(None)
    return parsed
