"""Unit tests for TimescaleDB configuration, DDL initialization, and database helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import Settings
from shiro_mlops.core.database import get_timescale_engine, get_timescale_init_ddl, init_db


def test_settings_timescaledb_defaults():
    """Verify default TimescaleDB configuration settings and URI formatting."""
    settings = Settings()
    assert settings.TIMESCALE_HOST == "localhost"
    assert settings.TIMESCALE_PORT == 5432
    assert settings.TIMESCALE_DB == "shiro_timeseries"
    assert settings.TIMESCALE_USER == "postgres"
    assert settings.TIMESCALE_PASSWORD == "postgrespassword"
    assert (
        settings.timescale_uri
        == "postgresql://postgres:postgrespassword@localhost:5432/shiro_timeseries"
    )


def test_database_contract_consistency():
    """Verify TimescaleDB database name is unified across config, compose, and .env.example."""
    settings = Settings()
    expected_db = "shiro_timeseries"
    assert settings.TIMESCALE_DB == expected_db

    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert f"TIMESCALE_DB={expected_db}" in env_example

    compose_content = Path("docker/docker-compose.yml").read_text(encoding="utf-8")
    assert f"POSTGRES_DB: {expected_db}" in compose_content
    assert f"/{expected_db}" in compose_content


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


def test_get_timescale_engine(tmp_path):
    """Verify get_timescale_engine returns a SQLAlchemy Engine instance."""
    engine = get_timescale_engine(uri=f"sqlite:///{tmp_path / 'test_engine.db'}")
    assert isinstance(engine, Engine)
    engine.dispose()


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

    engine = create_engine(f"sqlite:///{tmp_path / 'custom_ddl.db'}")
    try:
        init_db(engine=engine, sql_path=custom_sql_file)

        inspector = inspect(engine)
        assert "test_table" in inspector.get_table_names()
    finally:
        engine.dispose()


def test_timescale_ddl_contains_migrate_data():
    """Verify TimescaleDB DDL specifies migrate_data => TRUE for existing volumes."""
    sql_path = Path("docker/init-db/01_init_hypertables.sql")
    content = sql_path.read_text(encoding="utf-8")
    assert "migrate_data => TRUE" in content
    # Ensure both tables have migrate_data set
    assert content.count("migrate_data => TRUE") >= 2


def test_ensure_timescale_hypertables_creates_tables_and_is_idempotent(tmp_path):
    """Verify ensure_timescale_hypertables creates tables and preserves data across repeated calls."""
    from shiro_mlops.core.database import ensure_timescale_hypertables

    db_path = tmp_path / "persistent_volume.db"
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        # 1. Initial creation
        ensure_timescale_hypertables(engine)
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "raw_taipower_load" in tables
        assert "raw_cwa_weather" in tables

        # 2. Populate existing volume with data
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO raw_taipower_load (time, location, load_mw) "
                    "VALUES ('2026-08-20 00:00:00', 'Taipei', 26500.0)"
                )
            )
            conn.commit()

        # 3. Simulate upgrade/restart on existing volume
        ensure_timescale_hypertables(engine)
        ensure_timescale_hypertables(engine)

        # 4. Verify existing data preserved and not corrupted or duplicated
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM raw_taipower_load")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == "Taipei"
            assert rows[0][2] == 26500.0
    finally:
        engine.dispose()


def test_repository_auto_init_on_existing_volume(tmp_path):
    """Verify TimeSeriesRepository auto_init smoothly handles fresh and existing database volumes."""
    from shiro_mlops.data.repository import TimeSeriesRepository

    db_path = tmp_path / "repo_volume.db"
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        # Launch repo against fresh volume
        repo1 = TimeSeriesRepository(engine=engine, auto_init=True)
        sample_df = pd.DataFrame(
            [{"datetime": "2026-08-20 00:00:00", "load_mw": 30000.0, "location": "Taipei"}]
        )
        repo1.upsert_taipower_load(sample_df)

        # Launch new repo instance against existing volume (service reboot)
        repo2 = TimeSeriesRepository(engine=engine, auto_init=True)
        persisted = repo2.fetch_load_range(location="Taipei")
        assert len(persisted) == 1
        assert persisted.iloc[0]["load_mw"] == 30000.0
    finally:
        engine.dispose()
