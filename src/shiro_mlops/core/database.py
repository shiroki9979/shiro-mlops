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


SQLITE_DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_taipower_load (
    time TIMESTAMP NOT NULL,
    location VARCHAR(64) NOT NULL,
    load_mw DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (time, location)
);

CREATE TABLE IF NOT EXISTS raw_cwa_weather (
    time TIMESTAMP NOT NULL,
    location VARCHAR(64) NOT NULL,
    temperature DOUBLE PRECISION,
    relative_humidity DOUBLE PRECISION,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (time, location)
);

CREATE TABLE IF NOT EXISTS raw_taipower_supply_demand_snapshot (
    observed_at TIMESTAMP NOT NULL,
    source_publish_time TIMESTAMP,
    curr_load_wan_kw DOUBLE PRECISION NOT NULL,
    curr_util_rate_pct DOUBLE PRECISION NOT NULL,
    fore_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_dema_load_wan_kw DOUBLE PRECISION,
    fore_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    fore_peak_resv_rate_pct DOUBLE PRECISION,
    fore_peak_resv_indicator VARCHAR(8),
    fore_peak_hour_range VARCHAR(32),
    yday_date DATE,
    yday_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_dema_load_wan_kw DOUBLE PRECISION,
    yday_peak_resv_capacity_wan_kw DOUBLE PRECISION,
    yday_peak_resv_rate_pct DOUBLE PRECISION,
    yday_peak_resv_indicator VARCHAR(8),
    real_hr_maxi_sply_capacity_wan_kw DOUBLE PRECISION,
    real_hr_peak_time TIMESTAMP,
    raw_payload TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (observed_at)
);
"""


def ensure_timescale_hypertables(engine: Engine | None = None) -> None:
    """Ensure database tables and TimescaleDB hypertables exist and are migrated safely.

    Idempotent and safe for both new and existing persistent data volumes.
    If tables already exist with rows, converts them to hypertables with migrate_data => TRUE.
    """
    db_engine = engine or get_timescale_engine()
    dialect_obj = getattr(db_engine, "dialect", None)
    dialect = getattr(dialect_obj, "name", "postgresql").lower()

    if dialect == "sqlite":
        with db_engine.connect() as conn:
            for statement in SQLITE_DEFAULT_SCHEMA.split(";"):
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
