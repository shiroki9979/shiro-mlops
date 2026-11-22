"""An issued forecast: the immutable record of one scheduled dynamic horizon forecast (ADR-0013).

All times are Taiwan-local naive datetimes. The issue time is the schedule tick
and the forecast's ``as_of``; the load anchor is the latest actual load hour the
recursion started from. Steps are every hour the model produced, unfiltered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

IssuedForecastStatus = Literal["normal", "degraded"]
ISSUED_FORECAST_STATUSES: tuple[str, ...] = get_args(IssuedForecastStatus)
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class IssuedForecastStep:
    """The predicted load for one target hour."""

    target_hour: datetime
    predicted_load_mw: float


@dataclass(frozen=True)
class IssuedForecast:
    """One issue time's forecast and the model version that produced it.

    ``model_sha256`` identifies the loaded model without MLflow;
    ``mlflow_model_version`` is only a note and may be ``None``.
    """

    issued_at: datetime
    load_anchor: datetime
    status: IssuedForecastStatus
    model_sha256: str
    mlflow_model_version: str | None
    steps: tuple[IssuedForecastStep, ...]

    def __post_init__(self) -> None:
        if self.status not in ISSUED_FORECAST_STATUSES:
            raise ValueError(
                f"Issued forecast status must be one of {ISSUED_FORECAST_STATUSES}, "
                f"got {self.status!r}"
            )
        if not _SHA256_HEX.fullmatch(self.model_sha256):
            raise ValueError(
                f"model_sha256 must be a 64-character lowercase hex digest, "
                f"got {self.model_sha256!r}"
            )
