"""TimescaleDB database connection helpers and schema initialization."""

import logging
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from shiro_mlops.core.config import settings
from shiro_mlops.core.schema_migrations import apply_schema_migrations
from shiro_mlops.core.storage_time import register_sqlite_datetime_adapter

logger = logging.getLogger(__name__)

CWA_OBSERVATION_BATCH_TABLE = "raw_cwa_observation_batch"
CWA_FORECAST_RELEASE_TABLE = "raw_cwa_forecast_release"

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

    Idempotent and safe for both new and existing persistent data volumes: the frozen
    baseline DDL runs first, then every schema migration the database has not recorded
    (src/shiro_mlops/core/schema_migrations.py). If tables already exist with rows,
    converts them to hypertables with migrate_data => TRUE.
    """
    db_engine = engine or get_timescale_engine()
    dialect_obj = getattr(db_engine, "dialect", None)
    dialect = getattr(dialect_obj, "name", "postgresql").lower()

    ddl = get_timescale_init_ddl()
    if dialect == "sqlite":
        _execute_sql_statements(db_engine, convert_timescale_ddl_to_sqlite(ddl))
        apply_schema_migrations(db_engine)
        return

    _execute_sql_statements(db_engine, split_sql_statements(ddl))
    apply_schema_migrations(db_engine)
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
