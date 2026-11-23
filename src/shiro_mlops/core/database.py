"""TimescaleDB database connection helpers and schema initialization."""

import logging
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import NoInspectionAvailable

from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import NATIONWIDE_SUBJECT, SUBJECT_COL
from shiro_mlops.core.storage_time import register_sqlite_datetime_adapter

logger = logging.getLogger(__name__)

# ADR-0009 之前全台負載借用氣象代表點名稱保存；只用於辨識待遷移的舊值。
LEGACY_NATIONWIDE_SUBJECT = "Taipei"

CWA_OBSERVATION_BATCH_TABLE = "raw_cwa_observation_batch"
CWA_FORECAST_RELEASE_TABLE = "raw_cwa_forecast_release"
CWA_HEADER_TABLES = (CWA_OBSERVATION_BATCH_TABLE, CWA_FORECAST_RELEASE_TABLE)
LEGACY_CWA_HEADER_STATUS_COLUMN = "status"

# DDL 隨套件安裝，不依賴 repo 目錄結構：API 映像只含 src/（#112）。
# docker-compose 亦把同一目錄掛為資料庫容器的 init-db，兩者共用單一來源。
INIT_SQL_PATH: Traversable = files(__package__).joinpath("sql", "01_init_hypertables.sql")


def get_timescale_init_ddl(sql_path: Path | None = None) -> str:
    """Return the SQL DDL string used to initialize TimescaleDB hypertables.

    Parameters
    ----------
    sql_path : Path | None
        Optional custom path to the SQL initialization file. Defaults to the DDL
        packaged with ``shiro_mlops``.

    Returns
    -------
    str
        Contents of the initialization SQL file.
    """
    target_path: Path | Traversable = sql_path or INIT_SQL_PATH
    if not target_path.is_file():
        raise FileNotFoundError(f"DDL initialization script not found at {target_path}")
    return target_path.read_text(encoding="utf-8")


def _keep_json_text(value: str) -> str:
    """Return JSON column values as JSON text instead of parsed Python objects."""
    return value


def get_timescale_engine(uri: str | None = None, **kwargs: Any) -> Engine:
    """Create and return a SQLAlchemy Engine for TimescaleDB.

    JSON and JSONB columns read back as JSON text, as SQLite TEXT columns do,
    so ``deserialize_raw_payload`` decodes every stored payload exactly once
    whichever database holds it.

    Parameters
    ----------
    uri : str | None
        Optional database connection URI. Defaults to settings.timescale_uri.
    **kwargs : Any
        Additional keyword arguments passed to sqlalchemy.create_engine.

    Returns
    -------
    Engine
        Configured SQLAlchemy Engine instance.
    """
    db_uri = uri or settings.timescale_uri
    if make_url(db_uri).get_backend_name() == "sqlite":
        register_sqlite_datetime_adapter()
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True, "json_deserializer": _keep_json_text}
    engine_kwargs.update(kwargs)
    return create_engine(db_uri, **engine_kwargs)


def _strip_line_comments(sql: str) -> str:
    """Remove full-line SQL comments before splitting executable statements."""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def split_sql_statements(ddl: str) -> list[str]:
    """Split DDL into executable statements while skipping comment-only segments."""
    statements: list[str] = []
    for chunk in _strip_line_comments(ddl).split(";"):
        cleaned = chunk.strip()
        if cleaned:
            statements.append(cleaned)
    return statements


def _execute_sql_statements(engine: Engine, statements: list[str]) -> None:
    """Execute a list of SQL statements with leading/trailing whitespace stripped."""
    with engine.connect() as conn:
        for statement in statements:
            cleaned = statement.strip()
            if cleaned:
                conn.execute(text(cleaned))
        conn.commit()


def _isolate_legacy_cwa_weather(engine: Engine) -> None:
    """Move ambiguous pre-canonical weather rows into the permanent legacy table."""
    try:
        tables = set(inspect(engine).get_table_names())
    except NoInspectionAvailable:
        return
    if "raw_cwa_weather" not in tables:
        return

    if "legacy_cwa_weather" not in tables:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE raw_cwa_weather RENAME TO legacy_cwa_weather"))
        return

    insert_statement = (
        """
        INSERT OR IGNORE INTO legacy_cwa_weather
            (time, location, temperature, relative_humidity, created_at)
        SELECT time, location, temperature, relative_humidity, created_at
        FROM raw_cwa_weather
        """
        if engine.dialect.name == "sqlite"
        else """
        INSERT INTO legacy_cwa_weather
            (time, location, temperature, relative_humidity, created_at)
        SELECT time, location, temperature, relative_humidity, created_at
        FROM raw_cwa_weather
        ON CONFLICT (time, location) DO NOTHING
        """
    )
    with engine.begin() as connection:
        connection.execute(text(insert_statement))
        connection.execute(text("DROP TABLE raw_cwa_weather"))


def _taipower_load_columns(engine: Engine, purpose: str) -> set[str]:
    try:
        columns = inspect(engine).get_columns("raw_taipower_load")
    except NoInspectionAvailable as error:
        raise RuntimeError(f"Cannot inspect raw_taipower_load schema for {purpose}") from error
    return {column["name"] for column in columns}


def _add_taipower_load_source_column(engine: Engine) -> None:
    """Add the derivation provenance column to load tables created before ADR-0008.

    The column stays nullable on upgraded databases: NULL identifies d015046-era
    rows so operators can review and remove them before NOT NULL is enforced
    (docs/how-to/remove-legacy-d015046-load-rows.md). Existing rows are never
    rewritten here because relabelling them would mix incompatible load semantics.
    """
    if "source" in _taipower_load_columns(engine, "source migration"):
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE raw_taipower_load ADD COLUMN source VARCHAR(32)"))
    logger.warning(
        "Added nullable raw_taipower_load.source; rows with NULL source predate the "
        "regional snapshot derivation and must be removed by an operator."
    )


def _migrate_taipower_load_subject(engine: Engine) -> None:
    """Identify load series by prediction subject instead of a place name (ADR-0009).

    Rename and relabel share one transaction, so an interrupted upgrade never leaves
    a renamed column still holding the legacy value. The relabel is a no-op once
    migrated, which keeps every restart safe to repeat.
    """
    columns = _taipower_load_columns(engine, "subject migration")
    with engine.begin() as connection:
        if SUBJECT_COL not in columns:
            connection.execute(
                text(f"ALTER TABLE raw_taipower_load RENAME COLUMN location TO {SUBJECT_COL}")
            )
        relabelled = connection.execute(
            text(
                f"UPDATE raw_taipower_load SET {SUBJECT_COL} = :subject WHERE {SUBJECT_COL} = :legacy"
            ),
            {"subject": NATIONWIDE_SUBJECT, "legacy": LEGACY_NATIONWIDE_SUBJECT},
        ).rowcount
    if relabelled:
        logger.warning(
            "Relabelled %s raw_taipower_load rows from subject %r to %r.",
            relabelled,
            LEGACY_NATIONWIDE_SUBJECT,
            NATIONWIDE_SUBJECT,
        )


def _drop_cwa_header_status_columns(engine: Engine) -> None:
    """Drop the stored ``status`` column from CWA batch and release headers (#291).

    The missing list is the only record of CWA ingestion completeness; a stored status
    could contradict it. Neither header table is a hypertable, so a plain ``DROP COLUMN``
    works on SQLite and PostgreSQL alike. Tables already without the column are skipped,
    which keeps every restart safe to repeat. The API and Dagster both run this at
    startup, so on PostgreSQL the drop is ``IF EXISTS``: the column may vanish between
    inspection and drop. SQLite has no ``DROP COLUMN IF EXISTS``.
    """
    if_exists = "" if engine.dialect.name == "sqlite" else "IF EXISTS "
    inspector = inspect(engine)
    for table in CWA_HEADER_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        if LEGACY_CWA_HEADER_STATUS_COLUMN not in columns:
            continue
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"ALTER TABLE {table} DROP COLUMN {if_exists}{LEGACY_CWA_HEADER_STATUS_COLUMN}"
                )
            )
        logger.warning(
            "Dropped %s.%s; CWA ingestion completeness now derives from the missing list.",
            table,
            LEGACY_CWA_HEADER_STATUS_COLUMN,
        )


def convert_timescale_ddl_to_sqlite(ddl: str) -> list[str]:
    """Convert TimescaleDB/PostgreSQL DDL script into executable SQLite DDL statements.

    Strips comments and non-table TimescaleDB directives, and maps PostgreSQL types to
    SQLite-compatible types (TIMESTAMPTZ -> TIMESTAMP, NOW() -> CURRENT_TIMESTAMP, JSONB -> TEXT).

    Parameters
    ----------
    ddl : str
        The PostgreSQL / TimescaleDB DDL script.

    Returns
    -------
    list[str]
        List of SQLite CREATE TABLE statement strings.
    """
    statements: list[str] = []
    for cleaned in split_sql_statements(ddl):
        if not re.match(r"^\s*CREATE\s+TABLE", cleaned, re.IGNORECASE):
            continue
        # Apply PostgreSQL to SQLite dialect conversions
        cleaned = re.sub(r"\bTIMESTAMPTZ\b", "TIMESTAMP", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bJSONB\b", "TEXT", cleaned, flags=re.IGNORECASE)
        statements.append(cleaned)
    return statements


def get_sqlite_schema(sql_path: Path | None = None) -> str:
    """Return unified SQLite schema generated from TimescaleDB initialization DDL.

    Parameters
    ----------
    sql_path : Path | None
        Optional custom path to the SQL initialization file.

    Returns
    -------
    str
        SQLite DDL statements separated by semicolons and newlines.
    """
    ddl = get_timescale_init_ddl(sql_path=sql_path)
    statements = convert_timescale_ddl_to_sqlite(ddl)
    return "\n\n".join(stmt + ";" for stmt in statements)


try:
    SQLITE_DEFAULT_SCHEMA = get_sqlite_schema()
except FileNotFoundError:
    SQLITE_DEFAULT_SCHEMA = ""


def ensure_timescale_hypertables(engine: Engine | None = None) -> None:
    """Ensure database tables and TimescaleDB hypertables exist and are migrated safely.

    Idempotent and safe for both new and existing persistent data volumes.
    If tables already exist with rows, converts them to hypertables with migrate_data => TRUE.
    """
    db_engine = engine or get_timescale_engine()
    dialect_obj = getattr(db_engine, "dialect", None)
    dialect = getattr(dialect_obj, "name", "postgresql").lower()

    if dialect == "sqlite":
        statements = convert_timescale_ddl_to_sqlite(get_timescale_init_ddl())
        _execute_sql_statements(db_engine, statements)
        _run_schema_migrations(db_engine)
        return

    # PostgreSQL / TimescaleDB
    ddl = get_timescale_init_ddl()
    _execute_sql_statements(db_engine, split_sql_statements(ddl))
    _run_schema_migrations(db_engine)
    logger.info("TimescaleDB hypertables verified and initialized successfully.")


def _run_schema_migrations(engine: Engine) -> None:
    """Upgrade an existing schema in order; each step is a no-op once applied."""
    _isolate_legacy_cwa_weather(engine)
    _add_taipower_load_source_column(engine)
    _migrate_taipower_load_subject(engine)
    _drop_cwa_header_status_columns(engine)


def init_db(engine: Engine | None = None, sql_path: Path | None = None) -> None:
    """Initialize database tables and hypertables using the DDL script.

    Parameters
    ----------
    engine : Engine | None
        SQLAlchemy engine to execute DDL against. Defaults to get_timescale_engine().
    sql_path : Path | None
        Optional path to custom SQL script. If None, invokes ensure_timescale_hypertables().
    """
    db_engine = engine or get_timescale_engine()
    if sql_path is None:
        ensure_timescale_hypertables(db_engine)
        return

    ddl = get_timescale_init_ddl(sql_path=sql_path)
    _execute_sql_statements(db_engine, split_sql_statements(ddl))
    logger.info("Database initialization completed successfully.")
