"""Opt-in Data Explorer pagination acceptance against an isolated local TimescaleDB."""

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_audit import assert_observation_audit_pages
from tests.scenarios.data_explorer_forecast import (
    assert_forecast_audit_pages_keep_complete_sort_key,
    assert_forecast_pages_pin_microsecond_vintage,
)
from tests.scenarios.data_explorer_windows import (
    assert_all_dataset_windows,
    assert_completeness_windows,
)


def test_observation_audit_microsecond_pages_on_timescaledb(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    repo = TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False)
    assert_observation_audit_pages(repo)


def test_forecast_pages_on_timescaledb(data_explorer_timescaledb_engine: Engine) -> None:
    repo = TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False)
    assert_forecast_pages_pin_microsecond_vintage(repo)
    assert_forecast_audit_pages_keep_complete_sort_key(repo)


@pytest.mark.parametrize("data_explorer_timescaledb_engine", ["Asia/Taipei"], indirect=True)
def test_exact_windows_on_timescaledb_with_non_utc_session(
    data_explorer_timescaledb_engine: Engine,
) -> None:
    assert_all_dataset_windows(data_explorer_timescaledb_engine)
    assert_completeness_windows(data_explorer_timescaledb_engine)
