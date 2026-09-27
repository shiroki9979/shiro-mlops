"""Minimum-accumulation gate over persisted hourly actual load (ADR-0008, SPEC §3.1).

The runner applies it before training, and schedules and the container smoke
check read it through the runner, so a skip reason, an asset failure, and a
smoke-check line always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from shiro_mlops.data.hourly_actual_load import HourlyLoadAccumulation

HOURS_PER_DAY = 24
LEGACY_LOAD_GUIDE = "docs/how-to/remove-legacy-d015046-load-rows.md"


class LoadAccumulationSource(Protocol):
    """Anything that can summarize persisted derived hourly load."""

    def summarize_hourly_load_accumulation(self, subject: str) -> HourlyLoadAccumulation: ...


@dataclass(frozen=True)
class TrainingLoadReadiness:
    """Whether persisted hourly actual load may be used to train a model."""

    valid_hours: int
    required_hours: int
    legacy_rows: int
    latest_hour: datetime | None

    @property
    def ready(self) -> bool:
        return self.legacy_rows == 0 and self.valid_hours >= self.required_hours

    @property
    def reason(self) -> str:
        if self.legacy_rows:
            return (
                f"raw_taipower_load contains {self.legacy_rows} legacy rows without a "
                f"derivation source; remove them before training (see {LEGACY_LOAD_GUIDE})."
            )
        if self.valid_hours < self.required_hours:
            missing = self.required_hours - self.valid_hours
            return (
                "Insufficient hourly actual load for training: "
                f"{self.valid_hours} valid hourly observations; {self.required_hours} required "
                f"(policies.min_training_hours). {_describe_remaining(missing)}"
            )
        return (
            f"Hourly actual load ready for training: {self.valid_hours} valid hourly "
            f"observations (>= {self.required_hours})."
        )


def check_training_load_readiness(
    repository: LoadAccumulationSource, required_hours: int, subject: str
) -> TrainingLoadReadiness:
    """Summarize persisted derived load against the minimum training accumulation."""
    accumulation = repository.summarize_hourly_load_accumulation(subject=subject)
    return TrainingLoadReadiness(
        valid_hours=accumulation.valid_hours,
        required_hours=required_hours,
        legacy_rows=accumulation.legacy_rows,
        latest_hour=accumulation.latest_hour,
    )


def _describe_remaining(missing_hours: int) -> str:
    unit = "hour" if missing_hours == 1 else "hours"
    days = missing_hours / HOURS_PER_DAY
    # 缺值小時不計入，故實際等待只會比連續累積更久。
    return f"{missing_hours} more {unit} needed (at least {days:.1f} days of accumulation)."
