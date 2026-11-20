"""The forecast track record: issued forecasts paired with valid hourly observations (ADR-0013 §2.2–2.3).

All times are Taiwan-local naive datetimes. The window covers target hours in
``[cutoff - 720h, cutoff)`` whatever their issue time, so a step issued before
the window still counts when its target hour falls inside.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

TRACK_RECORD_WINDOW = timedelta(hours=720)
_ONE_HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class TrackRecordPair:
    """One issued step whose target hour has a valid hourly observation."""

    issued_at: datetime
    target_hour: datetime
    predicted_load_mw: float
    actual_load_mw: float

    @property
    def lead_time_hours(self) -> int:
        """Hours from the issue time to the target hour, a partial hour counting as one."""
        return math.ceil((self.target_hour - self.issued_at) / _ONE_HOUR)


@dataclass(frozen=True)
class ForecastTrackRecord:
    """What one compilation publishes; never run status, weather source, model version or gaps.

    ``accumulated_days`` counts the distinct Taiwan dates of target hours with
    at least one pair in the window, so it never exceeds 31.
    """

    cutoff: datetime
    accumulated_days: int


def track_record_cutoff(moment: datetime) -> datetime:
    """The cutoff of a compilation run at ``moment``: that moment floored to the hour."""
    return moment.replace(minute=0, second=0, microsecond=0)


def track_record_window(cutoff: datetime) -> tuple[datetime, datetime]:
    """Target hours ``[start, end)`` the track record covers: the 720 hours before the cutoff."""
    return cutoff - TRACK_RECORD_WINDOW, cutoff


def compile_forecast_track_record(
    cutoff: datetime, pairs: Iterable[TrackRecordPair]
) -> ForecastTrackRecord:
    """Summarize the pairs fetched for ``track_record_window(cutoff)``."""
    target_dates = {pair.target_hour.date() for pair in pairs}
    return ForecastTrackRecord(cutoff=cutoff, accumulated_days=len(target_dates))
