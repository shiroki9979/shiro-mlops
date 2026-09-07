"""Unit tests for TimescaleDB configuration, DDL initialization, and database helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import Settings
from shiro_mlops.core.database import (
    SQLITE_DEFAULT_SCHEMA,
    convert_timescale_ddl_to_sqlite,
    get_sqlite_schema,
    get_timescale_engine,
    get_timescale_init_ddl,
    init_db,
)


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


def test_cwa_api_key_is_available_to_runtime_services() -> None:
    """Verify the CWA API key placeholder and Compose interpolation are wired safely."""
    env_example = Path(".env.example").read_text(encoding="utf-8")
    compose_content = Path("docker/docker-compose.yml").read_text(encoding="utf-8")

    assert "CWA_API_KEY=" in env_example
    assert "CWA_API_KEY: ${CWA_API_KEY:-}" in compose_content


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
    assert "legacy_cwa_weather" in ddl
    assert "raw_taipower_supply_demand_snapshot" in ddl
    assert "raw_taipower_regional_supply_demand_snapshot" in ddl
    assert "raw_taipower_unit_generation_snapshot" in ddl

    # Verify primary keys
    assert "PRIMARY KEY (time, location)" in ddl
    assert "PRIMARY KEY (observed_at)" in ddl
    assert "PRIMARY KEY (observed_at, region)" in ddl
    assert "PRIMARY KEY (observed_at, unit_type, unit_name)" in ddl

    # Verify 7-day chunk intervals
    assert "chunk_time_interval => INTERVAL '7 days'" in ddl
    assert "create_hypertable" in ddl
    assert "'raw_taipower_load'" in ddl
    assert "'legacy_cwa_weather'" in ddl
    assert "'raw_taipower_supply_demand_snapshot'" in ddl
    assert "'raw_taipower_regional_supply_demand_snapshot'" in ddl
    assert "'raw_taipower_unit_generation_snapshot'" in ddl


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
    assert "legacy_cwa_weather" in sql_content
    assert "raw_taipower_supply_demand_snapshot" in sql_content
    assert "raw_taipower_regional_supply_demand_snapshot" in sql_content
    assert "raw_taipower_unit_generation_snapshot" in sql_content
    assert "PRIMARY KEY (time, location)" in sql_content
    assert "PRIMARY KEY (observed_at)" in sql_content
    assert "PRIMARY KEY (observed_at, region)" in sql_content
    assert "PRIMARY KEY (observed_at, unit_type, unit_name)" in sql_content
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
    # Ensure hypertables have migrate_data set
    assert content.count("migrate_data => TRUE") >= 5


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
        assert "legacy_cwa_weather" in tables
        assert "raw_taipower_supply_demand_snapshot" in tables
        assert "raw_taipower_regional_supply_demand_snapshot" in tables
        assert "raw_taipower_unit_generation_snapshot" in tables

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


def test_ensure_timescale_hypertables_moves_old_weather_rows_to_legacy_storage(tmp_path) -> None:
    """An existing ambiguous weather table must not survive as a canonical-looking source."""
    from shiro_mlops.core.database import ensure_timescale_hypertables

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy_weather.db'}")
    try:
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
            connection.execute(
                text(
                    """
                    INSERT INTO raw_cwa_weather (time, location, temperature, relative_humidity)
                    VALUES ('2026-08-20 00:00:00', 'Unknown', 27.0, 80.0)
                    """
                )
            )

        ensure_timescale_hypertables(engine)

        inspector = inspect(engine)
        assert "raw_cwa_weather" not in inspector.get_table_names()
        assert "legacy_cwa_weather" in inspector.get_table_names()
        with engine.connect() as connection:
            rows = connection.execute(text("SELECT location FROM legacy_cwa_weather")).fetchall()
        assert rows == [("Unknown",)]
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


def test_repository_auto_init_false_does_not_initialize_schema(tmp_path):
    """Verify externally managed schemas are untouched when auto initialization is disabled."""
    from shiro_mlops.data.repository import TimeSeriesRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'externally_managed.db'}")
    try:
        TimeSeriesRepository(engine=engine, auto_init=False)

        assert inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_convert_timescale_ddl_to_sqlite_statements():
    """Verify TimescaleDB DDL is cleanly converted to SQLite compatible DDL."""
    ddl = """
    -- Extension
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

    -- Table
    CREATE TABLE IF NOT EXISTS test_snapshot (
        observed_at TIMESTAMPTZ NOT NULL,
        data JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (observed_at)
    );

    SELECT create_hypertable('test_snapshot', 'observed_at');
    """
    stmts = convert_timescale_ddl_to_sqlite(ddl)
    assert len(stmts) == 1
    stmt = stmts[0]
    assert "CREATE TABLE IF NOT EXISTS test_snapshot" in stmt
    assert "observed_at TIMESTAMP NOT NULL" in stmt
    assert "data TEXT NOT NULL" in stmt
    assert "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in stmt
    assert "PRIMARY KEY (observed_at)" in stmt
    assert "timescaledb" not in stmt
    assert "create_hypertable" not in stmt


def test_sqlite_and_timescale_schema_parity(tmp_path):
    """Verify SQLite schema dynamically derived from 01_init_hypertables.sql has 100% parity."""
    import re

    from shiro_mlops.core.database import ensure_timescale_hypertables

    db_path = tmp_path / "parity.db"
    engine = create_engine(f"sqlite:///{db_path}")

    try:
        ensure_timescale_hypertables(engine)
        inspector = inspect(engine)
        sqlite_tables = set(inspector.get_table_names())

        ddl = get_timescale_init_ddl()
        table_matches = re.findall(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\((.*?)\);",
            ddl,
            re.DOTALL | re.IGNORECASE,
        )
        assert len(table_matches) >= 5

        for table_name, body in table_matches:
            # 1. Verify table exists in SQLite
            assert table_name in sqlite_tables, f"Table {table_name} missing in SQLite"

            # 2. Verify Primary Key constraints match
            pk_match = re.search(r"PRIMARY\s+KEY\s*\((.*?)\)", body, re.IGNORECASE)
            assert pk_match, f"No PRIMARY KEY found in DDL for {table_name}"
            expected_pk = [col.strip() for col in pk_match.group(1).split(",")]
            actual_pk = inspector.get_pk_constraint(table_name)["constrained_columns"]
            assert expected_pk == actual_pk, (
                f"PK mismatch for {table_name}: {expected_pk} vs {actual_pk}"
            )

            # 3. Verify ALL columns and NOT NULL constraints across all tables
            db_cols = {c["name"]: c for c in inspector.get_columns(table_name)}
            for line in body.splitlines():
                line = line.strip().rstrip(",")
                if not line or line.upper().startswith("PRIMARY KEY"):
                    continue
                parts = line.split()
                col_name = parts[0]
                assert col_name in db_cols, f"Column {col_name} missing from table {table_name}"
                is_not_null = "NOT NULL" in line.upper()
                assert (not db_cols[col_name]["nullable"]) == is_not_null, (
                    f"Nullability mismatch for {table_name}.{col_name}"
                )
    finally:
        engine.dispose()


def test_sqlite_test_schema_matches_production_ddl(tmp_path):
    """Verify test fixtures utilizing SQLITE_TEST_SCHEMA create tables matching production DDL."""
    import importlib.util
    import re

    conftest_path = Path(__file__).resolve().parents[1] / "conftest.py"
    spec = importlib.util.spec_from_file_location("test_conftest", conftest_path)
    assert spec is not None and spec.loader is not None
    conftest_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conftest_mod)

    derived_schema = get_sqlite_schema()
    assert SQLITE_DEFAULT_SCHEMA.strip() == derived_schema.strip()
    test_schema = getattr(conftest_mod, "SQLITE_TEST_SCHEMA").strip()
    assert test_schema == derived_schema.strip()

    # Verify execution of SQLITE_TEST_SCHEMA yields all production tables
    engine = create_engine(f"sqlite:///{tmp_path / 'conftest_test.db'}")
    try:
        from shiro_mlops.core.database import _execute_sql_statements

        _execute_sql_statements(engine, test_schema.split(";"))
        inspector = inspect(engine)
        ddl = get_timescale_init_ddl()
        expected_tables = set(
            re.findall(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)",
                ddl,
                re.IGNORECASE,
            )
        )
        assert expected_tables.issubset(set(inspector.get_table_names()))
    finally:
        engine.dispose()


def test_new_table_in_ddl_automatically_propagates_to_sqlite(tmp_path):
    """Verify adding a new hypertable to DDL automatically produces valid SQLite schema."""
    custom_ddl = """
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

    CREATE TABLE IF NOT EXISTS raw_future_snapshot (
        observed_at TIMESTAMPTZ NOT NULL,
        feature_val DOUBLE PRECISION NOT NULL,
        meta JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        PRIMARY KEY (observed_at)
    );

    SELECT create_hypertable('raw_future_snapshot', 'observed_at');
    """
    stmts = convert_timescale_ddl_to_sqlite(custom_ddl)
    assert len(stmts) == 1

    engine = create_engine(f"sqlite:///{tmp_path / 'future.db'}")
    try:
        with engine.connect() as conn:
            for s in stmts:
                conn.execute(text(s))
            conn.commit()

        inspector = inspect(engine)
        assert "raw_future_snapshot" in inspector.get_table_names()
        pk = inspector.get_pk_constraint("raw_future_snapshot")
        assert pk["constrained_columns"] == ["observed_at"]
    finally:
        engine.dispose()
