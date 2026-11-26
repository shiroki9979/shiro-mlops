"""Ordered schema migrations, each recorded once in ``schema_migration`` (ADR-0017).

The baseline DDL (``src/shiro_mlops/core/sql/01_init_hypertables.sql``) is frozen: a
change to a table that already exists is a migration appended to ``MIGRATIONS``, never
an edit to that table's ``CREATE TABLE``. Fresh and existing databases take the same
path: the baseline runs, then every migration missing from the record is applied in
order.

A migration and its record row share one transaction, so a migration is either
unapplied or applied; a failure rolls both back and the next run retries. TimescaleDB
guarantees this for DDL as well. SQLite commits DDL as it runs, so a migration made of
DDL alone can leave its change behind without a record there.

On TimescaleDB the baseline and each migration run under one advisory lock
(``hold_schema_lock``), so processes that start together set up the schema one at a
time. The baseline runs at every startup, so it only creates what is missing; anything
that changes an existing table, even ``ADD COLUMN IF NOT EXISTS``, locks that table and
belongs here.

Migrations 0001 to 0004 predate the record. Each keeps the probe it used to decide
whether it had been applied, which is what lets a database older than the record be
recorded without redoing work. A migration added from 0005 on needs no probe.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from shiro_mlops.core.constants import NATIONWIDE_SUBJECT, SUBJECT_COL

logger = logging.getLogger(__name__)

SCHEMA_MIGRATION_TABLE = "schema_migration"

_LEGACY_NATIONWIDE_SUBJECT = "Taipei"
_LEGACY_CWA_HEADER_STATUS_COLUMN = "status"
# WHY-NOT(_CWA_HEADER_TABLES): 不引用 src/shiro_mlops/core/database.py 的表名常數。遷移記錄的是
# 當時的 schema，日後表改名不應改變已套用遷移的意義；該模組也匯入本模組，反向匯入會成環。
_CWA_HEADER_TABLES = ("raw_cwa_observation_batch", "raw_cwa_forecast_release")

# WHY-NOT(_MIGRATION_LOCK_KEY): 固定值而非每個遷移各一把鎖。基線與每筆遷移都搶同一把鎖，
# 後到者才會等前者提交後才建表或重查紀錄；值本身無意義，只需不與其他 advisory lock 使用者相撞。
_MIGRATION_LOCK_KEY = 2960_0017


@dataclass(frozen=True)
class SchemaMigration:
    """One schema change, applied at most once per database.

    ``id`` is the persisted record key: a four-digit sequence number plus a name. It
    must never change once shipped. ``apply`` receives the connection whose transaction
    also writes the record row, and must not commit or open a transaction of its own.
    """

    id: str
    apply: Callable[[Connection], None]


class UnknownSchemaMigrationError(RuntimeError):
    """The database records a migration this program version does not know.

    It was migrated by a newer program version. Downgrades are not supported, so
    schema setup refuses to continue rather than run against an unknown schema.
    """


def _isolate_legacy_cwa_weather(connection: Connection) -> None:
    """Move ambiguous pre-canonical weather rows into the permanent legacy table."""
    tables = set(inspect(connection).get_table_names())
    if "raw_cwa_weather" not in tables:
        return

    if "legacy_cwa_weather" not in tables:
        connection.execute(text("ALTER TABLE raw_cwa_weather RENAME TO legacy_cwa_weather"))
        return

    insert_statement = (
        """
        INSERT OR IGNORE INTO legacy_cwa_weather
            (time, location, temperature, relative_humidity, created_at)
        SELECT time, location, temperature, relative_humidity, created_at
        FROM raw_cwa_weather
        """
        if connection.dialect.name == "sqlite"
        else """
        INSERT INTO legacy_cwa_weather
            (time, location, temperature, relative_humidity, created_at)
        SELECT time, location, temperature, relative_humidity, created_at
        FROM raw_cwa_weather
        ON CONFLICT (time, location) DO NOTHING
        """
    )
    connection.execute(text(insert_statement))
    connection.execute(text("DROP TABLE raw_cwa_weather"))


def _taipower_load_columns(connection: Connection) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns("raw_taipower_load")}


def _add_taipower_load_source_column(connection: Connection) -> None:
    """Add the derivation provenance column to load tables created before ADR-0008.

    The column stays nullable on upgraded databases: NULL identifies d015046-era
    rows so operators can review and remove them before NOT NULL is enforced
    (docs/how-to/remove-legacy-d015046-load-rows.md). Existing rows are never
    rewritten here because relabelling them would mix incompatible load semantics.
    """
    if "source" in _taipower_load_columns(connection):
        return
    connection.execute(text("ALTER TABLE raw_taipower_load ADD COLUMN source VARCHAR(32)"))
    logger.warning(
        "Added nullable raw_taipower_load.source; rows with NULL source predate the "
        "regional snapshot derivation and must be removed by an operator."
    )


def _migrate_taipower_load_subject(connection: Connection) -> None:
    """Identify load series by prediction subject instead of a place name (ADR-0009).

    Before ADR-0009 nationwide load was stored under the weather reference point's
    name, ``Taipei``. Rename and relabel share the migration's transaction, so an
    interrupted upgrade never leaves a renamed column still holding the legacy value.
    """
    if SUBJECT_COL not in _taipower_load_columns(connection):
        connection.execute(
            text(f"ALTER TABLE raw_taipower_load RENAME COLUMN location TO {SUBJECT_COL}")
        )
    relabelled = connection.execute(
        text(
            f"UPDATE raw_taipower_load SET {SUBJECT_COL} = :subject WHERE {SUBJECT_COL} = :legacy"
        ),
        {"subject": NATIONWIDE_SUBJECT, "legacy": _LEGACY_NATIONWIDE_SUBJECT},
    ).rowcount
    if relabelled:
        logger.warning(
            "Relabelled %s raw_taipower_load rows from subject %r to %r.",
            relabelled,
            _LEGACY_NATIONWIDE_SUBJECT,
            NATIONWIDE_SUBJECT,
        )


def _drop_cwa_header_status_columns(connection: Connection) -> None:
    """Drop the stored ``status`` column from CWA batch and release headers (#291).

    The missing list is the only record of CWA ingestion completeness; a stored status
    could contradict it. Neither header table is a hypertable, so a plain ``DROP COLUMN``
    works on SQLite and PostgreSQL alike. Tables already without the column are skipped.
    On PostgreSQL the drop is ``IF EXISTS``: a process still running a program version
    older than the migration record drops the column without taking the migration lock,
    so the column may vanish between inspection and drop. SQLite has no
    ``DROP COLUMN IF EXISTS``.
    """
    if_exists = "" if connection.dialect.name == "sqlite" else "IF EXISTS "
    inspector = inspect(connection)
    for table in _CWA_HEADER_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if _LEGACY_CWA_HEADER_STATUS_COLUMN not in columns:
            continue
        connection.execute(
            text(f"ALTER TABLE {table} DROP COLUMN {if_exists}{_LEGACY_CWA_HEADER_STATUS_COLUMN}")
        )
        logger.warning(
            "Dropped %s.%s; CWA ingestion completeness now derives from the missing list.",
            table,
            _LEGACY_CWA_HEADER_STATUS_COLUMN,
        )


def _add_cwa_township_forecast_location_name(connection: Connection) -> None:
    """Add the township name column to forecast tables created before it existed (#374).

    This was an ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` in the baseline, which every
    startup ran: PostgreSQL takes ACCESS EXCLUSIVE before it checks for the column, so each
    Dagster step and API start waited behind every reader of the hypertable. The baseline's
    ``CREATE TABLE`` already has the column, so on a fresh database this changes nothing.
    SQLite is skipped: its databases come from that ``CREATE TABLE`` in tests, the baseline
    statement never ran there, and SQLite has no ``ADD COLUMN IF NOT EXISTS``.
    """
    if connection.dialect.name == "sqlite":
        return
    connection.execute(
        text(
            "ALTER TABLE raw_cwa_township_forecast "
            "ADD COLUMN IF NOT EXISTS location_name VARCHAR(128)"
        )
    )


def _move_unit_generation_payload_to_batch(connection: Connection) -> None:
    """Keep each unit-generation response once per slot instead of on every unit row (#372).

    Every unit row of a slot was written with the same response, except after a rerun whose
    response lacked a unit: that unit's row kept the earlier response and its earlier
    ``source_time``. The header therefore takes the payload of a row with the latest
    ``source_time``, ties broken by ``(unit_type, unit_name)``.
    Dropping the column frees no disk space by itself: PostgreSQL keeps the dropped values
    until the rows are rewritten, for example by ``VACUUM FULL`` on each chunk.
    """
    connection.execute(
        text(
            """
            INSERT INTO raw_taipower_unit_generation_batch (observed_at, raw_payload)
            SELECT observed_at, raw_payload
            FROM (
                SELECT
                    observed_at,
                    raw_payload,
                    ROW_NUMBER() OVER (
                        PARTITION BY observed_at
                        ORDER BY source_time DESC, unit_type, unit_name
                    ) AS unit_rank
                FROM raw_taipower_unit_generation_snapshot
            ) AS ranked
            WHERE unit_rank = 1
            """
        )
    )
    connection.execute(
        text("ALTER TABLE raw_taipower_unit_generation_snapshot DROP COLUMN raw_payload")
    )


MIGRATIONS: tuple[SchemaMigration, ...] = (
    SchemaMigration("0001_isolate_legacy_cwa_weather", _isolate_legacy_cwa_weather),
    SchemaMigration("0002_add_taipower_load_source_column", _add_taipower_load_source_column),
    SchemaMigration("0003_migrate_taipower_load_subject", _migrate_taipower_load_subject),
    SchemaMigration("0004_drop_cwa_header_status_columns", _drop_cwa_header_status_columns),
    SchemaMigration(
        "0005_add_cwa_township_forecast_location_name", _add_cwa_township_forecast_location_name
    ),
    SchemaMigration(
        "0006_move_unit_generation_payload_to_batch", _move_unit_generation_payload_to_batch
    ),
)


def hold_schema_lock(connection: Connection) -> None:
    """Serialize schema setup across processes until this connection's transaction ends.

    The API and each Dagster run set up the schema on their own, often at the same moment.
    Without the lock two of them can both find a table missing and both create it, and the
    later one fails. SQLite is used only by tests and takes no lock.

    Parameters
    ----------
    connection : Connection
        Connection inside the transaction that runs the schema change.
    """
    if connection.dialect.name != "sqlite":
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})


def apply_schema_migrations(
    engine: Engine, migrations: tuple[SchemaMigration, ...] = MIGRATIONS
) -> None:
    """Apply, in order, every migration the database has not recorded yet.

    The baseline DDL must already have run, since it creates the record table. When
    every migration is recorded this costs one query and takes no lock.

    Parameters
    ----------
    engine : Engine
        Engine of the database to migrate.
    migrations : tuple[SchemaMigration, ...]
        The ordered migrations this program version knows. Only tests pass their own.

    Raises
    ------
    UnknownSchemaMigrationError
        If the record holds an id that is not in ``migrations``.
    """
    with engine.connect() as connection:
        recorded = set(
            connection.execute(text(f"SELECT id FROM {SCHEMA_MIGRATION_TABLE}")).scalars()
        )
    unknown = sorted(recorded - {migration.id for migration in migrations})
    if unknown:
        raise UnknownSchemaMigrationError(
            f"{SCHEMA_MIGRATION_TABLE} records migrations unknown to this program version: "
            f"{', '.join(unknown)}. The database was migrated by a newer version; "
            "downgrades are not supported."
        )
    for migration in migrations:
        if migration.id not in recorded:
            _apply_unless_recorded(engine, migration)


def _apply_unless_recorded(engine: Engine, migration: SchemaMigration) -> None:
    """Run one migration and write its record row in a single transaction.

    On TimescaleDB the transaction first takes an advisory lock, then re-reads the
    record: the API and each Dagster run set up the schema on their own, and a process
    that waited for the lock must see that the holder already applied the migration.
    """
    with engine.begin() as connection:
        hold_schema_lock(connection)
        already_recorded = connection.execute(
            text(f"SELECT 1 FROM {SCHEMA_MIGRATION_TABLE} WHERE id = :id"), {"id": migration.id}
        ).first()
        if already_recorded:
            return
        migration.apply(connection)
        connection.execute(
            text(f"INSERT INTO {SCHEMA_MIGRATION_TABLE} (id) VALUES (:id)"), {"id": migration.id}
        )
        logger.info("Applied schema migration %s.", migration.id)
