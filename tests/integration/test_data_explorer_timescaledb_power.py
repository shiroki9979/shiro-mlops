"""Opt-in power pagination acceptance against an isolated local TimescaleDB."""

from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.unit.test_data_explorer_power import (
    assert_national_reader_pages,
    assert_regional_reader_pages,
    assert_unit_reader_pages,
)


def test_power_microsecond_and_composite_pages_on_timescaledb(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    repo = TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False)
    assert_national_reader_pages(repo)
    assert_regional_reader_pages(repo)
    assert_unit_reader_pages(repo)
