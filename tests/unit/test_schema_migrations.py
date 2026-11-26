"""Schema migrations are recorded once in ``schema_migration`` instead of re-inferred (ADR-0017)."""

import json
from collections.abc import Callable, Iterator
from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.database import (
    convert_timescale_ddl_to_sqlite,
    ensure_timescale_hypertables,
    get_timescale_init_ddl,
)
from shiro_mlops.core.schema_migrations import (
    MIGRATIONS,
    SchemaMigration,
    UnknownSchemaMigrationError,
    apply_schema_migrations,
)
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)
from tests.helpers import (
    MIGRATIONS_BEFORE_UNIT_BATCH,
    create_legacy_load_table,
    create_location_keyed_load_table,
)

# 已寫進既有資料庫的 id 是持久契約；改名會讓舊資料庫被當成記錄了不認得的遷移。
RECORDED_IDS = [
    "0001_isolate_legacy_cwa_weather",
    "0002_add_taipower_load_source_column",
    "0003_migrate_taipower_load_subject",
    "0004_drop_cwa_header_status_columns",
    "0005_add_cwa_township_forecast_location_name",
    "0006_move_unit_generation_payload_to_batch",
]


@pytest.fixture
def engine(tmp_path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'schema_migrations.db'}")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def baseline_engine(engine: Engine) -> Engine:
    """A database holding the baseline DDL only, with no migration recorded yet."""
    with engine.begin() as connection:
        for statement in convert_timescale_ddl_to_sqlite(get_timescale_init_ddl()):
            connection.execute(text(statement))
    return engine


def recorded_migrations(engine: Engine) -> list[tuple[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT id, applied_at FROM schema_migration ORDER BY id")
        ).all()
    return [(row.id, row.applied_at) for row in rows]


def recorded_ids(engine: Engine) -> list[str]:
    return [migration_id for migration_id, _ in recorded_migrations(engine)]


class CountingMigration:
    """A fake migration that counts its calls and can be told to fail."""

    def __init__(self, migration_id: str) -> None:
        self.calls = 0
        self.error: Exception | None = None
        self.migration = SchemaMigration(migration_id, self._apply)

    def _apply(self, connection: Connection) -> None:
        self.calls += 1
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES ('2026-08-20 00:00:00', :subject, 1.0, 'fake')"
            ),
            {"subject": self.migration.id},
        )
        if self.error is not None:
            raise self.error


def subjects_written_by_fakes(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text("SELECT subject FROM raw_taipower_load ORDER BY subject")
            ).scalars()
        )


def test_shipped_migration_ids_stay_as_recorded() -> None:
    assert [migration.id for migration in MIGRATIONS] == RECORDED_IDS


def test_fresh_database_records_every_migration_exactly_once(engine: Engine) -> None:
    ensure_timescale_hypertables(engine)
    first_run = recorded_migrations(engine)

    ensure_timescale_hypertables(engine)

    assert [migration_id for migration_id, _ in first_run] == RECORDED_IDS
    assert all(applied_at is not None for _, applied_at in first_run)
    assert recorded_migrations(engine) == first_run


def create_legacy_weather_table(engine: Engine) -> None:
    """Model a pre-ADR-0007 database whose weather rows carry no station provenance."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE raw_cwa_weather (
                    time TIMESTAMP NOT NULL,
                    location VARCHAR(64) NOT NULL,
                    temperature DOUBLE PRECISION,
                    relative_humidity DOUBLE PRECISION,
                    created_at TIMESTAMP,
                    PRIMARY KEY (time, location)
                )
                """
            )
        )


def create_cwa_headers_with_status(engine: Engine) -> None:
    """Model a pre-#339 database whose CWA headers store a status column."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE raw_cwa_observation_batch (
                    fetched_at TIMESTAMP NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    missing_station_ids TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (fetched_at)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE raw_cwa_forecast_release (
                    dataset_id VARCHAR(16) NOT NULL,
                    issued_at TIMESTAMP NOT NULL,
                    source_updated_at TIMESTAMP NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    status VARCHAR(16) NOT NULL,
                    missing_geocodes TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (dataset_id, issued_at, source_updated_at)
                )
                """
            )
        )


def create_every_legacy_shape(engine: Engine) -> None:
    create_legacy_weather_table(engine)
    create_legacy_load_table(engine)
    create_cwa_headers_with_status(engine)


def table_columns(engine: Engine, table: str) -> list[str]:
    with engine.connect() as connection:
        return [row.name for row in connection.execute(text(f"PRAGMA table_info({table})"))]


@pytest.mark.parametrize(
    "create_legacy_database",
    [
        create_legacy_weather_table,
        create_legacy_load_table,
        create_location_keyed_load_table,
        create_cwa_headers_with_status,
        create_every_legacy_shape,
    ],
)
def test_database_older_than_the_record_is_upgraded_and_recorded(
    engine: Engine, create_legacy_database: Callable[[Engine], None]
) -> None:
    create_legacy_database(engine)

    ensure_timescale_hypertables(engine)

    assert recorded_ids(engine) == RECORDED_IDS
    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            ).scalars()
        )
    assert "raw_cwa_weather" not in tables
    load_columns = table_columns(engine, "raw_taipower_load")
    assert "subject" in load_columns
    assert "source" in load_columns
    assert "location" not in load_columns
    assert "status" not in table_columns(engine, "raw_cwa_observation_batch")
    assert "status" not in table_columns(engine, "raw_cwa_forecast_release")


def test_recorded_migration_is_not_called_again(baseline_engine: Engine) -> None:
    first, second = CountingMigration("0001_first"), CountingMigration("0002_second")
    migrations = (first.migration, second.migration)

    apply_schema_migrations(baseline_engine, migrations=migrations)
    apply_schema_migrations(baseline_engine, migrations=migrations)

    assert (first.calls, second.calls) == (1, 1)
    assert recorded_ids(baseline_engine) == ["0001_first", "0002_second"]


def test_migration_added_later_is_the_only_one_applied(baseline_engine: Engine) -> None:
    first, second = CountingMigration("0001_first"), CountingMigration("0002_second")
    apply_schema_migrations(baseline_engine, migrations=(first.migration,))

    apply_schema_migrations(baseline_engine, migrations=(first.migration, second.migration))

    assert (first.calls, second.calls) == (1, 1)
    assert recorded_ids(baseline_engine) == ["0001_first", "0002_second"]


def test_failed_migration_leaves_no_record_and_is_retried(baseline_engine: Engine) -> None:
    first, failing, third = (
        CountingMigration("0001_first"),
        CountingMigration("0002_failing"),
        CountingMigration("0003_third"),
    )
    migrations = (first.migration, failing.migration, third.migration)
    failing.error = ValueError("migration body failed")

    with pytest.raises(ValueError, match="migration body failed"):
        apply_schema_migrations(baseline_engine, migrations=migrations)

    assert recorded_ids(baseline_engine) == ["0001_first"]
    assert subjects_written_by_fakes(baseline_engine) == ["0001_first"]
    assert third.calls == 0

    failing.error = None
    apply_schema_migrations(baseline_engine, migrations=migrations)

    assert (first.calls, failing.calls, third.calls) == (1, 2, 1)
    assert recorded_ids(baseline_engine) == ["0001_first", "0002_failing", "0003_third"]
    assert subjects_written_by_fakes(baseline_engine) == [
        "0001_first",
        "0002_failing",
        "0003_third",
    ]


def test_unknown_recorded_migration_stops_before_any_migration_runs(
    baseline_engine: Engine,
) -> None:
    pending = CountingMigration("0001_pending")
    with baseline_engine.begin() as connection:
        connection.execute(text("INSERT INTO schema_migration (id) VALUES ('0009_from_newer')"))

    with pytest.raises(UnknownSchemaMigrationError, match="0009_from_newer"):
        apply_schema_migrations(baseline_engine, migrations=(pending.migration,))

    assert pending.calls == 0
    assert recorded_ids(baseline_engine) == ["0009_from_newer"]


def test_database_from_a_newer_program_version_refuses_schema_setup(engine: Engine) -> None:
    ensure_timescale_hypertables(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO schema_migration (id) VALUES ('0099_from_newer')"))

    with pytest.raises(UnknownSchemaMigrationError, match="0099_from_newer"):
        ensure_timescale_hypertables(engine)


def _unit_payload(slot: str, unit_names: list[str]) -> str:
    rows = [{"機組類型": "燃氣", "機組名稱": name} for name in unit_names]
    return json.dumps({"DateTime": slot, "aaData": rows}, ensure_ascii=False)


def insert_legacy_unit_row(
    engine: Engine, observed_at: str, unit_name: str, source_time: str, payload: str
) -> None:
    """Write a unit row as before 0006, carrying the whole response it was parsed from."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO raw_taipower_unit_generation_snapshot (
                    observed_at, unit_type, unit_name, source_time,
                    capacity_mw, net_generation_mw, capacity_ratio_pct, remark,
                    raw_payload
                ) VALUES (
                    :observed_at, '燃氣', :unit_name, :source_time,
                    742.7, 670.4, 90.265, NULL, :payload
                )
                """
            ),
            {
                "observed_at": observed_at,
                "unit_name": unit_name,
                "source_time": source_time,
                "payload": payload,
            },
        )


def insert_unit_rows_carrying_the_payload(engine: Engine) -> None:
    """Model rows written before 0006: every unit row repeats its slot's whole response."""
    slots = {
        "2026-09-05 09:30:00+00:00": ("2026-09-05T17:30:00", ["大潭CC#1", "大潭CC#3"]),
        "2026-09-05 09:40:00+00:00": ("2026-09-05T17:40:00", ["大潭CC#1", "大潭CC#3"]),
    }
    for observed_at, (source_slot, unit_names) in slots.items():
        payload = _unit_payload(source_slot, unit_names)
        for name in unit_names:
            insert_legacy_unit_row(engine, observed_at, name, observed_at, payload)


def test_unit_generation_response_moves_from_every_row_to_one_batch(
    baseline_engine: Engine,
) -> None:
    """Each slot's response is kept once in the batch header and no longer on the unit rows."""
    apply_schema_migrations(baseline_engine, migrations=MIGRATIONS_BEFORE_UNIT_BATCH)
    insert_unit_rows_carrying_the_payload(baseline_engine)

    ensure_timescale_hypertables(baseline_engine)

    assert "raw_payload" not in table_columns(
        baseline_engine, "raw_taipower_unit_generation_snapshot"
    )
    repository = TaipowerUnitGenerationRepository(engine=baseline_engine, auto_init=False)
    batch = repository.fetch(datetime(2026, 9, 5, 17, 40))
    assert batch is not None
    assert batch.raw_payload == {
        "DateTime": "2026-09-05T17:40:00",
        "aaData": [
            {"機組類型": "燃氣", "機組名稱": "大潭CC#1"},
            {"機組類型": "燃氣", "機組名稱": "大潭CC#3"},
        ],
    }
    assert [snapshot.unit_name for snapshot in batch.snapshots] == ["大潭CC#1", "大潭CC#3"]
    earlier = repository.fetch(datetime(2026, 9, 5, 17, 30))
    assert earlier is not None
    assert earlier.raw_payload["DateTime"] == "2026-09-05T17:30:00"


def test_unit_generation_batch_takes_the_latest_response_of_a_rerun_slot(
    baseline_engine: Engine,
) -> None:
    """A rerun that lost a unit left that row on the earlier response; the header takes the later."""
    apply_schema_migrations(baseline_engine, migrations=MIGRATIONS_BEFORE_UNIT_BATCH)
    observed_at = "2026-09-05 09:30:00+00:00"
    insert_legacy_unit_row(
        baseline_engine,
        observed_at,
        "大潭CC#1",
        "2026-09-05 09:20:00+00:00",
        _unit_payload("2026-09-05T17:20:00", ["大潭CC#1", "大潭CC#3"]),
    )
    insert_legacy_unit_row(
        baseline_engine,
        observed_at,
        "大潭CC#3",
        observed_at,
        _unit_payload("2026-09-05T17:30:00", ["大潭CC#3"]),
    )

    ensure_timescale_hypertables(baseline_engine)

    batch = TaipowerUnitGenerationRepository(engine=baseline_engine, auto_init=False).fetch(
        datetime(2026, 9, 5, 17, 30)
    )
    assert batch is not None
    assert batch.raw_payload["DateTime"] == "2026-09-05T17:30:00"
