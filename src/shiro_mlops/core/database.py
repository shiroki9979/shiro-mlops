"""TimescaleDB database connection helpers and schema initialization."""

import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

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


def convert_timescale_ddl_to_sqlite(ddl: str) -> list[str]:
    """Convert TimescaleDB/PostgreSQL DDL script into executable SQLite DDL statements.

    Strips comments, TimescaleDB-specific extension and hypertable commands,
    and maps PostgreSQL types to SQLite-compatible types (TIMESTAMPTZ -> TIMESTAMP,
    NOW() -> CURRENT_TIMESTAMP, JSONB -> TEXT).

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
    for chunk in ddl.split(";"):
        cleaned = "\n".join(
            line for line in chunk.splitlines() if not line.strip().startswith("--")
        ).strip()
        if not cleaned:
            continue
        if re.match(r"^\s*(CREATE\s+EXTENSION|SELECT\s+create_hypertable)", cleaned, re.IGNORECASE):
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


SQLITE_DEFAULT_SCHEMA = get_sqlite_schema()


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
        with db_engine.connect() as conn:
            for statement in statements:
                cleaned = statement.strip()
                if cleaned:
                    conn.execute(text(cleaned))
            conn.commit()
        return

    # PostgreSQL / TimescaleDB
    ddl = get_timescale_init_ddl()
    with db_engine.connect() as conn:
        for statement in ddl.split(";"):
            cleaned = statement.strip()
            if cleaned:
                conn.execute(text(cleaned))
        conn.commit()
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
    with db_engine.connect() as conn:
        for statement in ddl.split(";"):
            cleaned_stmt = statement.strip()
            if cleaned_stmt:
                conn.execute(text(cleaned_stmt))
        conn.commit()
    logger.info("Database initialization completed successfully.")
