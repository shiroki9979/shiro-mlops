"""Parse and fetch Taipower unit net-generation snapshots."""

from __future__ import annotations

import json
import logging
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from shiro_mlops.data.taipower_supply_demand import (
    floor_to_ten_minutes,
    resolve_manual_observed_at,
)

logger = logging.getLogger(__name__)

DEFAULT_UNIT_GENERATION_URL = (
    "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SOURCE_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
_INVALID_IDENTITY_VALUES = frozenset({"", "-", "n/a", "none", "null"})
_AGREED_MISSING_NUMERIC = frozenset({"", "-", "n/a"})


class UnitGenerationParseError(ValueError):
    """Raised when a unit-generation payload yields no valid snapshots."""


class UnitGenerationFormatError(ValueError):
    """Raised when a unit-generation field contains a non-agreed format error."""


@dataclass(frozen=True)
class TaipowerUnitGenerationSnapshot:
    """Typed unit net-generation snapshot ready for persistence."""

    observed_at: datetime
    unit_type: str
    unit_name: str
    source_time: datetime
    capacity_mw: float | None
    net_generation_mw: float | None
    capacity_ratio_pct: float | None
    remark: str | None
    raw_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            not self.unit_type
            or not self.unit_type.strip()
            or self.unit_type.strip().lower() in _INVALID_IDENTITY_VALUES
        ):
            raise ValueError(f"Invalid unit_type: {self.unit_type!r}")
        if (
            not self.unit_name
            or not self.unit_name.strip()
            or self.unit_name.strip().lower() in _INVALID_IDENTITY_VALUES
        ):
            raise ValueError(f"Invalid unit_name: {self.unit_name!r}")
        if self.capacity_mw is not None and (
            math.isnan(self.capacity_mw) or math.isinf(self.capacity_mw)
        ):
            raise ValueError(f"Invalid capacity_mw: {self.capacity_mw!r}")
        if self.net_generation_mw is not None and (
            math.isnan(self.net_generation_mw) or math.isinf(self.net_generation_mw)
        ):
            raise ValueError(f"Invalid net_generation_mw: {self.net_generation_mw!r}")
        if self.capacity_ratio_pct is not None and (
            math.isnan(self.capacity_ratio_pct) or math.isinf(self.capacity_ratio_pct)
        ):
            raise ValueError(f"Invalid capacity_ratio_pct: {self.capacity_ratio_pct!r}")


def _strip_noise(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip()


def _normalize_unit_type(raw: Any) -> str | None:
    # 來源偶發夾帶 HTML 殘片（如 </b>），去除後才作為機組識別鍵的一部分。
    if raw is None:
        return None
    cleaned = _HTML_TAG_RE.sub("", _strip_noise(raw)).strip()
    if not cleaned or cleaned.lower() in _INVALID_IDENTITY_VALUES:
        return None
    return cleaned


def _normalize_unit_name(raw: Any) -> str | None:
    if raw is None:
        return None
    cleaned = _HTML_TAG_RE.sub("", _strip_noise(raw)).strip()
    if not cleaned or cleaned.lower() in _INVALID_IDENTITY_VALUES:
        return None
    return cleaned


def _parse_optional_mw(raw: Any, field_name: str = "mw") -> float | None:
    if raw is None:
        return None
    cleaned = _strip_noise(raw)
    if cleaned.lower() in _AGREED_MISSING_NUMERIC:
        return None
    try:
        val = float(cleaned)
    except (ValueError, TypeError) as exc:
        raise UnitGenerationFormatError(f"Invalid numeric value for {field_name}: {raw!r}") from exc
    if math.isnan(val) or math.isinf(val):
        raise UnitGenerationFormatError(f"Non-finite numeric value for {field_name}: {raw!r}")
    return val


def _parse_optional_ratio_pct(raw: Any, field_name: str = "ratio_pct") -> float | None:
    if raw is None:
        return None
    cleaned = _strip_noise(raw).rstrip("%").strip()
    if cleaned.lower() in _AGREED_MISSING_NUMERIC:
        return None
    try:
        val = float(cleaned)
    except (ValueError, TypeError) as exc:
        raise UnitGenerationFormatError(
            f"Invalid percentage value for {field_name}: {raw!r}"
        ) from exc
    if math.isnan(val) or math.isinf(val):
        raise UnitGenerationFormatError(f"Non-finite percentage value for {field_name}: {raw!r}")
    return val


def _parse_optional_remark(raw: Any) -> str | None:
    if raw is None:
        return None
    cleaned = _strip_noise(raw)
    if not cleaned or cleaned.lower() in _INVALID_IDENTITY_VALUES:
        return None
    return cleaned


def _parse_source_time(raw: Any) -> datetime | None:
    cleaned = _strip_noise(raw)
    if not cleaned:
        return None
    try:
        return datetime.strptime(cleaned, _SOURCE_DATETIME_FORMAT)
    except ValueError:
        return None


def _parse_row(
    row: dict[str, Any],
    *,
    observed_at: datetime,
    source_time: datetime,
    source_payload: dict[str, Any],
) -> TaipowerUnitGenerationSnapshot | None:
    unit_type = _normalize_unit_type(row.get("機組類型"))
    unit_name = _normalize_unit_name(row.get("機組名稱"))
    if unit_type is None or unit_name is None:
        logger.warning(
            "Skipping unit generation row due to missing or invalid unit identity: "
            "unit_type=%r, unit_name=%r, row=%r",
            row.get("機組類型"),
            row.get("機組名稱"),
            row,
        )
        return None

    try:
        capacity_mw = _parse_optional_mw(row.get("裝置容量(MW)"), "裝置容量(MW)")
        net_generation_mw = _parse_optional_mw(row.get("淨發電量(MW)"), "淨發電量(MW)")
        capacity_ratio_pct = _parse_optional_ratio_pct(
            row.get("淨發電量/裝置容量比(%)"), "淨發電量/裝置容量比(%)"
        )
    except UnitGenerationFormatError as exc:
        logger.warning(
            "Skipping unit generation row (%s, %s) due to format error: %s",
            unit_type,
            unit_name,
            exc,
        )
        return None

    return TaipowerUnitGenerationSnapshot(
        observed_at=observed_at,
        unit_type=unit_type,
        unit_name=unit_name,
        source_time=source_time,
        capacity_mw=capacity_mw,
        net_generation_mw=net_generation_mw,
        capacity_ratio_pct=capacity_ratio_pct,
        remark=_parse_optional_remark(row.get("備註")),
        raw_payload=deepcopy(source_payload),
    )


def parse_unit_generation_payload(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> list[TaipowerUnitGenerationSnapshot]:
    """Validate unit-generation JSON rows into typed snapshots; skip incomplete rows."""
    if not isinstance(payload, dict):
        raise UnitGenerationParseError("Payload must be a JSON object")

    source_datetime = _strip_noise(payload.get("DateTime", ""))
    source_time = _parse_source_time(source_datetime)
    if source_time is None:
        raise UnitGenerationParseError("Missing or invalid DateTime")

    rows = payload.get("aaData")
    if not isinstance(rows, list):
        raise UnitGenerationParseError("Payload missing aaData list")

    snapshots: list[TaipowerUnitGenerationSnapshot] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        snapshot = _parse_row(
            row,
            observed_at=observed_at,
            source_time=source_time,
            source_payload=payload,
        )
        if snapshot is not None:
            snapshots.append(snapshot)

    if not snapshots:
        raise UnitGenerationParseError("No valid unit rows")
    return snapshots


class TaipowerUnitGenerationClient:
    """HTTP client for the Taipower unit net-generation open-data endpoint."""

    def __init__(self, base_url: str = DEFAULT_UNIT_GENERATION_URL) -> None:
        self.base_url = base_url

    def fetch_payload(self) -> dict[str, Any]:
        """Fetch and decode the raw JSON payload from Taipower."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.base_url)
            response.raise_for_status()
            try:
                payload = json.loads(response.content.decode("utf-8-sig"))
            except json.JSONDecodeError as error:
                raise UnitGenerationParseError("Response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise UnitGenerationParseError("Response JSON must be an object")
        return payload

    def fetch_snapshots(
        self, observed_at: datetime | None = None
    ) -> list[TaipowerUnitGenerationSnapshot]:
        """Fetch, validate, and return typed unit snapshots for the observation slot."""
        slot = (
            floor_to_ten_minutes(observed_at)
            if observed_at is not None
            else resolve_manual_observed_at()
        )
        return parse_unit_generation_payload(self.fetch_payload(), observed_at=slot)
