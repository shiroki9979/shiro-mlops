"""Forecast track record metrics: lead time curve, lead 24 metrics and series (ADR-0013 §2.3)."""

from datetime import datetime, timedelta

import pytest

from shiro_mlops.data.forecast_track_record import (
    TrackRecordPair,
    TrackRecordWindow,
    compile_forecast_track_record,
    count_headline_pairs,
    track_record_window,
)

CUTOFF = datetime(2026, 11, 20, 10, 0)


def _pair(target_hour: datetime, lead: int, predicted: float, actual: float) -> TrackRecordPair:
    """A pair issued at :15, so its lead time rounds up to ``lead`` hours."""
    return TrackRecordPair(
        issued_at=target_hour - timedelta(hours=lead) + timedelta(minutes=45),
        target_hour=target_hour,
        predicted_load_mw=predicted,
        actual_load_mw=actual,
    )


def _one_pair_per_day(days: int) -> list[TrackRecordPair]:
    """Lead 1 pairs at 09:00 on each of the ``days`` Taiwan dates before the cutoff."""
    return [
        _pair(datetime(2026, 11, 20, 9, 0) - timedelta(days=offset), 1, 30000.0, 25000.0)
        for offset in range(days)
    ]


def test_window_covers_the_720_target_hours_before_the_cutoff() -> None:
    assert track_record_window(CUTOFF) == TrackRecordWindow(
        start=datetime(2026, 10, 21, 10, 0), end=CUTOFF
    )


def test_headline_pairs_count_only_lead_24() -> None:
    target = datetime(2026, 11, 20, 9, 0)
    pairs = [
        _pair(target, 24, 30000.0, 25000.0),
        _pair(target - timedelta(hours=1), 24, 30000.0, 25000.0),
        _pair(target, 23, 30000.0, 25000.0),
        _pair(target, 25, 30000.0, 25000.0),
    ]

    assert count_headline_pairs(pairs) == 2


def test_six_accumulated_days_publish_no_metrics() -> None:
    record = compile_forecast_track_record(CUTOFF, _one_pair_per_day(6))

    assert record.accumulated_days == 6
    assert record.metrics is None


def test_seven_accumulated_days_publish_metrics() -> None:
    record = compile_forecast_track_record(CUTOFF, _one_pair_per_day(7))

    assert record.accumulated_days == 7
    assert record.metrics is not None


def _exact_filler(days: int = 7) -> list[TrackRecordPair]:
    """Error-free lead 5 pairs on ``days`` dates, so the window passes the 7-day threshold."""
    return [
        _pair(datetime(2026, 11, 20, 8, 0) - timedelta(days=offset), 5, 25000.0, 25000.0)
        for offset in range(days)
    ]


def _curve_cell(record, lead: int) -> tuple[int, float | None, float | None]:
    cell = record.metrics.lead_time_curve[lead - 1]
    return cell.lead_time_hours, cell.mape, cell.mae


def test_lead_time_errors_pool_every_pair_rather_than_averaging_per_day() -> None:
    """Lead 1: 10% and 10% on 11-19, 50% on 11-18, so 70/3 % pooled, not 30 % per day.

    Lead 2 has a single pair, a different count from lead 1.
    """
    pairs = [
        _pair(datetime(2026, 11, 19, 3, 0), 1, 110.0, 100.0),
        _pair(datetime(2026, 11, 19, 4, 0), 1, 90.0, 100.0),
        _pair(datetime(2026, 11, 18, 3, 0), 1, 100.0, 200.0),
        _pair(datetime(2026, 11, 19, 3, 0), 2, 120.0, 100.0),
        *_exact_filler(),
    ]

    record = compile_forecast_track_record(CUTOFF, pairs)

    assert _curve_cell(record, 1) == (1, pytest.approx(23.333333), pytest.approx(40.0))
    assert _curve_cell(record, 2) == (2, pytest.approx(20.0), pytest.approx(20.0))
    assert _curve_cell(record, 5) == (5, 0.0, 0.0)


def test_lead_time_without_pairs_is_null_and_the_curve_keeps_all_168_cells() -> None:
    record = compile_forecast_track_record(CUTOFF, _exact_filler())

    curve = record.metrics.lead_time_curve
    assert [cell.lead_time_hours for cell in curve] == list(range(1, 169))
    assert _curve_cell(record, 4) == (4, None, None)
    assert _curve_cell(record, 168) == (168, None, None)


def test_lead_24_metrics_are_the_24th_curve_cell() -> None:
    pairs = [
        _pair(datetime(2026, 11, 19, 3, 0), 24, 110.0, 100.0),
        _pair(datetime(2026, 11, 19, 4, 0), 24, 100.0, 200.0),
        *_exact_filler(),
    ]

    record = compile_forecast_track_record(CUTOFF, pairs)

    assert _curve_cell(record, 24) == (24, pytest.approx(30.0), pytest.approx(55.0))
    assert record.metrics.lead_24 == record.metrics.lead_time_curve[23]


def _series(record) -> list[tuple[datetime, float, float]]:
    return [
        (point.target_hour, point.actual_load_mw, point.predicted_load_mw)
        for point in record.metrics.lead_24_series
    ]


def test_lead_24_series_lists_hours_with_a_lead_24_pair_in_target_hour_order() -> None:
    """Hours paired only at other lead times are left out, not filled with nulls."""
    pairs = [
        _pair(datetime(2026, 11, 19, 5, 0), 24, 31000.0, 30000.0),
        _pair(datetime(2026, 11, 19, 3, 0), 24, 29000.0, 28000.0),
        _pair(datetime(2026, 11, 19, 4, 0), 23, 27000.0, 26000.0),
        *_exact_filler(),
    ]

    record = compile_forecast_track_record(CUTOFF, pairs)

    assert _series(record) == [
        (datetime(2026, 11, 19, 3, 0), 28000.0, 29000.0),
        (datetime(2026, 11, 19, 5, 0), 30000.0, 31000.0),
    ]


def test_lead_24_series_keeps_one_point_per_hour_from_the_latest_issue() -> None:
    """Two forecasts issued 30 minutes apart can both round to lead 24 for the same hour."""
    target = datetime(2026, 11, 19, 3, 0)
    earlier = TrackRecordPair(
        issued_at=target - timedelta(hours=23, minutes=45),
        target_hour=target,
        predicted_load_mw=29000.0,
        actual_load_mw=28000.0,
    )
    later = TrackRecordPair(
        issued_at=target - timedelta(hours=23, minutes=15),
        target_hour=target,
        predicted_load_mw=28500.0,
        actual_load_mw=28000.0,
    )

    record = compile_forecast_track_record(CUTOFF, [later, earlier, *_exact_filler()])

    assert _series(record) == [(target, 28000.0, 28500.0)]
    assert _curve_cell(record, 24) == (24, pytest.approx(2.678571), pytest.approx(750.0))
