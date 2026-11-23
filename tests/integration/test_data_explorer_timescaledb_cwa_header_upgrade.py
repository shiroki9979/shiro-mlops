"""Opt-in CWA audit header acceptance against an isolated local TimescaleDB."""

import pytest
from sqlalchemy.engine import Engine

from tests.scenarios.cwa_header_upgrade import (
    CWA_HEADER_TABLES,
    LEGACY_STATUS_COLUMN,
    assert_header_status_drop_survives_a_concurrent_upgrade,
    assert_header_status_is_dropped_repeatably,
    header_columns,
)
from tests.scenarios.cwa_ingestion_status import (
    COMPLETENESS_CASES,
    assert_python_and_sql_judge_alike,
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


def test_concurrent_timescaledb_startups_both_drop_the_status_column(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    assert_header_status_drop_survives_a_concurrent_upgrade(data_explorer_timescaledb_engine)


@pytest.mark.parametrize(("missing_station_ids", "status"), COMPLETENESS_CASES)
def test_timescaledb_batch_completeness_reads_the_same_in_sql_as_in_python(
    data_explorer_timescaledb_engine: Engine, missing_station_ids: tuple[str, ...], status: str
) -> None:
    assert_python_and_sql_judge_alike(data_explorer_timescaledb_engine, missing_station_ids, status)
