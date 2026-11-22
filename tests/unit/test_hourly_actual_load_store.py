"""Nationwide hourly actual load store: derived writes, latest derived observation, scheduling."""

from datetime import datetime

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore, HourlyLoadObservation
from tests.helpers import derived_hourly_load, insert_legacy_load_row


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
    _insert_other_source_row(legacy_upgraded_engine, datetime(2026, 9, 5, 18), 31000.0)

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


def test_write_replaces_another_source_with_the_derived_source(
    store: HourlyActualLoadStore, sqlite_engine: Engine
) -> None:
    _insert_other_source_row(sqlite_engine, datetime(2026, 9, 5, 16), 31000.0)

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


def _insert_other_source_row(engine: Engine, hour: datetime, load_mw: float) -> None:
    """A row the store itself cannot write: same table, another derivation source."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, 'nationwide', :load_mw, 'other_source')"
            ),
            {"time": to_storage_time(hour), "load_mw": load_mw},
        )
