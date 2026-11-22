"""Opt-in weather series HTTP acceptance against an isolated local TimescaleDB."""

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_weather_series import WEATHER_SERIES_SCENARIOS


@pytest.mark.parametrize("data_explorer_timescaledb_engine", ["Asia/Taipei"], indirect=True)
@pytest.mark.parametrize(
    "scenario", WEATHER_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__
)
def test_weather_series_scenarios_on_timescaledb(
    scenario, data_explorer_timescaledb_engine: Engine
) -> None:
    scenario(TimeSeriesRepository(engine=data_explorer_timescaledb_engine, auto_init=False))
