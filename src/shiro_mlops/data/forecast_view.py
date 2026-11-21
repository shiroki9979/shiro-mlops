"""The Forecast View's two public JSON documents, projected field by field (ADR-0015 §2.4).

Each document names every field it publishes, so nothing reaches the public
page by being added upstream: run status, load anchor, weather values, weather
source and model version stay local. Times carry the ``+08:00`` offset because
the viewer's browser may sit in any time zone; the inputs are Taiwan-local
naive datetimes or the ISO strings the track record artifact stores.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.issued_forecast import IssuedForecast

# 預報檢視以 /published/ 讀取這兩個固定檔名；變更時須同步 scripts/smoke_nginx.py、
# tests/fixtures/published/ 與 docs/reference/data-contracts.md 第 6 節。
LATEST_ISSUED_FORECAST_FILE = "latest_issued_forecast.json"
FORECAST_TRACK_RECORD_FILE = "forecast_track_record.json"

_TAIWAN = ZoneInfo(TAIWAN_TZ)


def latest_issued_forecast_document(forecast: IssuedForecast | None) -> dict[str, Any]:
    """The issue time and the steps whose target hour is after it; empty before any issue."""
    if forecast is None:
        return {"issued_at": None, "steps": []}
    return {
        "issued_at": _with_offset(forecast.issued_at),
        "steps": [
            {
                "target_hour": _with_offset(step.target_hour),
                "predicted_load_mw": step.predicted_load_mw,
            }
            for step in forecast.steps
            if step.target_hour > forecast.issued_at
        ],
    }


def forecast_track_record_document(record: Mapping[str, Any]) -> dict[str, Any]:
    """The ADR-0013 §2.3 public fields of a stored ``forecast_track_record`` artifact."""
    metrics = record["metrics"]
    return {
        "cutoff": _with_offset(record["cutoff"]),
        "accumulated_days": record["accumulated_days"],
        "metrics": None if metrics is None else _metrics_document(metrics),
    }


def encode_document(document: Mapping[str, Any]) -> bytes:
    """UTF-8 JSON; NaN or infinity fail here rather than reach the browser as invalid JSON."""
    return json.dumps(document, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _metrics_document(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_time_curve": [_accuracy_document(cell) for cell in metrics["lead_time_curve"]],
        "lead_24": _accuracy_document(metrics["lead_24"]),
        "lead_24_series": [
            {
                "target_hour": _with_offset(point["target_hour"]),
                "actual_load_mw": point["actual_load_mw"],
                "predicted_load_mw": point["predicted_load_mw"],
            }
            for point in metrics["lead_24_series"]
        ],
    }


def _accuracy_document(cell: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_time_hours": cell["lead_time_hours"],
        "mape": cell["mape"],
        "mae": cell["mae"],
    }


def _with_offset(moment: datetime | str) -> str:
    """A Taiwan-local naive time as ISO 8601 with the ``+08:00`` offset."""
    local = datetime.fromisoformat(moment) if isinstance(moment, str) else moment
    return local.replace(tzinfo=_TAIWAN).isoformat()
