"""Minimum-accumulation gate over persisted hourly actual load (ADR-0008, docs/reference/dagster-schedules.md).

The runner applies it before training, and schedules and the container smoke
check read it through the runner, so a skip reason, an asset failure, and a
smoke-check line always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto

from shiro_mlops.core.constants import HOURS_PER_DAY
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore

LEGACY_LOAD_GUIDE = "docs/how-to/remove-legacy-d015046-load-rows.md"


class AccumulationOutcome(Enum):
    """The gate's verdict on persisted hourly actual load; exactly one applies.

    ``BLOCKED_BY_LEGACY_ROWS``: ``source IS NULL`` rows remain, whatever the valid
    hourly observations add up to. ``BELOW_MINIMUM_ACCUMULATION``: valid hourly
    observations are fewer than the minimum accumulation. ``MINIMUM_ACCUMULATION_REACHED``:
    the only outcome that permits training.
    """

    BLOCKED_BY_LEGACY_ROWS = auto()
    BELOW_MINIMUM_ACCUMULATION = auto()
    MINIMUM_ACCUMULATION_REACHED = auto()


@dataclass(frozen=True)
class TrainingLoadReadiness:
    """Whether persisted hourly actual load may be used to train a model."""

    valid_hours: int
    required_hours: int
    legacy_rows: int
    latest_hour: datetime | None

    @property
    def outcome(self) -> AccumulationOutcome:
        if self.legacy_rows:
            return AccumulationOutcome.BLOCKED_BY_LEGACY_ROWS
        if self.valid_hours < self.required_hours:
            return AccumulationOutcome.BELOW_MINIMUM_ACCUMULATION
        return AccumulationOutcome.MINIMUM_ACCUMULATION_REACHED

    @property
    def ready(self) -> bool:
        return self.outcome is AccumulationOutcome.MINIMUM_ACCUMULATION_REACHED

    @property
    def reason(self) -> str:
        match self.outcome:
            case AccumulationOutcome.BLOCKED_BY_LEGACY_ROWS:
                return (
                    f"raw_taipower_load contains {self.legacy_rows} legacy rows without a "
                    f"derivation source; remove them before training (see {LEGACY_LOAD_GUIDE})."
                )
            case AccumulationOutcome.BELOW_MINIMUM_ACCUMULATION:
                missing = self.required_hours - self.valid_hours
                return (
                    "Insufficient hourly actual load for training: "
                    f"{self.valid_hours} valid hourly observations; {self.required_hours} "
                    f"required (policies.min_training_hours). {_describe_remaining(missing)}"
                )
            case AccumulationOutcome.MINIMUM_ACCUMULATION_REACHED:
                return (
                    f"Hourly actual load ready for training: {self.valid_hours} valid hourly "
                    f"observations (>= {self.required_hours})."
                )


def check_training_load_readiness(
    hourly_actual_load: HourlyActualLoadStore,
    required_hours: int,
    subject: str,
    *,
    as_of: datetime | None = None,
) -> TrainingLoadReadiness:
    """Summarize persisted derived load against the minimum training accumulation."""
    accumulation = hourly_actual_load.accumulation(as_of, subject=subject)
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
