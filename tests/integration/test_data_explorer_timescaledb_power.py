"""Opt-in power pagination acceptance against an isolated local TimescaleDB."""

from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_gaps import (
    assert_regional_gaps_list_zero_region_slots_on_every_page,
)
from tests.scenarios.data_explorer_power import (
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


def test_regional_zero_region_gaps_over_http_on_timescaledb(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    repo = TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False)
    assert_regional_gaps_list_zero_region_slots_on_every_page(repo)
