"""Nationwide hourly actual load store: derived writes, latest derived observation, scheduling."""

from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.data.hourly_actual_load import HourlyLoadAccumulation, HourWindow
from shiro_mlops.data.hourly_actual_load_store import (
    HourlyActualLoadStore,
    HourlyLoadObservation,
    ScheduledDerivationPolicy,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from tests.helpers import (
    derived_hourly_load,
    derived_load_series,
    insert_legacy_load_row,
    insert_other_source_load_row,
    regional_supply_demand_snapshots,
)

TICK = datetime(2026, 9, 5, 18, 5)
POLICY = ScheduledDerivationPolicy(recompute_hours=3, max_catchup_hours=168, min_samples=4)
# 區域 fixture 四區用電加總 3254.0 萬瓩，即 32540 MW。
FIXTURE_TOTAL_MW = 32540.0


@pytest.fixture
def store(sqlite_engine: Engine) -> HourlyActualLoadStore:
    return HourlyActualLoadStore(sqlite_engine)


def test_latest_observation_is_the_newest_written_hour_at_or_before_the_cutoff(
    store: HourlyActualLoadStore,
) -> None:
    store.write(derived_hourly_load(3, datetime(2026, 9, 5, 16)))  # 14:00、15:00、16:00

    assert store.latest_observation(datetime(2026, 9, 5, 15)) == HourlyLoadObservation(
        hour=datetime(2026, 9, 5, 15), load_mw=30001.0
    )
    assert store.latest_observation(datetime(2026, 9, 5, 18)) == HourlyLoadObservation(
        hour=datetime(2026, 9, 5, 16), load_mw=30002.0
    )


def test_latest_observation_is_none_when_no_hour_is_derived_by_the_cutoff(
    store: HourlyActualLoadStore,
) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)))

    assert store.latest_observation(datetime(2026, 9, 5, 15, 59)) is None


def test_latest_observation_ignores_legacy_and_other_source_rows(
    legacy_upgraded_engine: Engine,
) -> None:
    store = HourlyActualLoadStore(legacy_upgraded_engine)
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)))
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 9, 5, 17), 26500.0)
    insert_other_source_load_row(legacy_upgraded_engine, datetime(2026, 9, 5, 18), 31000.0)

    assert store.latest_observation(datetime(2026, 9, 5, 18)) == HourlyLoadObservation(
        hour=datetime(2026, 9, 5, 16), load_mw=30000.0
    )


def test_latest_observation_reads_one_prediction_subject(store: HourlyActualLoadStore) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)), subject="north")
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 15)))

    assert store.latest_observation(datetime(2026, 9, 5, 18), subject="north") == (
        HourlyLoadObservation(hour=datetime(2026, 9, 5, 16), load_mw=30000.0)
    )
    assert store.latest_observation(datetime(2026, 9, 5, 18)) == HourlyLoadObservation(
        hour=datetime(2026, 9, 5, 15), load_mw=30000.0
    )


def test_series_holds_only_derived_hours_in_a_datetime_column(
    legacy_upgraded_engine: Engine,
) -> None:
    store = HourlyActualLoadStore(legacy_upgraded_engine)
    store.write(derived_hourly_load(2, datetime(2026, 9, 5, 16)))  # 15:00、16:00
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 9, 5, 17), 26500.0)
    insert_other_source_load_row(legacy_upgraded_engine, datetime(2026, 9, 5, 18), 31000.0)

    series = store.series(start=datetime(2026, 9, 5), end=datetime(2026, 9, 6))

    pd.testing.assert_frame_equal(
        series,
        pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2026-09-05 15:00", "2026-09-05 16:00"]),
                "load_mw": [30000.0, 30001.0],
            }
        ),
    )


def test_series_window_includes_its_start_and_excludes_its_end(
    store: HourlyActualLoadStore,
) -> None:
    store.write(derived_hourly_load(4, datetime(2026, 9, 5, 17)))  # 14:00 至 17:00

    series = store.series(start=datetime(2026, 9, 5, 15), end=datetime(2026, 9, 5, 17))

    assert series["datetime"].tolist() == [
        pd.Timestamp("2026-09-05 15:00"),
        pd.Timestamp("2026-09-05 16:00"),
    ]


def test_series_without_a_start_begins_at_the_earliest_derived_hour(
    legacy_upgraded_engine: Engine,
) -> None:
    store = HourlyActualLoadStore(legacy_upgraded_engine)
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 9, 1), 26500.0)
    store.write(derived_hourly_load(3, datetime(2026, 9, 5, 16)))  # 14:00、15:00、16:00

    series = store.series(end=datetime(2026, 9, 5, 16))

    assert series["datetime"].tolist() == [
        pd.Timestamp("2026-09-05 14:00"),
        pd.Timestamp("2026-09-05 15:00"),
    ]


def test_series_reads_one_prediction_subject(store: HourlyActualLoadStore) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)), subject="north")
    store.write(derived_hourly_load(2, datetime(2026, 9, 5, 16)))

    north = store.series(end=datetime(2026, 9, 6), subject="north")
    nationwide = store.series(end=datetime(2026, 9, 6))

    assert north["datetime"].tolist() == [pd.Timestamp("2026-09-05 16:00")]
    assert nationwide["datetime"].tolist() == [
        pd.Timestamp("2026-09-05 15:00"),
        pd.Timestamp("2026-09-05 16:00"),
    ]


def test_series_is_oldest_first_whatever_order_the_hours_were_written(
    store: HourlyActualLoadStore,
) -> None:
    store.write(
        pd.DataFrame(
            {
                "datetime": ["2026-08-20 03:00", "2026-08-20 01:00", "2026-08-20 02:00"],
                "load_mw": [23800.0, 25200.0, 24300.0],
            }
        )
    )
    store.write(
        pd.DataFrame({"datetime": ["2026-08-20 02:00"], "load_mw": [18000.0]}), subject="south"
    )

    series = store.series(start=datetime(2026, 8, 20, 1), end=datetime(2026, 8, 20, 3))

    assert len(series) == 2
    assert list(series["load_mw"]) == [25200.0, 24300.0]
    assert series.iloc[0]["datetime"] < series.iloc[1]["datetime"]


def test_an_empty_series_keeps_its_datetime_and_load_columns(
    store: HourlyActualLoadStore,
) -> None:
    series = store.series(end=datetime(2026, 9, 6))

    assert series.empty
    assert list(series.columns) == ["datetime", "load_mw"]
    assert pd.api.types.is_datetime64_any_dtype(series["datetime"])


def test_accumulation_counts_derived_hours_through_the_cutoff(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    store.write(derived_hourly_load(4, datetime(2026, 9, 5, 17)))  # 14:00 至 17:00
    store.write(derived_hourly_load(2, datetime(2026, 9, 5, 17)), subject="north")
    insert_other_source_load_row(sqlite_engine, datetime(2026, 9, 5, 13), 31000.0)

    assert store.accumulation(datetime(2026, 9, 5, 16)) == HourlyLoadAccumulation(
        valid_hours=3, legacy_rows=0, latest_hour=datetime(2026, 9, 5, 16)
    )
    assert store.accumulation() == HourlyLoadAccumulation(
        valid_hours=4, legacy_rows=0, latest_hour=datetime(2026, 9, 5, 17)
    )


def test_accumulation_without_derived_hours_has_no_latest_hour(
    store: HourlyActualLoadStore,
) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)))

    assert store.accumulation(datetime(2026, 9, 5, 15)) == HourlyLoadAccumulation(
        valid_hours=0, legacy_rows=0, latest_hour=None
    )


def test_accumulation_counts_legacy_rows_at_any_time_and_subject(
    legacy_upgraded_engine: Engine,
) -> None:
    """The fixture's legacy row is one; two more lie after the cutoff or under another subject."""
    store = HourlyActualLoadStore(legacy_upgraded_engine)
    store.write(derived_hourly_load(2, datetime(2026, 9, 5, 16)))
    insert_legacy_load_row(legacy_upgraded_engine, datetime(2026, 9, 5, 20), 26500.0)
    with legacy_upgraded_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw) "
                "VALUES (:time, 'north', 8000.0)"
            ),
            {"time": to_storage_time(datetime(2026, 9, 5, 12))},
        )

    assert store.accumulation(datetime(2026, 9, 5, 16)) == HourlyLoadAccumulation(
        valid_hours=2, legacy_rows=3, latest_hour=datetime(2026, 9, 5, 16)
    )


def test_write_replaces_another_source_with_the_derived_source(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    insert_other_source_load_row(sqlite_engine, datetime(2026, 9, 5, 16), 31000.0)

    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 16)))

    assert store.latest_observation(datetime(2026, 9, 5, 16)) == HourlyLoadObservation(
        hour=datetime(2026, 9, 5, 16), load_mw=30000.0
    )


def test_write_offers_no_choice_of_source(store: HourlyActualLoadStore) -> None:
    with pytest.raises(TypeError, match="source"):
        store.write(  # type: ignore[call-arg]  # 寫入 interface 刻意沒有 source 參數
            derived_hourly_load(1, datetime(2026, 9, 5, 16)), source="other_source"
        )


def test_write_rejects_the_storage_time_column(store: HourlyActualLoadStore) -> None:
    stored_form = pd.DataFrame({"time": [datetime(2026, 9, 5, 16)], "load_mw": [30000.0]})

    with pytest.raises(KeyError, match="'datetime'.*not the storage column 'time'"):
        store.write(stored_form)


def test_rewriting_a_derived_hour_updates_its_load_in_place(store: HourlyActualLoadStore) -> None:
    store.write(
        pd.DataFrame(
            {"datetime": ["2026-08-20 00:00", "2026-08-20 01:00"], "load_mw": [25000.0, 24000.0]}
        )
    )

    store.write(pd.DataFrame({"datetime": ["2026-08-20 00:00"], "load_mw": [26800.0]}))

    series = store.series(end=datetime(2026, 8, 21))
    assert len(series) == 2
    row_00 = series[series["datetime"] == pd.Timestamp("2026-08-20 00:00")].iloc[0]
    assert row_00["load_mw"] == pytest.approx(26800.0)


def test_writing_no_hours_writes_nothing(store: HourlyActualLoadStore) -> None:
    assert store.write(pd.DataFrame(columns=["datetime", "load_mw"])) == 0


def test_rerunning_a_tick_recomputes_the_recent_hours_to_the_same_load(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 14), 6)  # 尚無推算小時，由補算上限涵蓋
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 15), 6)
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 16), 4)
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 17), 3)  # 低於樣本門檻
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 18), 1)  # 尚未結束

    first = store.derive_scheduled(TICK, POLICY)
    persisted = _persisted_load(sqlite_engine)
    rerun = store.derive_scheduled(TICK, POLICY)

    assert persisted == {
        datetime(2026, 9, 5, 14): pytest.approx(FIXTURE_TOTAL_MW),
        datetime(2026, 9, 5, 15): pytest.approx(FIXTURE_TOTAL_MW),
        datetime(2026, 9, 5, 16): pytest.approx(FIXTURE_TOTAL_MW),
    }
    assert _persisted_load(sqlite_engine) == persisted
    assert first.window == HourWindow(start=datetime(2026, 8, 29, 18), end=datetime(2026, 9, 5, 18))
    assert (first.snapshot_count, first.written_hours) == (19 * 4, 3)
    assert first.hourly_load["datetime"].tolist() == [
        pd.Timestamp("2026-09-05 14:00"),
        pd.Timestamp("2026-09-05 15:00"),
        pd.Timestamp("2026-09-05 16:00"),
    ]
    assert rerun.window == HourWindow(start=datetime(2026, 9, 5, 15), end=datetime(2026, 9, 5, 18))
    assert rerun.written_hours == 2


def test_late_sample_fills_a_previously_missing_hour(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 17), 3)
    store.derive_scheduled(TICK, POLICY)
    assert _persisted_load(sqlite_engine) == {}

    _store_samples(sqlite_engine, datetime(2026, 9, 5, 17, 30), 1)
    store.derive_scheduled(TICK, POLICY)

    assert _persisted_load(sqlite_engine) == {
        datetime(2026, 9, 5, 17): pytest.approx(FIXTURE_TOTAL_MW)
    }


def test_resumed_schedule_derives_the_boundary_hour_left_by_an_outage(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    """An hour stored just before an outage is derived once the schedule resumes (#113)."""
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 10), 6)
    store.derive_scheduled(datetime(2026, 9, 5, 11, 5), POLICY)
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 11), 6)  # 中斷前最後一個完整小時
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 17), 6)  # 排程恢復後的小時

    resumed = store.derive_scheduled(TICK, POLICY)

    assert _persisted_load(sqlite_engine) == {
        datetime(2026, 9, 5, 10): pytest.approx(FIXTURE_TOTAL_MW),
        datetime(2026, 9, 5, 11): pytest.approx(FIXTURE_TOTAL_MW),
        datetime(2026, 9, 5, 17): pytest.approx(FIXTURE_TOTAL_MW),
    }
    assert resumed.window == HourWindow(
        start=datetime(2026, 9, 5, 11), end=datetime(2026, 9, 5, 18)
    )


def test_derived_hours_newer_than_the_tick_do_not_move_its_window(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    """A re-run of an old tick anchors on what was derived by then, not on later rows."""
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 11), 6)
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 16), 6)  # 舊 tick 當下尚未結束
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 17), 6)
    store.derive_scheduled(TICK, POLICY)
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 12), 6)

    old_tick = store.derive_scheduled(datetime(2026, 9, 5, 16, 5), POLICY)

    assert old_tick.window == HourWindow(
        start=datetime(2026, 9, 5, 12), end=datetime(2026, 9, 5, 16)
    )
    assert datetime(2026, 9, 5, 12) in _persisted_load(sqlite_engine)


def test_hours_beyond_the_catchup_limit_are_reported_and_not_derived(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 1)))
    _store_samples(sqlite_engine, datetime(2026, 9, 1, 2), 6)  # 超出補算上限
    _store_samples(sqlite_engine, datetime(2026, 9, 5, 9), 6)

    derivation = store.derive_scheduled(TICK, replace(POLICY, max_catchup_hours=24))

    assert derivation.uncovered_gap == HourWindow(
        start=datetime(2026, 9, 1, 1), end=datetime(2026, 9, 4, 18)
    )
    assert derivation.window == HourWindow(
        start=datetime(2026, 9, 4, 18), end=datetime(2026, 9, 5, 18)
    )
    assert set(_persisted_load(sqlite_engine)) == {
        datetime(2026, 9, 1),
        datetime(2026, 9, 5, 9),
    }


def test_window_reaching_the_latest_derived_hour_leaves_no_gap(
    store: HourlyActualLoadStore,
) -> None:
    store.write(derived_hourly_load(1, datetime(2026, 9, 5, 10)))

    assert store.derive_scheduled(TICK, POLICY).uncovered_gap is None


def _store_samples(engine: Engine, start: datetime, count: int) -> None:
    """Store four-region snapshots every ten minutes, each slot its own source time."""
    snapshots = TaipowerRegionalSupplyDemandRepository(engine, auto_init=False)
    for index in range(count):
        slot = start + timedelta(minutes=10 * index)
        snapshots.upsert(
            [
                replace(snapshot, source_time=slot)
                for snapshot in regional_supply_demand_snapshots(slot)
            ]
        )


def _persisted_load(engine: Engine) -> dict[datetime, float]:
    """Every stored nationwide derived hour."""
    stored = derived_load_series(engine)
    return {
        hour.to_pydatetime(): load_mw
        for hour, load_mw in zip(stored["datetime"], stored["load_mw"], strict=True)
    }
