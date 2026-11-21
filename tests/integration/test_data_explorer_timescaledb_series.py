"""Opt-in series HTTP acceptance against an isolated local TimescaleDB."""

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_audit_series import AUDIT_SERIES_SCENARIOS
from tests.scenarios.data_explorer_series import SERIES_SCENARIOS
from tests.scenarios.data_explorer_unit_series import UNIT_SERIES_SCENARIOS


@pytest.mark.parametrize("data_explorer_timescaledb_engine", ["Asia/Taipei"], indirect=True)
@pytest.mark.parametrize("scenario", SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_series_scenarios_on_timescaledb(
    scenario, data_explorer_timescaledb_engine: Engine
) -> None:
    scenario(TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False))


@pytest.mark.parametrize("data_explorer_timescaledb_engine", ["Asia/Taipei"], indirect=True)
@pytest.mark.parametrize("scenario", AUDIT_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_audit_series_scenarios_on_timescaledb(
    scenario, data_explorer_timescaledb_engine: Engine
) -> None:
    scenario(TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False))


@pytest.mark.parametrize("data_explorer_timescaledb_engine", ["Asia/Taipei"], indirect=True)
@pytest.mark.parametrize("scenario", UNIT_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_unit_series_scenarios_on_timescaledb(
    scenario, data_explorer_timescaledb_engine: Engine
) -> None:
    scenario(TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False))
