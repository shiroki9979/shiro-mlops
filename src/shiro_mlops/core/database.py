"""TimescaleDB database connection helpers and schema initialization."""

import logging
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


def init_db(engine: Engine | None = None, sql_path: Path | None = None) -> None:
    """Initialize database tables and hypertables using the DDL script.

    Parameters
    ----------
    engine : Engine | None
        SQLAlchemy engine to execute DDL against. Defaults to get_timescale_engine().
    sql_path : Path | None
        Optional path to custom SQL script. Defaults to docker/init-db/01_init_hypertables.sql.
    """
    db_engine = engine or get_timescale_engine()
    ddl = get_timescale_init_ddl(sql_path=sql_path)

    with db_engine.connect() as conn:
        for statement in ddl.split(";"):
            cleaned_stmt = statement.strip()
            if cleaned_stmt:
                conn.execute(text(cleaned_stmt))
        conn.commit()
    logger.info("Database initialization completed successfully.")
