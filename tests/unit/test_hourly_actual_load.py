"""Unit tests for deriving nationwide hourly actual load from regional snapshots."""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from shiro_mlops.data.hourly_actual_load import (
    derive_hourly_actual_load,
    recent_completed_hours,
)
from shiro_mlops.data.taipower_regional_supply_demand import (
    REGIONAL_SUPPLY_DEMAND_REGIONS,
    TaipowerRegionalSupplyDemandSnapshot,
)

HOUR_13 = datetime(2026, 9, 26, 13, 0)
AFTER_HOUR_13 = datetime(2026, 9, 26, 14, 5)


def _sample(
    source_time: datetime,
    region_loads_wan_kw: tuple[float, ...] = (1000.0, 900.0, 1100.0, 40.0),
    *,
    observed_at: datetime | None = None,
    regions: tuple[str, ...] = REGIONAL_SUPPLY_DEMAND_REGIONS,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """Build regional snapshots for one source time, totaling 30,400 MW by default."""
    return [
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=observed_at or source_time,
            region=region,
            source_time=source_time,
            generation_wan_kw=None,
            load_wan_kw=load,
            raw_payload={},
        )
        for region, load in zip(regions, region_loads_wan_kw, strict=True)
    ]


def _samples_every_ten_minutes(start: datetime, count: int) -> list:
    snapshots = []
    for index in range(count):
        snapshots.extend(_sample(start + timedelta(minutes=10 * index)))
    return snapshots


def _derive(snapshots, *, completed_before=AFTER_HOUR_13, min_samples=4) -> pd.DataFrame:
    return derive_hourly_actual_load(
        snapshots, completed_before=completed_before, min_samples=min_samples
    )


def test_hourly_value_is_mean_of_four_region_sums_converted_to_mw_at_hour_start() -> None:
    snapshots = [
        *_sample(HOUR_13, (1000.0, 900.0, 1100.0, 40.0)),  # 3040 萬瓩
        *_sample(HOUR_13 + timedelta(minutes=10), (1010.0, 900.0, 1100.0, 40.0)),  # 3050
        *_sample(HOUR_13 + timedelta(minutes=20), (1020.0, 900.0, 1100.0, 40.0)),  # 3060
        *_sample(HOUR_13 + timedelta(minutes=30), (1030.0, 900.0, 1100.0, 40.0)),  # 3070
    ]

    hourly = _derive(snapshots)

    assert hourly["datetime"].tolist() == [pd.Timestamp(HOUR_13)]
    assert hourly["load_mw"].tolist() == [pytest.approx(30550.0)]
    assert hourly["sample_count"].tolist() == [4]


def test_samples_missing_a_region_or_with_mismatched_source_time_are_excluded() -> None:
    complete = _samples_every_ten_minutes(HOUR_13, 4)
    missing_east = _sample(
        HOUR_13 + timedelta(minutes=40),
        (9999.0, 9999.0, 9999.0),
        regions=("北部", "中部", "南部"),
    )
    # 同一觀測 slot 內東部來源時間落後，兩個來源時間都不是四區齊全的樣本。
    mismatched_slot = HOUR_13 + timedelta(minutes=50)
    mismatched = [
        *_sample(
            mismatched_slot,
            (9999.0, 9999.0, 9999.0),
            regions=("北部", "中部", "南部"),
        ),
        *_sample(
            mismatched_slot - timedelta(minutes=5),
            (9999.0,),
            observed_at=mismatched_slot,
            regions=("東部",),
        ),
    ]

    hourly = _derive([*complete, *missing_east, *mismatched])

    assert hourly["sample_count"].tolist() == [4]
    assert hourly["load_mw"].tolist() == [pytest.approx(30400.0)]


def test_repeated_source_time_across_observation_slots_counts_once() -> None:
    distinct = _samples_every_ten_minutes(HOUR_13, 3)
    repeated_capture = _sample(
        HOUR_13 + timedelta(minutes=20),
        observed_at=HOUR_13 + timedelta(minutes=30),
    )

    hourly = _derive([*distinct, *repeated_capture])

    assert hourly.empty


def test_hour_with_fewer_valid_samples_than_threshold_is_not_produced() -> None:
    snapshots = _samples_every_ten_minutes(HOUR_13, 3)

    assert _derive(snapshots, min_samples=4).empty
    assert _derive(snapshots, min_samples=3)["sample_count"].tolist() == [3]


def test_unfinished_hour_is_not_produced() -> None:
    snapshots = _samples_every_ten_minutes(HOUR_13, 6)

    hourly = _derive(snapshots, completed_before=HOUR_13 + timedelta(minutes=55))

    assert hourly.empty


def test_samples_are_bucketed_into_half_open_hours() -> None:
    snapshots = [
        *_samples_every_ten_minutes(HOUR_13 + timedelta(minutes=20), 4),  # 13:20..13:50
        *_sample(HOUR_13 + timedelta(hours=1), (5000.0, 5000.0, 5000.0, 5000.0)),  # 14:00
    ]

    hourly = _derive(snapshots, completed_before=HOUR_13 + timedelta(hours=2), min_samples=1)

    assert hourly["datetime"].tolist() == [
        pd.Timestamp(HOUR_13),
        pd.Timestamp(HOUR_13 + timedelta(hours=1)),
    ]
    assert hourly["sample_count"].tolist() == [4, 1]
    assert hourly["load_mw"].tolist() == [pytest.approx(30400.0), pytest.approx(200000.0)]


def test_min_samples_must_be_positive() -> None:
    with pytest.raises(ValueError, match="min_samples"):
        _derive([], min_samples=0)


def test_recent_completed_hours_ends_at_current_hour_start() -> None:
    window = recent_completed_hours(datetime(2026, 9, 26, 14, 5, 30), hours=3)

    assert window.start == datetime(2026, 9, 26, 11, 0)
    assert window.end == datetime(2026, 9, 26, 14, 0)
