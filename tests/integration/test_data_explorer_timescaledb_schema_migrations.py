"""Opt-in schema migration acceptance against an isolated local TimescaleDB (ADR-0017)."""

import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.schema_migrations import (
    MIGRATIONS,
    SchemaMigration,
    apply_schema_migrations,
)

ACCEPTANCE_MIGRATION_ID = "9001_acceptance_only"
ACCEPTANCE_TABLE = "schema_migration_acceptance"
LOCK_WAIT_TIMEOUT_SECONDS = 30
# 代表「新版程式在基線加入的表」：驗收資料庫裡沒有其他測試寫入它，刪掉後由基線重建。
TABLE_NEW_TO_THE_BASELINE = "legacy_cwa_weather"
CONCURRENT_STARTUPS = 3
# 未修正前，同時啟動的三個 process 每輪幾乎都有兩個失敗；跑幾輪讓偶然全數成功不足以通過。
CONCURRENT_STARTUP_ROUNDS = 3
LOCATION_NAME_MIGRATION_ID = "0005_add_cwa_township_forecast_location_name"


@pytest.fixture
def migrated_engine(data_explorer_timescaledb_engine: Engine) -> Iterator[Engine]:
    """The acceptance database, with this module's migration and table removed again."""
    engine = data_explorer_timescaledb_engine
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TABLE IF EXISTS {ACCEPTANCE_TABLE}"))
            connection.execute(
                text("DELETE FROM schema_migration WHERE id = :id"),
                {"id": ACCEPTANCE_MIGRATION_ID},
            )


def acceptance_migration_records(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT COUNT(*) FROM schema_migration WHERE id = :id"),
            {"id": ACCEPTANCE_MIGRATION_ID},
        ).scalar_one()


def sessions_waiting_for_an_advisory_lock(engine: Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT COUNT(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
        ).scalar_one()


def test_timescaledb_records_every_shipped_migration_once(migrated_engine: Engine) -> None:
    ensure_timescale_hypertables(migrated_engine)

    with migrated_engine.connect() as connection:
        recorded = list(
            connection.execute(text("SELECT id FROM schema_migration ORDER BY id")).scalars()
        )
    assert recorded == [migration.id for migration in MIGRATIONS]
    assert "schema_migration" not in hypertable_names(migrated_engine)


def hypertable_names(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT hypertable_name FROM timescaledb_information.hypertables")
            ).scalars()
        )


def test_two_timescaledb_startups_apply_a_migration_once(migrated_engine: Engine) -> None:
    calls = 0
    first_caller_is_inside = threading.Event()
    second_caller_is_waiting = threading.Event()

    def create_acceptance_table(connection: Connection) -> None:
        nonlocal calls
        calls += 1
        first_caller_is_inside.set()
        assert second_caller_is_waiting.wait(LOCK_WAIT_TIMEOUT_SECONDS)
        connection.execute(text(f"CREATE TABLE {ACCEPTANCE_TABLE} (id INTEGER PRIMARY KEY)"))

    migrations = (*MIGRATIONS, SchemaMigration(ACCEPTANCE_MIGRATION_ID, create_acceptance_table))

    with ThreadPoolExecutor(max_workers=2) as startups:
        first = startups.submit(apply_schema_migrations, migrated_engine, migrations)
        assert first_caller_is_inside.wait(LOCK_WAIT_TIMEOUT_SECONDS)
        second = startups.submit(apply_schema_migrations, migrated_engine, migrations)
        deadline = time.monotonic() + LOCK_WAIT_TIMEOUT_SECONDS
        while not sessions_waiting_for_an_advisory_lock(migrated_engine):
            assert time.monotonic() < deadline, "the second startup never waited for the lock"
            time.sleep(0.05)
        second_caller_is_waiting.set()
        first.result(LOCK_WAIT_TIMEOUT_SECONDS)
        second.result(LOCK_WAIT_TIMEOUT_SECONDS)

    assert calls == 1
    assert acceptance_migration_records(migrated_engine) == 1
    assert ACCEPTANCE_TABLE in inspect(migrated_engine).get_table_names()


def test_failed_timescaledb_migration_rolls_its_ddl_back(migrated_engine: Engine) -> None:
    def create_acceptance_table_then_fail(connection: Connection) -> None:
        connection.execute(text(f"CREATE TABLE {ACCEPTANCE_TABLE} (id INTEGER PRIMARY KEY)"))
        connection.execute(text("ALTER TABLE raw_cwa_observation_batch ADD COLUMN acceptance INT"))
        raise ValueError("migration body failed")

    migrations = (
        *MIGRATIONS,
        SchemaMigration(ACCEPTANCE_MIGRATION_ID, create_acceptance_table_then_fail),
    )

    with pytest.raises(ValueError, match="migration body failed"):
        apply_schema_migrations(migrated_engine, migrations)

    inspector = inspect(migrated_engine)
    assert ACCEPTANCE_TABLE not in inspector.get_table_names()
    assert "acceptance" not in {
        column["name"] for column in inspector.get_columns("raw_cwa_observation_batch")
    }
    assert acceptance_migration_records(migrated_engine) == 0


def test_startup_of_a_migrated_database_does_not_wait_for_readers(
    migrated_engine: Engine,
) -> None:
    """Each Dagster step and API start sets up the schema; it must not lock tables (#374)."""
    url = migrated_engine.url.render_as_string(hide_password=False)
    startup = get_timescale_engine(url, connect_args={"options": "-c lock_timeout=5000"})
    try:
        with migrated_engine.connect() as reader:
            for table in inspect(migrated_engine).get_table_names():
                reader.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
            ensure_timescale_hypertables(startup)
            reader.rollback()
    finally:
        startup.dispose()


def test_concurrent_startups_create_a_table_new_to_the_baseline(
    migrated_engine: Engine,
) -> None:
    """Startups after an upgrade race to create the tables the new baseline adds (#374)."""
    for _ in range(CONCURRENT_STARTUP_ROUNDS):
        with migrated_engine.begin() as connection:
            connection.execute(text(f"DROP TABLE {TABLE_NEW_TO_THE_BASELINE}"))

        with ThreadPoolExecutor(max_workers=CONCURRENT_STARTUPS) as startups:
            results = [
                startups.submit(ensure_timescale_hypertables, migrated_engine)
                for _ in range(CONCURRENT_STARTUPS)
            ]
            for result in results:
                result.result(LOCK_WAIT_TIMEOUT_SECONDS)

        assert TABLE_NEW_TO_THE_BASELINE in hypertable_names(migrated_engine)


def test_township_forecast_without_location_name_gains_it_by_migration(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(text("ALTER TABLE raw_cwa_township_forecast DROP COLUMN location_name"))
        connection.execute(
            text("DELETE FROM schema_migration WHERE id = :id"),
            {"id": LOCATION_NAME_MIGRATION_ID},
        )

    ensure_timescale_hypertables(migrated_engine)

    assert "location_name" in {
        column["name"]
        for column in inspect(migrated_engine).get_columns("raw_cwa_township_forecast")
    }
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT COUNT(*) FROM schema_migration WHERE id = :id"),
                {"id": LOCATION_NAME_MIGRATION_ID},
            ).scalar_one()
            == 1
        )
