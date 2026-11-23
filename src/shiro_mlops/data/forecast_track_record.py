"""The forecast track record: issued forecasts paired with valid hourly observations (ADR-0013 §2.2–2.3).

All times are Taiwan-local naive datetimes. The window covers target hours in
``[cutoff - 720h, cutoff)`` whatever their issue time, so a step issued before
the window still counts when its target hour falls inside.

``ForecastTrackRecordStore`` reads the database and decides which issued steps
count and which hourly load row each pairs with; compiling the pairs into the
published record is pure.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import MAX_HORIZON_HOURS, NATIONWIDE_SUBJECT
from shiro_mlops.core.storage_time import from_storage_time, half_open_window, to_storage_time
from shiro_mlops.data.hourly_actual_load_store import REGIONAL_SNAPSHOT_SUM_SOURCE

TRACK_RECORD_WINDOW = timedelta(hours=720)
TRACK_RECORD_MIN_DAYS = 7
CURVE_LEAD_TIMES = range(1, MAX_HORIZON_HOURS + 1)
HEADLINE_LEAD_TIME_HOURS = 24
_ONE_HOUR = timedelta(hours=1)
_MAX_HORIZON = timedelta(hours=MAX_HORIZON_HOURS)


@dataclass(frozen=True)
class TrackRecordWindow:
    """The target hours ``[start, end)`` one compilation covers."""

    start: datetime
    end: datetime


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
    ``TRACK_RECORD_MIN_DAYS`` the record carries no ``metrics`` at all.
    """

    cutoff: datetime
    accumulated_days: int
    metrics: TrackRecordMetrics | None


class ForecastTrackRecordStore:
    """Reads the issued steps the track record counts, paired with their hourly load."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def fetch_pairs(self, window: TrackRecordWindow) -> tuple[TrackRecordPair, ...]:
        """Pair issued steps targeting the window with valid hourly observations.

        Only steps whose target hour is after their issue time count, and only
        target hours with a nationwide ``regional_snapshot_sum`` load row. One SQL
        join returns only the paired rows. Pairs are ordered by target hour, then
        issue time.

        Both hypertables are bounded on their partition column: a step lands at
        most 168 hours after its load anchor, which precedes its issue time, so a
        step targeting the window was issued after the window start minus 168 hours.
        """
        target_hour = half_open_window("step.target_hour", window.start, window.end)
        load_time = half_open_window("actual.time", window.start, window.end, param="load_time")
        params = {
            **target_hour.params,
            **load_time.params,
            "earliest_issued_at": to_storage_time(window.start - _MAX_HORIZON),
            "latest_issued_at": to_storage_time(window.end),
            "subject": NATIONWIDE_SUBJECT,
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
        }
        query = text(
            f"""
            SELECT step.issued_at, step.target_hour, step.predicted_load_mw, actual.load_mw
            FROM issued_forecast_step AS step
            JOIN raw_taipower_load AS actual ON actual.time = step.target_hour
            WHERE step.issued_at > :earliest_issued_at
              AND step.issued_at < :latest_issued_at
              AND {target_hour.sql}
              AND step.target_hour > step.issued_at
              AND {load_time.sql}
              AND actual.subject = :subject
              AND actual.source = :source
            ORDER BY step.target_hour, step.issued_at
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()
        return tuple(
            TrackRecordPair(
                issued_at=from_storage_time(row["issued_at"], column="issued_at"),
                target_hour=from_storage_time(row["target_hour"], column="target_hour"),
                predicted_load_mw=float(row["predicted_load_mw"]),
                actual_load_mw=float(row["load_mw"]),
            )
            for row in rows
        )


def track_record_cutoff(moment: datetime) -> datetime:
    """The cutoff of a compilation run at ``moment``: that moment floored to the hour."""
    return moment.replace(minute=0, second=0, microsecond=0)


def track_record_window(cutoff: datetime) -> TrackRecordWindow:
    """The 720 target hours before the cutoff."""
    return TrackRecordWindow(start=cutoff - TRACK_RECORD_WINDOW, end=cutoff)


def compile_forecast_track_record(
    cutoff: datetime, pairs: Iterable[TrackRecordPair]
) -> ForecastTrackRecord:
    """Summarize the pairs fetched for ``track_record_window(cutoff)``."""
    pairs = tuple(pairs)
    accumulated_days = len({pair.target_hour.date() for pair in pairs})
    metrics = _metrics(pairs) if accumulated_days >= TRACK_RECORD_MIN_DAYS else None
    return ForecastTrackRecord(cutoff=cutoff, accumulated_days=accumulated_days, metrics=metrics)


def count_headline_pairs(pairs: Iterable[TrackRecordPair]) -> int:
    """How many pairs sit at the headline lead time 24."""
    return sum(pair.lead_time_hours == HEADLINE_LEAD_TIME_HOURS for pair in pairs)


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
