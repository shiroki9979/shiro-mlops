"""TimescaleDB database connection helpers and schema initialization."""

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoInspectionAvailable

from shiro_mlops.core.config import settings

logger = logging.getLogger(__name__)

INIT_SQL_PATH = (
    Path(__file__).resolve().parents[3] / "docker" / "init-db" / "01_init_hypertables.sql"
)


def get_timescale_init_ddl(sql_path: Path | None = None) -> str:
    """Return the SQL DDL string used to initialize TimescaleDB hypertables.

    Parameters
    ----------
    sql_path : Path | None
        Optional custom path to the SQL initialization file.

    Returns
    -------
    str
        Contents of the initialization SQL file.
    """
    target_path = sql_path or INIT_SQL_PATH
    if not target_path.exists():
        raise FileNotFoundError(f"DDL initialization script not found at {target_path}")
    return target_path.read_text(encoding="utf-8")


def get_timescale_engine(uri: str | None = None, **kwargs: Any) -> Engine:
    """Create and return a SQLAlchemy Engine for TimescaleDB.

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
    engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
    engine_kwargs.update(kwargs)
    return create_engine(db_uri, **engine_kwargs)


def _strip_line_comments(sql: str) -> str:
    """移除整行 SQL 註解，避免其內容被當成可執行語句。"""
    return "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))


def split_sql_statements(ddl: str) -> list[str]:
    """將 DDL 切分為可執行語句，略過純註解片段。"""
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


def _add_taipower_load_source_column(engine: Engine) -> None:
    """Add the derivation provenance column to load tables created before ADR-0008.

    The column stays nullable on upgraded databases: NULL identifies d015046-era
    rows so operators can review and remove them before NOT NULL is enforced
    (docs/how-to/remove-legacy-d015046-load-rows.md). Existing rows are never
    rewritten here because relabelling them would mix incompatible load semantics.
    """
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("raw_taipower_load")}
    except NoInspectionAvailable:
        return
    if "source" in columns:
        return
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE raw_taipower_load ADD COLUMN source VARCHAR(32)"))
    logger.warning(
        "Added nullable raw_taipower_load.source; rows with NULL source predate the "
        "regional snapshot derivation and must be removed by an operator."
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
        _isolate_legacy_cwa_weather(db_engine)
        _add_taipower_load_source_column(db_engine)
        return

    # PostgreSQL / TimescaleDB
    ddl = get_timescale_init_ddl()
    _execute_sql_statements(db_engine, split_sql_statements(ddl))
    _isolate_legacy_cwa_weather(db_engine)
    _add_taipower_load_source_column(db_engine)
    logger.info("TimescaleDB hypertables verified and initialized successfully.")


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
