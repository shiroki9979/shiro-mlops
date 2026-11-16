"""One-off re-derivation of hourly actual load from stored regional snapshots (ADR-0008 Notes)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from rederive_hourly_actual_load import rederive_missing_hours

from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)

REGION_LOADS_WAN_KW = {"北部": 1000.0, "中部": 800.0, "南部": 1100.0, "東部": 100.0}
NATIONWIDE_MW = 30000.0  # 3000 萬瓩


def _snapshots_for_hour(hour: datetime) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    return [
        TaipowerRegionalSupplyDemandSnapshot(
            observed_at=hour + timedelta(minutes=minute),
            region=region,
            source_time=hour + timedelta(minutes=minute),
            generation_wan_kw=None,
            load_wan_kw=load,
            raw_payload={},
        )
        for minute in range(0, 60, 10)
        for region, load in REGION_LOADS_WAN_KW.items()
    ]


class FakeRepository:
    def __init__(self, snapshot_hours: list[datetime], stored_hours: list[datetime]) -> None:
        self.snapshots = [s for hour in snapshot_hours for s in _snapshots_for_hour(hour)]
        self.stored = pd.DataFrame(
            {
                "time": pd.to_datetime(stored_hours),
                "subject": "nationwide",
                "load_mw": 1.0,
                "created_at": pd.Timestamp("2026-11-16"),
            }
        )
        self.upserted: list[pd.DataFrame] = []

    def fetch_regional_supply_demand_snapshots_by_source_time(self, start, end):
        return [s for s in self.snapshots if start <= s.source_time < end]

    def fetch_load_range(self, start_time=None, end_time=None, subject=None, source=None):
        return self.stored

    def upsert_taipower_load(self, df: pd.DataFrame) -> int:
        self.upserted.append(df)
        return len(df)


HOUR_A = datetime(2026, 9, 6, 18)
HOUR_B = datetime(2026, 9, 6, 19)
WINDOW = (datetime(2026, 9, 6), datetime(2026, 9, 7))


def test_only_hours_missing_from_stored_load_are_written() -> None:
    repository = FakeRepository(snapshot_hours=[HOUR_A, HOUR_B], stored_hours=[HOUR_B])

    written = rederive_missing_hours(repository, *WINDOW, min_samples=4, dry_run=False)

    assert written["datetime"].tolist() == [pd.Timestamp(HOUR_A)]
    assert written["load_mw"].tolist() == [pytest.approx(NATIONWIDE_MW)]
    assert len(repository.upserted) == 1
    assert repository.upserted[0]["datetime"].tolist() == [pd.Timestamp(HOUR_A)]


def test_dry_run_reports_missing_hours_without_writing() -> None:
    repository = FakeRepository(snapshot_hours=[HOUR_A, HOUR_B], stored_hours=[])

    planned = rederive_missing_hours(repository, *WINDOW, min_samples=4, dry_run=True)

    assert planned["datetime"].tolist() == [pd.Timestamp(HOUR_A), pd.Timestamp(HOUR_B)]
    assert repository.upserted == []


def test_nothing_is_written_when_every_derivable_hour_is_stored() -> None:
    repository = FakeRepository(snapshot_hours=[HOUR_A], stored_hours=[HOUR_A])

    written = rederive_missing_hours(repository, *WINDOW, min_samples=4, dry_run=False)

    assert written.empty
    assert repository.upserted == []
