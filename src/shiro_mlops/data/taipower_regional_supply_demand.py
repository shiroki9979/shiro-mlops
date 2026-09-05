"""Parse and fetch Taipower regional supply-demand snapshots."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from shiro_mlops.data.taipower_supply_demand import (
    floor_to_ten_minutes,
    resolve_manual_observed_at,
)

DEFAULT_REGIONAL_SUPPLY_DEMAND_URL = (
    "https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv"
)

# 北中南東為台電區域慣用順序，同時作為合法區域集合。
REGIONAL_SUPPLY_DEMAND_REGIONS: tuple[str, ...] = ("北部", "中部", "南部", "東部")
_KNOWN_REGIONS = frozenset(REGIONAL_SUPPLY_DEMAND_REGIONS)
_SOURCE_TIME_FORMAT = "%Y%m%dT%H%M%S"


class RegionalSupplyDemandParseError(ValueError):
    """Raised when a regional supply-demand payload yields no valid snapshots."""


@dataclass(frozen=True)
class TaipowerRegionalSupplyDemandSnapshot:
    """Typed regional supply-demand snapshot ready for persistence."""

    observed_at: datetime
    region: str
    source_time: datetime
    generation_wan_kw: float | None
    load_wan_kw: float
    raw_payload: dict[str, Any]


def _strip_bom(value: str) -> str:
    return value.replace("\ufeff", "").strip()


def _parse_source_time(raw: str) -> datetime | None:
    cleaned = _strip_bom(raw)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, _SOURCE_TIME_FORMAT)
    except ValueError:
        return None


def _parse_optional_float(raw: str) -> float | None:
    cleaned = _strip_bom(raw)
    if cleaned == "":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_region(raw: str) -> str | None:
    region = _strip_bom(raw)
    if region in _KNOWN_REGIONS:
        return region
    return None


def _parse_row(
    row: dict[str, str],
    *,
    observed_at: datetime,
) -> TaipowerRegionalSupplyDemandSnapshot | None:
    source_time = _parse_source_time(row.get("時間", ""))
    region = _normalize_region(row.get("區域", ""))
    load_wan_kw = _parse_optional_float(row.get("用電(萬瓩)", ""))
    if source_time is None or region is None or load_wan_kw is None:
        return None

    generation_wan_kw = _parse_optional_float(row.get("發電(萬瓩)", ""))
    raw_payload = {key: _strip_bom(value) for key, value in row.items()}
    return TaipowerRegionalSupplyDemandSnapshot(
        observed_at=observed_at,
        region=region,
        source_time=source_time,
        generation_wan_kw=generation_wan_kw,
        load_wan_kw=load_wan_kw,
        raw_payload=raw_payload,
    )


def parse_regional_supply_demand_csv(
    csv_text: str,
    *,
    observed_at: datetime,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """Validate CSV rows into typed regional snapshots; skip incomplete rows."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise RegionalSupplyDemandParseError("No valid regional rows")

    reader.fieldnames = [_strip_bom(name) for name in reader.fieldnames]
    snapshots: list[TaipowerRegionalSupplyDemandSnapshot] = []
    for row in reader:
        normalized = {_strip_bom(key): value for key, value in row.items() if key is not None}
        snapshot = _parse_row(normalized, observed_at=observed_at)
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        raise RegionalSupplyDemandParseError("No valid regional rows")
    return snapshots


class TaipowerRegionalSupplyDemandClient:
    """HTTP client for the Taipower regional supply-demand open-data CSV."""

    def __init__(self, base_url: str = DEFAULT_REGIONAL_SUPPLY_DEMAND_URL) -> None:
        self.base_url = base_url

    def fetch_csv_text(self) -> str:
        """Fetch the raw CSV body from Taipower."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.base_url)
            response.raise_for_status()
            return response.text

    def fetch_snapshots(
        self, observed_at: datetime | None = None
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch, validate, and return typed regional snapshots for the observation slot."""
        slot = (
            floor_to_ten_minutes(observed_at)
            if observed_at is not None
            else resolve_manual_observed_at()
        )
        return parse_regional_supply_demand_csv(self.fetch_csv_text(), observed_at=slot)
