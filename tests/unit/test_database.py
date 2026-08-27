"""Unit tests for TimescaleDB configuration, DDL initialization, and database helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import Settings
from shiro_mlops.core.database import get_timescale_engine, get_timescale_init_ddl, init_db


def test_settings_timescaledb_defaults():
    """Verify default TimescaleDB configuration settings and URI formatting."""
    settings = Settings()
    assert settings.TIMESCALE_HOST == "localhost"
    assert settings.TIMESCALE_PORT == 5432
    assert settings.TIMESCALE_DB == "mlflow"
    assert settings.TIMESCALE_USER == "postgres"
    assert settings.TIMESCALE_PASSWORD == "postgrespassword"
    assert settings.timescale_uri == "postgresql://postgres:postgrespassword@localhost:5432/mlflow"


def test_settings_timescaledb_env_override(monkeypatch):
    """Verify environment variables override TimescaleDB settings."""
    monkeypatch.setenv("TIMESCALE_HOST", "timescale.internal")
    monkeypatch.setenv("TIMESCALE_PORT", "5433")
    monkeypatch.setenv("TIMESCALE_DB", "shiro_timeseries")
    monkeypatch.setenv("TIMESCALE_USER", "shiro_user")
    monkeypatch.setenv("TIMESCALE_PASSWORD", "secret123")

    settings = Settings()
    assert settings.TIMESCALE_HOST == "timescale.internal"
    assert settings.TIMESCALE_PORT == 5433
    assert settings.TIMESCALE_DB == "shiro_timeseries"
    assert settings.TIMESCALE_USER == "shiro_user"
    assert settings.TIMESCALE_PASSWORD == "secret123"
    assert (
        settings.timescale_uri
        == "postgresql://shiro_user:secret123@timescale.internal:5433/shiro_timeseries"
    )


def test_timescale_init_ddl_content():
    """Verify TimescaleDB DDL contains required table schemas, primary keys, and hypertables."""
    ddl = get_timescale_init_ddl()

    assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in ddl
    assert "raw_taipower_load" in ddl
    assert "raw_cwa_weather" in ddl

    # Verify primary keys
    assert "PRIMARY KEY (time, location)" in ddl

    # Verify 7-day chunk intervals
    assert "chunk_time_interval => INTERVAL '7 days'" in ddl
    assert "create_hypertable" in ddl
    assert "'raw_taipower_load'" in ddl
    assert "'raw_cwa_weather'" in ddl


def test_timescale_init_ddl_file_not_found(tmp_path):
    """Verify get_timescale_init_ddl raises FileNotFoundError for missing path."""
    non_existent = tmp_path / "non_existent.sql"
    with pytest.raises(FileNotFoundError, match="DDL initialization script not found"):
        get_timescale_init_ddl(sql_path=non_existent)


def test_docker_init_sql_file_exists_and_matches():
    """Verify docker/init-db/01_init_hypertables.sql exists on disk and contains valid DDL."""
    sql_path = Path("docker/init-db/01_init_hypertables.sql")
    assert sql_path.exists(), f"Expected {sql_path} to exist"

    sql_content = sql_path.read_text(encoding="utf-8")
    assert "raw_taipower_load" in sql_content
    assert "raw_cwa_weather" in sql_content
    assert "PRIMARY KEY (time, location)" in sql_content
    assert "INTERVAL '7 days'" in sql_content


def test_get_timescale_engine():
    """Verify get_timescale_engine returns a SQLAlchemy Engine instance."""
    engine = get_timescale_engine(uri="sqlite:///:memory:")
    assert isinstance(engine, Engine)


def test_init_db_executes_ddl():
    """Verify init_db executes DDL statements on the provided engine."""
    mock_conn = MagicMock()
    mock_engine = MagicMock(spec=Engine)
    mock_engine.connect.return_value.__enter__.return_value = mock_conn

    init_db(mock_engine)

    assert mock_conn.execute.called
    assert mock_conn.commit.called


def test_init_db_with_sqlite_custom_ddl(tmp_path):
    """Verify init_db correctly executes custom multi-statement DDL on a real SQLite engine."""
    custom_ddl = (
        "CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT);"
        "INSERT INTO test_table (id, name) VALUES (1, 'sample');"
    )
    custom_sql_file = tmp_path / "test.sql"
    custom_sql_file.write_text(custom_ddl, encoding="utf-8")

    engine = create_engine("sqlite:///:memory:")
    init_db(engine=engine, sql_path=custom_sql_file)

    inspector = inspect(engine)
    assert "test_table" in inspector.get_table_names()
