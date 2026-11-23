"""Opt-in CWA audit header upgrade acceptance against an isolated local TimescaleDB."""

from sqlalchemy.engine import Engine

from tests.scenarios.cwa_header_upgrade import (
    CWA_HEADER_TABLES,
    LEGACY_STATUS_COLUMN,
    assert_header_status_is_dropped_repeatably,
    header_columns,
)


def test_fresh_timescaledb_cwa_headers_have_no_status_column(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    for table in CWA_HEADER_TABLES:
        assert LEGACY_STATUS_COLUMN not in header_columns(data_explorer_timescaledb_engine, table)


def test_existing_timescaledb_cwa_headers_lose_status_column_repeatably(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    assert_header_status_is_dropped_repeatably(data_explorer_timescaledb_engine)
