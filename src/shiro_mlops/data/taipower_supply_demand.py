"""Parse and fetch Taipower power supply-demand snapshots."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from shiro_mlops.core.datetime_utils import TAIWAN_TZ

DEFAULT_SUPPLY_DEMAND_URL = (
    "https://service.taipower.com.tw/data/opendata/apply/file/d006020/001.json"
)

_ROC_DATETIME_RE = re.compile(
    r"^(?P<year>\d{2,3})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})"
    r"(?:\([^)]*\))?"
    r"(?:(?P<hour>\d{1,2}):(?P<minute>\d{2}))?$"
)
_GREGORIAN_DATETIME_RE = re.compile(
    r"^(?P<year>\d{4})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})"
    r"[ T](?P<hour>\d{1,2}):(?P<minute>\d{2})$"
)


class SupplyDemandParseError(ValueError):
    """Raised when a supply-demand payload fails validation or parsing."""


@dataclass(frozen=True)
class TaipowerSupplyDemandSnapshot:
    """Typed Taipower power supply-demand snapshot ready for persistence."""

    observed_at: datetime
    curr_load_wan_kw: float
    curr_util_rate_pct: float
    source_publish_time: datetime | None
    fore_maxi_sply_capacity_wan_kw: float | None
    fore_peak_dema_load_wan_kw: float | None
    fore_peak_resv_capacity_wan_kw: float | None
    fore_peak_resv_rate_pct: float | None
    fore_peak_resv_indicator: str | None
    fore_peak_hour_range: str | None
    yday_date: date | None
    yday_maxi_sply_capacity_wan_kw: float | None
    yday_peak_dema_load_wan_kw: float | None
    yday_peak_resv_capacity_wan_kw: float | None
    yday_peak_resv_rate_pct: float | None
    yday_peak_resv_indicator: str | None
    real_hr_maxi_sply_capacity_wan_kw: float | None
    real_hr_peak_time: datetime | None
    raw_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            self.curr_load_wan_kw is None
            or math.isnan(self.curr_load_wan_kw)
            or math.isinf(self.curr_load_wan_kw)
        ):
            raise ValueError(f"Invalid curr_load_wan_kw: {self.curr_load_wan_kw!r}")
        if (
            self.curr_util_rate_pct is None
            or math.isnan(self.curr_util_rate_pct)
            or math.isinf(self.curr_util_rate_pct)
        ):
            raise ValueError(f"Invalid curr_util_rate_pct: {self.curr_util_rate_pct!r}")
        for field_name in (
            "fore_maxi_sply_capacity_wan_kw",
            "fore_peak_dema_load_wan_kw",
            "fore_peak_resv_capacity_wan_kw",
            "fore_peak_resv_rate_pct",
            "yday_maxi_sply_capacity_wan_kw",
            "yday_peak_dema_load_wan_kw",
            "yday_peak_resv_capacity_wan_kw",
            "yday_peak_resv_rate_pct",
            "real_hr_maxi_sply_capacity_wan_kw",
        ):
            val = getattr(self, field_name)
            if val is not None and (math.isnan(val) or math.isinf(val)):
                raise ValueError(f"Invalid {field_name}: {val!r}")


def floor_to_ten_minutes(moment: datetime) -> datetime:
    """Floor a timestamp to the start of its 10-minute observation slot."""
    return moment.replace(minute=(moment.minute // 10) * 10, second=0, microsecond=0)


def resolve_manual_observed_at(now: datetime | None = None) -> datetime:
    """Resolve the Taiwan-local observation slot used by manual materialize runs."""
    if now is None:
        now = datetime.now(tz=ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)
    return floor_to_ten_minutes(now)


def resolve_snapshot_observed_at(observed_at: str | datetime | None = None) -> datetime:
    """Resolve observation slot from a schedule tick, ISO string, or manual fallback."""
    if observed_at is None:
        return resolve_manual_observed_at()
    if isinstance(observed_at, str):
        return floor_to_ten_minutes(datetime.fromisoformat(observed_at))
    return floor_to_ten_minutes(observed_at)


def parse_roc_datetime(value: str) -> datetime:
    """Parse a ROC calendar timestamp used by Taipower open-data payloads."""
    cleaned = value.strip()
    match = _ROC_DATETIME_RE.fullmatch(cleaned)
    if match is None:
        raise SupplyDemandParseError(f"Unrecognized ROC datetime: {value!r}")

    year = int(match.group("year")) + 1911
    month = int(match.group("month"))
    day = int(match.group("day"))
    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)
    try:
        return datetime(year, month, day, hour, minute)
    except ValueError as error:
        raise SupplyDemandParseError(f"Invalid ROC datetime: {value!r}") from error


def _parse_optional_float(raw: Any, field: str) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError) as error:
        raise SupplyDemandParseError(f"Cannot parse optional field: {field}") from error
    if math.isnan(val) or math.isinf(val):
        raise SupplyDemandParseError(f"Cannot parse optional field: {field}")
    return val


def _require_float(merged: dict[str, Any], field: str) -> float:
    if field not in merged or merged[field] in (None, ""):
        raise SupplyDemandParseError(f"Missing required field: {field}")
    try:
        val = float(merged[field])
    except (TypeError, ValueError) as error:
        raise SupplyDemandParseError(f"Cannot parse required field: {field}") from error
    if math.isnan(val) or math.isinf(val):
        raise SupplyDemandParseError(f"Cannot parse required field: {field}")
    return val


def _optional_str(raw: Any, field: str = "optional_field") -> str | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list, tuple, set)):
        raise SupplyDemandParseError(
            f"Unexpected complex structure in optional string field: {field}"
        )
    cleaned = str(raw).strip()
    return cleaned or None


def _parse_gregorian_datetime(value: str) -> datetime:
    match = _GREGORIAN_DATETIME_RE.fullmatch(value.strip())
    if match is None:
        raise SupplyDemandParseError(f"Unrecognized Gregorian datetime: {value!r}")
    try:
        return datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
        )
    except ValueError as error:
        raise SupplyDemandParseError(f"Invalid Gregorian datetime: {value!r}") from error


def _optional_roc_datetime(raw: Any, field: str) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        return parse_roc_datetime(str(raw))
    except SupplyDemandParseError as error:
        raise SupplyDemandParseError(f"Cannot parse optional field: {field}") from error


def _optional_gregorian_datetime(raw: Any, field: str) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        return _parse_gregorian_datetime(str(raw))
    except SupplyDemandParseError as error:
        raise SupplyDemandParseError(f"Cannot parse optional field: {field}") from error


def _merge_records(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise SupplyDemandParseError("Payload missing records list")

    merged: dict[str, Any] = {}
    for record in records:
        if not isinstance(record, dict):
            raise SupplyDemandParseError("Each record must be an object")
        merged.update(record)
    return merged


def parse_supply_demand_payload(
    payload: dict[str, Any],
    *,
    observed_at: datetime,
) -> TaipowerSupplyDemandSnapshot:
    """Validate and convert a Taipower supply-demand JSON payload into a typed snapshot."""
    if not isinstance(payload, dict):
        raise SupplyDemandParseError("Payload must be a JSON object")

    merged = _merge_records(payload)
    curr_load_wan_kw = _require_float(merged, "curr_load")
    curr_util_rate_pct = _require_float(merged, "curr_util_rate")

    source_publish_time = _optional_roc_datetime(merged.get("publish_time"), "publish_time")
    yday_dt = _optional_roc_datetime(merged.get("yday_date"), "yday_date")
    yday_date = yday_dt.date() if yday_dt is not None else None
    real_hr_peak_time = _optional_gregorian_datetime(
        merged.get("real_hr_peak_time"), "real_hr_peak_time"
    )

    return TaipowerSupplyDemandSnapshot(
        observed_at=observed_at,
        curr_load_wan_kw=curr_load_wan_kw,
        curr_util_rate_pct=curr_util_rate_pct,
        source_publish_time=source_publish_time,
        fore_maxi_sply_capacity_wan_kw=_parse_optional_float(
            merged.get("fore_maxi_sply_capacity"), "fore_maxi_sply_capacity"
        ),
        fore_peak_dema_load_wan_kw=_parse_optional_float(
            merged.get("fore_peak_dema_load"), "fore_peak_dema_load"
        ),
        fore_peak_resv_capacity_wan_kw=_parse_optional_float(
            merged.get("fore_peak_resv_capacity"), "fore_peak_resv_capacity"
        ),
        fore_peak_resv_rate_pct=_parse_optional_float(
            merged.get("fore_peak_resv_rate"), "fore_peak_resv_rate"
        ),
        fore_peak_resv_indicator=_optional_str(
            merged.get("fore_peak_resv_indicator"), "fore_peak_resv_indicator"
        ),
        fore_peak_hour_range=_optional_str(
            merged.get("fore_peak_hour_range"), "fore_peak_hour_range"
        ),
        yday_date=yday_date,
        yday_maxi_sply_capacity_wan_kw=_parse_optional_float(
            merged.get("yday_maxi_sply_capacity"), "yday_maxi_sply_capacity"
        ),
        yday_peak_dema_load_wan_kw=_parse_optional_float(
            merged.get("yday_peak_dema_load"), "yday_peak_dema_load"
        ),
        yday_peak_resv_capacity_wan_kw=_parse_optional_float(
            merged.get("yday_peak_resv_capacity"), "yday_peak_resv_capacity"
        ),
        yday_peak_resv_rate_pct=_parse_optional_float(
            merged.get("yday_peak_resv_rate"), "yday_peak_resv_rate"
        ),
        yday_peak_resv_indicator=_optional_str(
            merged.get("yday_peak_resv_indicator"), "yday_peak_resv_indicator"
        ),
        real_hr_maxi_sply_capacity_wan_kw=_parse_optional_float(
            merged.get("real_hr_maxi_sply_capacity"), "real_hr_maxi_sply_capacity"
        ),
        real_hr_peak_time=real_hr_peak_time,
        raw_payload=payload,
    )


class TaipowerSupplyDemandClient:
    """HTTP client for the Taipower current supply-demand open-data endpoint."""

    def __init__(self, base_url: str = DEFAULT_SUPPLY_DEMAND_URL) -> None:
        self.base_url = base_url

    def fetch_payload(self) -> dict[str, Any]:
        """Fetch and decode the raw JSON payload from Taipower."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.base_url)
            response.raise_for_status()
            try:
                payload = response.json()
            except json.JSONDecodeError as error:
                raise SupplyDemandParseError("Response is not valid JSON") from error
        if not isinstance(payload, dict):
            raise SupplyDemandParseError("Response JSON must be an object")
        return payload

    def fetch_snapshot(self, observed_at: datetime | None = None) -> TaipowerSupplyDemandSnapshot:
        """Fetch, validate, and return a typed snapshot for the given observation slot."""
        slot = (
            floor_to_ten_minutes(observed_at)
            if observed_at is not None
            else resolve_manual_observed_at()
        )
        return parse_supply_demand_payload(self.fetch_payload(), observed_at=slot)
