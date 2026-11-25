"""Row mapping helpers shared by Data Explorer readers."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any, SupportsFloat

from shiro_mlops.core.storage_time import (
    StoredInstant,
    from_storage_time,
    from_storage_time_or_none,
)
from shiro_mlops.data.repository_utils import deserialize_raw_payload
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time

# SYNC(frontend/apps/engineering-console/src/components/data-explorer/plot-series.ts): MW_PER_WAN_KW.
WAN_KW_TO_MW = 10.0


def row_time(row: Mapping[str, Any], column: str) -> datetime:
    """Read a row's NOT NULL stored instant in ``column`` as Taiwan-local naive."""
    return from_storage_time(row[column], column=column)


def format_row_time(row: Mapping[str, Any], column: str, *, timespec: str = "seconds") -> str:
    """Format a row's NOT NULL stored instant in ``column`` as RFC 3339 with +08:00."""
    return format_taiwan_time(row_time(row, column), timespec=timespec)


def optional_time(value: StoredInstant) -> str | None:
    taiwan = from_storage_time_or_none(value)
    return None if taiwan is None else format_taiwan_time(taiwan)


def to_float(value: SupportsFloat | str | None) -> float | None:
    """A stored number as ``float``; NULL and NaN give ``None``."""
    if value is None:
        return None
    number = float(value)
    return None if math.isnan(number) else number


def to_mw(value: SupportsFloat | str | None) -> float | None:
    wan_kw = to_float(value)
    if wan_kw is None:
        return None
    return wan_kw * WAN_KW_TO_MW


def json_list(value: object) -> list[Any]:
    if value in (None, ""):
        return []
    parsed = deserialize_raw_payload(value)
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValueError("Identifier list must be a JSON array")
    return parsed


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/explorer-query-state.ts): TRUTHY_VALUES.
def is_truthy(value: object) -> bool:
    """True for every spelling FastAPI's bool validation reads as true on a series endpoint."""
    return str(value).lower() in {"1", "on", "t", "true", "y", "yes"}
