"""Row mapping helpers shared by Data Explorer readers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from shiro_mlops.core.storage_time import from_storage_time_or_none
from shiro_mlops.data.repository_utils import deserialize_raw_payload
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time

# SYNC(frontend/apps/engineering-console/src/components/data-explorer/plot-series.ts): MW_PER_WAN_KW.
WAN_KW_TO_MW = 10.0


def optional_time(value: object) -> str | None:
    taiwan = from_storage_time_or_none(value)
    return None if taiwan is None else format_taiwan_time(taiwan)


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
    if not isinstance(parsed, list):
        raise ValueError("Identifier list must be a JSON array")
    return parsed


# SYNC(frontend/apps/engineering-console/src/components/data-explorer/explorer-filter-field.tsx): TRUTHY_VALUES.
def is_truthy(value: object) -> bool:
    return str(value).lower() in {"1", "true", "yes"}
