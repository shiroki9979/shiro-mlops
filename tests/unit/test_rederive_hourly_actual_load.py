"""One-off re-derivation of hourly actual load from stored regional snapshots (ADR-0008 Notes)."""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.storage_time import from_storage_time
from shiro_mlops.data.hourly_actual_load import HourWindow
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from tests.helpers import insert_legacy_load_row

REGION_LOADS_WAN_KW = {"北部": 1000.0, "中部": 800.0, "南部": 1100.0, "東部": 100.0}
NATIONWIDE_MW = 30000.0  # 3000 萬瓩
DERIVED_SOURCE = "regional_snapshot_sum"

HOUR_A = datetime(2026, 9, 6, 18)
HOUR_B = datetime(2026, 9, 6, 19)
WINDOW = HourWindow(start=datetime(2026, 9, 6), end=datetime(2026, 9, 7))


@pytest.fixture
def store(sqlite_engine: Engine) -> HourlyActualLoadStore:
    return HourlyActualLoadStore(sqlite_engine)


def test_rederive_writes_supported_hours_and_keeps_a_derived_hour_unchanged(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_snapshots(sqlite_engine, [HOUR_A, HOUR_B])
    store.write(pd.DataFrame({"datetime": [HOUR_B], "load_mw": [31234.0]}))

    written = store.rederive(WINDOW, min_samples=4)

    assert written["datetime"].tolist() == [pd.Timestamp(HOUR_A)]
    assert written["load_mw"].tolist() == [pytest.approx(NATIONWIDE_MW)]
    assert _stored_rows(sqlite_engine) == {
        HOUR_A: (pytest.approx(NATIONWIDE_MW), DERIVED_SOURCE),
        HOUR_B: (31234.0, DERIVED_SOURCE),
    }


def test_rederive_leaves_a_legacy_hour_legacy(legacy_upgraded_engine: Engine) -> None:
    store = HourlyActualLoadStore(legacy_upgraded_engine)
    _store_snapshots(legacy_upgraded_engine, [HOUR_A])
    insert_legacy_load_row(legacy_upgraded_engine, HOUR_A, 26500.0)

    written = store.rederive(WINDOW, min_samples=4)

    assert written.empty
    assert _stored_rows(legacy_upgraded_engine)[HOUR_A] == (26500.0, None)


def test_rederive_does_not_derive_the_hour_starting_at_the_window_end(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_snapshots(sqlite_engine, [HOUR_A, HOUR_B])

    written = store.rederive(HourWindow(start=WINDOW.start, end=HOUR_B), min_samples=4)

    assert written["datetime"].tolist() == [pd.Timestamp(HOUR_A)]
    assert set(_stored_rows(sqlite_engine)) == {HOUR_A}


def test_dry_run_writes_nothing_and_lists_the_hours_a_run_then_writes(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_snapshots(sqlite_engine, [HOUR_A, HOUR_B])
    store.write(pd.DataFrame({"datetime": [HOUR_B], "load_mw": [31234.0]}))

    planned = store.rederive(WINDOW, min_samples=4, dry_run=True)
    stored_after_dry_run = _stored_rows(sqlite_engine)
    written = store.rederive(WINDOW, min_samples=4)

    assert planned["datetime"].tolist() == [pd.Timestamp(HOUR_A)]
    assert stored_after_dry_run == {HOUR_B: (31234.0, DERIVED_SOURCE)}
    pd.testing.assert_frame_equal(written, planned)


def test_a_row_written_after_the_free_hours_were_found_is_not_overwritten(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_snapshots(sqlite_engine, [HOUR_A, HOUR_B])
    planned = store.rederive(WINDOW, min_samples=4, dry_run=True)
    store.write(pd.DataFrame({"datetime": [HOUR_B], "load_mw": [31234.0]}))  # 排程搶先寫入

    written = store.write_unoccupied(planned)

    assert written["datetime"].tolist() == [pd.Timestamp(HOUR_A)]
    assert _stored_rows(sqlite_engine) == {
        HOUR_A: (pytest.approx(NATIONWIDE_MW), DERIVED_SOURCE),
        HOUR_B: (31234.0, DERIVED_SOURCE),
    }


def _store_snapshots(engine: Engine, hours: list[datetime]) -> None:
    """Store six four-region samples per hour, ten minutes apart."""
    TaipowerRegionalSupplyDemandRepository(engine, auto_init=False).upsert(
        [snapshot for hour in hours for snapshot in _snapshots_for_hour(hour)]
    )


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


def _stored_rows(engine: Engine) -> dict[datetime, tuple[float, str | None]]:
    """Every stored nationwide row with its source, legacy rows included."""
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT time, load_mw, source FROM raw_taipower_load WHERE subject = 'nationwide'")
        ).all()
    return {from_storage_time(row.time, column="time"): (row.load_mw, row.source) for row in rows}
