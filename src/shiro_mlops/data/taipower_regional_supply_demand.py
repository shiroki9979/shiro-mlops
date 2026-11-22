"""Parse and fetch Taipower regional supply-demand snapshots."""

from __future__ import annotations

import csv
import io
import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

DEFAULT_REGIONAL_SUPPLY_DEMAND_URL = (
    "https://service.taipower.com.tw/data/opendata/apply/file/d006019/001.csv"
)

# SYNC(frontend/apps/engineering-console/src/components/data-explorer/catalog.ts): REGIONS，
# 同為台電慣用的北中南東順序；此 tuple 同時作為合法區域集合。
REGIONAL_SUPPLY_DEMAND_REGIONS: tuple[str, ...] = ("北部", "中部", "南部", "東部")
_KNOWN_REGIONS = frozenset(REGIONAL_SUPPLY_DEMAND_REGIONS)
_SOURCE_TIME_FORMAT = "%Y%m%dT%H%M%S"
_REQUIRED_HEADERS = frozenset({"時間", "區域", "用電(萬瓩)"})


class RegionalSupplyDemandParseError(ValueError):
    """Raised when a regional supply-demand payload yields no valid snapshots."""


class RegionalSupplyDemandFormatError(ValueError):
    """Raised when a regional supply-demand field contains a non-agreed format error."""


@dataclass(frozen=True)
class TaipowerRegionalSupplyDemandSnapshot:
    """Typed regional supply-demand snapshot ready for persistence."""

    observed_at: datetime
    region: str
    source_time: datetime
    generation_wan_kw: float | None
    load_wan_kw: float
    raw_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.region not in _KNOWN_REGIONS:
            raise ValueError(f"Invalid region: {self.region!r}")
        if self.load_wan_kw is None or math.isnan(self.load_wan_kw) or math.isinf(self.load_wan_kw):
            raise ValueError(f"Invalid load_wan_kw: {self.load_wan_kw!r}")
        if self.generation_wan_kw is not None and (
            math.isnan(self.generation_wan_kw) or math.isinf(self.generation_wan_kw)
        ):
            raise ValueError(f"Invalid generation_wan_kw: {self.generation_wan_kw!r}")


def _strip_bom(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip()


def _parse_source_time(raw: Any) -> datetime:
    cleaned = _strip_bom(raw)
    if not cleaned:
        raise ValueError("Missing source time ('時間')")
    try:
        return datetime.strptime(cleaned, _SOURCE_TIME_FORMAT)
    except ValueError as exc:
        raise RegionalSupplyDemandFormatError(f"Invalid source_time format: {raw!r}") from exc


def _normalize_region(raw: Any) -> str:
    region = _strip_bom(raw)
    if not region:
        raise ValueError("Missing region ('區域')")
    if region not in _KNOWN_REGIONS:
        raise RegionalSupplyDemandFormatError(f"Unknown region: {raw!r}")
    return region


def _parse_required_float(raw: Any, field_name: str) -> float:
    cleaned = _strip_bom(raw)
    if cleaned == "":
        raise ValueError(f"Missing required field: {field_name}")
    try:
        val = float(cleaned)
    except (ValueError, TypeError) as exc:
        raise RegionalSupplyDemandFormatError(
            f"Invalid numeric value for {field_name}: {raw!r}"
        ) from exc
    if math.isnan(val) or math.isinf(val):
        raise RegionalSupplyDemandFormatError(f"Non-finite numeric value for {field_name}: {raw!r}")
    return val


_AGREED_REGIONAL_MISSING = frozenset({"", "-", "n/a"})


def _parse_optional_float(raw: Any, field_name: str = "generation_wan_kw") -> float | None:
    cleaned = _strip_bom(raw)
    if cleaned.lower() in _AGREED_REGIONAL_MISSING:
        return None
    try:
        val = float(cleaned)
    except (ValueError, TypeError) as exc:
        raise RegionalSupplyDemandFormatError(
            f"Invalid numeric value for {field_name}: {raw!r}"
        ) from exc
    if math.isnan(val) or math.isinf(val):
        raise RegionalSupplyDemandFormatError(f"Non-finite numeric value for {field_name}: {raw!r}")
    return val


def _parse_row(
    row: dict[str, str],
    *,
    observed_at: datetime,
) -> TaipowerRegionalSupplyDemandSnapshot | None:
    try:
        source_time = _parse_source_time(row.get("時間", ""))
        region = _normalize_region(row.get("區域", ""))
        load_wan_kw = _parse_required_float(row.get("用電(萬瓩)", ""), "用電(萬瓩)")
        generation_wan_kw = _parse_optional_float(row.get("發電(萬瓩)", ""), "發電(萬瓩)")
    except RegionalSupplyDemandFormatError as exc:
        logger.warning("Skipping regional row due to format error: %s (row=%r)", exc, row)
        return None
    except ValueError as exc:
        logger.warning("Skipping regional row due to missing required field: %s (row=%r)", exc, row)
        return None

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

    cleaned_headers = [_strip_bom(name) for name in reader.fieldnames]
    reader.fieldnames = cleaned_headers
    if not _REQUIRED_HEADERS.issubset(set(cleaned_headers)):
        missing = _REQUIRED_HEADERS - set(cleaned_headers)
        raise RegionalSupplyDemandParseError(f"Missing required CSV headers: {sorted(missing)}")

    snapshots: list[TaipowerRegionalSupplyDemandSnapshot] = []
    for row in reader:
        normalized = {_strip_bom(key): value for key, value in row.items() if key is not None}
        snapshot = _parse_row(normalized, observed_at=observed_at)
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        raise RegionalSupplyDemandParseError("No valid regional rows")
    return snapshots


class RegionalSupplyDemandSource(Protocol):
    """Port that fetches the raw regional supply-demand CSV; parsing stays in this module."""

    def fetch_payload(self) -> str:
        """Return the CSV body exactly as the source published it."""
        ...


class TaipowerRegionalSupplyDemandClient:
    """HTTP adapter for the Taipower regional supply-demand open-data CSV."""

    def __init__(
        self,
        base_url: str = DEFAULT_REGIONAL_SUPPLY_DEMAND_URL,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self._transport = transport

    def fetch_payload(self) -> str:
        """Fetch the raw CSV body from Taipower."""
        with httpx.Client(timeout=10.0, transport=self._transport) as client:
            response = client.get(self.base_url)
            response.raise_for_status()
            return response.text
