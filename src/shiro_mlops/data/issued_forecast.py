"""An issued forecast: the immutable record of one scheduled dynamic horizon forecast (ADR-0013).

All times are Taiwan-local naive datetimes. The issue time is the schedule tick
and the forecast's ``as_of``; the load anchor is the latest actual load hour the
recursion started from. Steps are every hour the model produced, unfiltered.
``status`` is the forecast mode (預報運行狀態, GLOSSARY) and only ever holds a
``ForecastMode`` member, whether built by the issuing asset or read from the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from shiro_mlops.data.weather_resolution import ForecastMode

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
    status: ForecastMode
    model_sha256: str
    mlflow_model_version: str | None
    steps: tuple[IssuedForecastStep, ...]

    def __post_init__(self) -> None:
        try:
            status = ForecastMode(self.status)
        except ValueError as error:
            raise ValueError(
                f"Issued forecast status must be one of {[mode.value for mode in ForecastMode]}, "
                f"got {self.status!r}"
            ) from error
        object.__setattr__(self, "status", status)
        if not _SHA256_HEX.fullmatch(self.model_sha256):
            raise ValueError(
                f"model_sha256 must be a 64-character lowercase hex digest, "
                f"got {self.model_sha256!r}"
            )
