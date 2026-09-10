"""Row mapping helpers shared by Data Explorer readers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from shiro_mlops.data.repository_utils import deserialize_raw_payload, utc_instant_to_taiwan
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time

WAN_KW_TO_MW = 10.0


def to_taiwan(value: object) -> datetime:
    converted = utc_instant_to_taiwan(value)
    if converted is None:
        raise ValueError("Timestamp is required")
    return converted


def optional_time(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    return format_taiwan_time(to_taiwan(value))


def to_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def to_mw(value: object) -> float | None:
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
    if isinstance(parsed, list):
        return parsed
    return list(parsed)


def floor_ten_minutes(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 10) * 10, second=0, microsecond=0)


def is_truthy(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes"}
