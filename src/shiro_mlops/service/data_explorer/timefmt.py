"""RFC 3339 timestamps labelled as Asia/Taipei with an explicit +08:00 offset."""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from shiro_mlops.core.storage_time import TAIWAN, to_storage_time


def now_taiwan() -> datetime:
    """Return the current Taiwan-local naive timestamp."""
    return datetime.now(TAIWAN).replace(tzinfo=None)


def parse_api_time(value: datetime | str) -> datetime:
    """Read a timestamp this service produced as Taiwan local time; request input goes
    through ``parse_request_time``."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Timestamp is required")
    if timestamp.tzinfo is None:
        return timestamp.to_pydatetime()
    return timestamp.tz_convert(TAIWAN).tz_localize(None).to_pydatetime()


# 請求時間只接受 RFC 3339 date-time：日期、T、時分（秒與小數可省略）與可省略的 offset。
_REQUEST_TIME = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?([Zz]|[+-]\d{2}:\d{2})?",
    re.ASCII,
)
EARLIEST_REQUEST_TIME = datetime(1970, 1, 1)
REQUEST_TIME_END = datetime(2200, 1, 1)


def parse_request_time(value: datetime | str) -> datetime:
    """Parse a timestamp a client sent as Taiwan local time; no offset means Taiwan time.

    Raises ``ValueError`` for anything but an RFC 3339 date-time inside
    ``[EARLIEST_REQUEST_TIME, REQUEST_TIME_END)``.
    """
    # WHY-NOT parse_request_time: pandas is not asked to guess. It reads "now", "2026" or a
    # bare "12:00" as times, and reads the space a "+08:00" turns into when a client forgets
    # to URL-encode it as a time-of-day, so the request silently queried a different window.
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and _REQUEST_TIME.fullmatch(value):
        parsed = datetime.fromisoformat(value.upper())
    else:
        raise ValueError(f"Not an RFC 3339 timestamp: {value!r}")
    if parsed.tzinfo is not None:
        try:
            parsed = parsed.astimezone(TAIWAN).replace(tzinfo=None)
        except OverflowError as exc:
            raise ValueError(_OUT_OF_RANGE) from exc
    # The range keeps every later conversion (UTC, pandas nanoseconds) inside its bounds.
    if not EARLIEST_REQUEST_TIME <= parsed < REQUEST_TIME_END:
        raise ValueError(_OUT_OF_RANGE)
    return parsed


_OUT_OF_RANGE = (
    f"Timestamp must be between {EARLIEST_REQUEST_TIME.year} and {REQUEST_TIME_END.year - 1}"
)


def parse_request_storage_time(value: datetime | str) -> datetime:
    """Parse a timestamp a client sent and convert it to its stored instant."""
    return to_storage_time(parse_request_time(value))


def format_taiwan_time(value: datetime | str, *, timespec: str = "seconds") -> str:
    """Format a Taiwan-local naive timestamp as RFC 3339 with +08:00."""
    parsed = parse_api_time(value)
    return parsed.replace(tzinfo=TAIWAN).isoformat(timespec=timespec)
