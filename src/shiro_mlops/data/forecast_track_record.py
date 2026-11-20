"""The forecast track record: issued forecasts paired with valid hourly observations (ADR-0013 §2.2–2.3).

All times are Taiwan-local naive datetimes. The window covers target hours in
``[cutoff - 720h, cutoff)`` whatever their issue time, so a step issued before
the window still counts when its target hour falls inside.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from shiro_mlops.core.constants import MAX_HORIZON_HOURS

TRACK_RECORD_WINDOW = timedelta(hours=720)
MIN_ACCUMULATED_DAYS = 7
CURVE_LEAD_TIMES = range(1, MAX_HORIZON_HOURS + 1)
HEADLINE_LEAD_TIME_HOURS = 24
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
class LeadTimeAccuracy:
    """MAPE (%) and MAE (MW) over every pair in the window at one lead time.

    Both are ``None`` when the lead time has no pair; there is no minimum pair count.
    """

    lead_time_hours: int
    mape: float | None
    mae: float | None


@dataclass(frozen=True)
class SeriesPoint:
    """One target hour's actual load against its lead 24 issued forecast."""

    target_hour: datetime
    actual_load_mw: float
    predicted_load_mw: float


@dataclass(frozen=True)
class TrackRecordMetrics:
    """The accuracy published once the window has accumulated enough days.

    ``lead_time_curve`` holds one cell per lead time 1–168 in order;
    ``lead_24`` is its 24th cell, the headline numbers. ``lead_24_series``
    has one point per target hour with a lead 24 pair, in target hour order;
    hours without one are left out.
    """

    lead_time_curve: tuple[LeadTimeAccuracy, ...]
    lead_24: LeadTimeAccuracy
    lead_24_series: tuple[SeriesPoint, ...]


@dataclass(frozen=True)
class ForecastTrackRecord:
    """What one compilation publishes; never run status, weather source, model version or gaps.

    ``accumulated_days`` counts the distinct Taiwan dates of target hours with
    at least one pair in the window, so it never exceeds 31. Below
    ``MIN_ACCUMULATED_DAYS`` the record carries no ``metrics`` at all.
    """

    cutoff: datetime
    accumulated_days: int
    metrics: TrackRecordMetrics | None


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
    pairs = tuple(pairs)
    accumulated_days = len({pair.target_hour.date() for pair in pairs})
    metrics = _metrics(pairs) if accumulated_days >= MIN_ACCUMULATED_DAYS else None
    return ForecastTrackRecord(cutoff=cutoff, accumulated_days=accumulated_days, metrics=metrics)


def _metrics(pairs: Sequence[TrackRecordPair]) -> TrackRecordMetrics:
    by_lead_time: dict[int, list[TrackRecordPair]] = defaultdict(list)
    for pair in pairs:
        by_lead_time[pair.lead_time_hours].append(pair)
    curve = tuple(_accuracy(lead, by_lead_time[lead]) for lead in CURVE_LEAD_TIMES)
    return TrackRecordMetrics(
        lead_time_curve=curve,
        lead_24=curve[CURVE_LEAD_TIMES.index(HEADLINE_LEAD_TIME_HOURS)],
        lead_24_series=_series(by_lead_time[HEADLINE_LEAD_TIME_HOURS]),
    )


def _series(pairs: Sequence[TrackRecordPair]) -> tuple[SeriesPoint, ...]:
    """One point per target hour; the latest issue wins if two issues share a lead time."""
    latest: dict[datetime, TrackRecordPair] = {}
    for pair in sorted(pairs, key=lambda pair: pair.issued_at):
        latest[pair.target_hour] = pair
    return tuple(
        SeriesPoint(
            target_hour=pair.target_hour,
            actual_load_mw=pair.actual_load_mw,
            predicted_load_mw=pair.predicted_load_mw,
        )
        for _, pair in sorted(latest.items())
    )


def _accuracy(lead_time_hours: int, pairs: Sequence[TrackRecordPair]) -> LeadTimeAccuracy:
    """Pool every pair at one lead time; no averaging per day or per issue time first."""
    if not pairs:
        return LeadTimeAccuracy(lead_time_hours=lead_time_hours, mape=None, mae=None)
    errors = [abs(pair.predicted_load_mw - pair.actual_load_mw) for pair in pairs]
    percentages = [error / pair.actual_load_mw for error, pair in zip(errors, pairs, strict=True)]
    return LeadTimeAccuracy(
        lead_time_hours=lead_time_hours,
        mape=sum(percentages) / len(pairs) * 100,
        mae=sum(errors) / len(pairs),
    )
