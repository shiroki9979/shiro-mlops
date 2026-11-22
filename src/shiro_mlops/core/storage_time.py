"""Storage time (儲存時刻): the single boundary between Taiwan-local instants and stored instants.

Every store writes and binds instants as timezone-aware UTC, so TimescaleDB ``timestamptz``
never depends on the session TimeZone and SQLite holds one string form. Reads hand back
Taiwan-local, timezone-naive instants.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from shiro_mlops.core.datetime_utils import TAIWAN_TZ

TAIWAN = ZoneInfo(TAIWAN_TZ)


def to_storage_time(value: datetime | pd.Timestamp) -> datetime:
    """Convert a Taiwan-local instant to the aware UTC datetime that stores write and bind.

    A naive value is Taiwan local time; an aware value keeps the instant it states.
    """
    if _is_null(value):
        raise ValueError("A Taiwan-local instant is required")
    instant = value.to_pydatetime() if isinstance(value, pd.Timestamp) else value
    local = instant if instant.tzinfo is not None else instant.replace(tzinfo=TAIWAN)
    return local.astimezone(UTC)


def to_storage_time_or_none(value: datetime | pd.Timestamp | None) -> datetime | None:
    """Convert a nullable column's Taiwan-local instant; ``None`` and ``NaT`` give ``None``."""
    return None if _is_null(value) else to_storage_time(value)


def from_storage_time(value: object, *, column: str) -> datetime:
    """Read a NOT NULL stored instant back as a Taiwan-local, timezone-naive datetime.

    Accepts the strings SQLite returns, with or without fractional seconds and ``+00:00``,
    and the aware values TimescaleDB returns; a naive value is UTC. A NULL means the
    storage is corrupt, so it raises instead of letting a caller substitute a query bound.
    """
    if _is_null(value):
        raise ValueError(f"Stored instant {column} is NULL in a NOT NULL time column")
    return _taiwan_local(value)


def from_storage_time_or_none(value: object) -> datetime | None:
    """Read a nullable column's stored instant as Taiwan-local naive, NULL as ``None``."""
    return None if _is_null(value) else _taiwan_local(value)


def from_storage_time_series(stored: pd.Series) -> pd.Series:
    """Read a NOT NULL stored time column of a frame as Taiwan-local naive ``datetime64``.

    Accepts the same stored forms as :func:`from_storage_time`, mixed within one column.
    """
    if stored.isna().any():
        raise ValueError(f"Stored time column {stored.name} holds NULL in a NOT NULL column")
    utc = pd.to_datetime(stored, utc=True, format="ISO8601")
    return utc.dt.tz_convert(TAIWAN).dt.tz_localize(None)


@dataclass(frozen=True)
class WindowCondition:
    """A SQL condition fragment and the storage-form parameters it binds."""

    sql: str
    params: dict[str, datetime]


def half_open_window(
    column: str, start: datetime, end: datetime, *, param: str | None = None
) -> WindowCondition:
    """Select stored instants in the Taiwan-local half-open window ``[start, end)``.

    Parameters are named ``<param>_start`` and ``<param>_end``; ``param`` defaults to the
    column name without its table qualifier, so a self-join passes distinct names.
    """
    stored_start, stored_end = to_storage_time(start), to_storage_time(end)
    if stored_end < stored_start:
        raise ValueError(f"Window end {end} is before its start {start}")
    name = _param_name(column, param)
    return WindowCondition(
        sql=f"{column} >= :{name}_start AND {column} < :{name}_end",
        params={f"{name}_start": stored_start, f"{name}_end": stored_end},
    )


def window_before(column: str, end: datetime, *, param: str | None = None) -> WindowCondition:
    """Select stored instants before the Taiwan-local ``end``: ``[start, end)`` with no start.

    The end parameter is named as in :func:`half_open_window`.
    """
    name = _param_name(column, param)
    return WindowCondition(
        sql=f"{column} < :{name}_end", params={f"{name}_end": to_storage_time(end)}
    )


def _param_name(column: str, param: str | None) -> str:
    return param or column.rsplit(".", 1)[-1]


def register_sqlite_datetime_adapter() -> None:
    """Bind datetimes to SQLite explicitly, replacing Python's deprecated default adapter.

    The text form is unchanged: ``YYYY-MM-DD HH:MM:SS[.ffffff][+00:00]``, microseconds only
    when non-zero and the offset only when the value is aware. The registration is
    process-wide and idempotent.
    """
    sqlite3.register_adapter(datetime, _sqlite_datetime_text)


def _sqlite_datetime_text(value: datetime) -> str:
    return value.isoformat(" ")


def _taiwan_local(value: object) -> datetime:
    stored = pd.Timestamp(value)
    utc = stored.tz_localize(UTC) if stored.tzinfo is None else stored.tz_convert(UTC)
    return utc.tz_convert(TAIWAN).tz_localize(None).to_pydatetime()


def _is_null(value: object) -> bool:
    return value is None or bool(pd.isna(value))
