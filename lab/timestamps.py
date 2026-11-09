"""Timestamp normalization shared by lab snapshot and backtest tools."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from shiro_mlops.core.datetime_utils import TAIWAN_TZ


def normalize_taiwan_timestamp(value: datetime | pd.Timestamp | str) -> pd.Timestamp:
    """Normalize a timestamp input to a timezone-naive Asia/Taipei pd.Timestamp."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(TAIWAN_TZ).tz_localize(None)
    return timestamp
