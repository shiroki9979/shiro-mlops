"""Which buckets a fixed-cadence series is expected to hold inside a window."""

from datetime import datetime, timedelta

import pytest

from shiro_mlops.service.data_explorer.datasets import HOURLY_LOAD
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.series import (
    Bucket,
    SeriesReader,
    SeriesRequest,
    expected_bucket_starts,
)

HOURLY = timedelta(hours=1)
TEN_MINUTES = timedelta(minutes=10)
DAY = datetime(2026, 11, 20)


def _starts(start: datetime, end: datetime, bucket: Bucket, cadence: timedelta) -> list[datetime]:
    return expected_bucket_starts(TimeWindow(start, end), bucket, cadence)


def test_hourly_buckets_skip_a_leading_bucket_with_no_slot_in_the_window() -> None:
    """Hourly data has one slot per hour, at :00; a window from 10:30 cannot hold the 10:00 one."""
    starts = _starts(DAY.replace(hour=10, minute=30), DAY.replace(hour=13), Bucket.HOUR, HOURLY)

    assert starts == [DAY.replace(hour=11), DAY.replace(hour=12), DAY.replace(hour=13)]


def test_daily_buckets_skip_a_leading_day_with_no_slot_in_the_window() -> None:
    start = DAY.replace(hour=23, minute=30)

    starts = _starts(start, DAY + timedelta(days=2), Bucket.DAY, HOURLY)

    assert starts == [DAY + timedelta(days=1), DAY + timedelta(days=2)]


def test_a_partial_leading_bucket_that_still_holds_a_slot_is_kept() -> None:
    """Ten-minute data from 10:30 has the 10:30, 10:40 and 10:50 slots of the 10:00 bucket."""
    starts = _starts(
        DAY.replace(hour=10, minute=30), DAY.replace(hour=12), Bucket.HOUR, TEN_MINUTES
    )

    assert starts == [DAY.replace(hour=10), DAY.replace(hour=11), DAY.replace(hour=12)]


def test_ten_minute_data_starting_past_the_last_slot_of_the_hour_skips_that_hour() -> None:
    starts = _starts(
        DAY.replace(hour=10, minute=55), DAY.replace(hour=12), Bucket.HOUR, TEN_MINUTES
    )

    assert starts == [DAY.replace(hour=11), DAY.replace(hour=12)]


def test_a_window_starting_on_a_bucket_boundary_is_unchanged() -> None:
    assert _starts(DAY, DAY + timedelta(hours=2), Bucket.HOUR, HOURLY) == [
        DAY,
        DAY + timedelta(hours=1),
        DAY + timedelta(hours=2),
    ]
    assert _starts(DAY, DAY + timedelta(days=1), Bucket.DAY, HOURLY) == [
        DAY,
        DAY + timedelta(days=1),
    ]


def test_a_partial_day_keeps_its_bucket_when_an_hour_of_it_is_in_the_window() -> None:
    starts = _starts(DAY.replace(hour=2), DAY.replace(hour=3), Bucket.DAY, HOURLY)

    assert starts == [DAY]


@pytest.mark.parametrize("bucket", [Bucket.RAW, Bucket.HOUR, Bucket.DAY])
def test_a_window_holding_no_slot_expects_no_bucket(bucket: Bucket) -> None:
    start = DAY.replace(hour=10, minute=10)

    assert _starts(start, start + timedelta(minutes=20), bucket, HOURLY) == []


@pytest.mark.parametrize("bucket", [Bucket.RAW, Bucket.HOUR, Bucket.DAY])
def test_a_zero_length_window_on_a_slot_expects_that_slot_alone(bucket: Bucket) -> None:
    assert _starts(DAY, DAY, bucket, HOURLY) == [DAY]


def test_raw_slots_follow_the_cadence_from_the_first_slot_in_the_window() -> None:
    starts = _starts(
        DAY.replace(hour=10, minute=5), DAY.replace(hour=10, minute=30), Bucket.RAW, TEN_MINUTES
    )

    assert starts == [DAY.replace(hour=10, minute=minute) for minute in (10, 20, 30)]


class _GroupAppearsBetweenReads:
    """A database where an ingestion commits a new subject after the series keys were read."""

    dialect_name = "sqlite"

    def __init__(self) -> None:
        self._real = ExplorerDb.__new__(ExplorerDb)

    def time_window(self, column: str, window: TimeWindow):
        return [f"{column} >= :start_time", f"{column} <= :end_time"], {}

    def bucket_start(self, column: str, bucket: str) -> str:
        return column

    def fetch(self, query: str, params: dict | None = None) -> list[dict]:
        if "DISTINCT" in query:
            return [{"subject": "nationwide"}]
        return [
            {"bucket_at": "2026-11-20 02:00:00", "subject": "nationwide", "v0": 30000.0},
            {"bucket_at": "2026-11-20 02:00:00", "subject": "arrived-late", "v0": 1.0},
        ]


def test_a_group_committed_between_the_two_reads_is_left_out_instead_of_crashing() -> None:
    options = HOURLY_LOAD.series
    request = SeriesRequest.build(
        HOURLY_LOAD,
        options,
        {"start": "2026-11-20T10:00:00+08:00", "end": "2026-11-20T10:00:00+08:00"},
        fields=None,
        bucket=Bucket.RAW,
    )

    response = SeriesReader(_GroupAppearsBetweenReads(), HOURLY_LOAD, options).read(request)

    assert [series.group for series in response.series] == [{"subject": "nationwide"}]
    assert [point.v for point in response.series[0].points] == [30000.0]
