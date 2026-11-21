"""Data Explorer weather series HTTP contract on a real SQLite repository."""

import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_weather_series import WEATHER_SERIES_SCENARIOS


@pytest.mark.parametrize(
    "scenario", WEATHER_SERIES_SCENARIOS, ids=lambda scenario: scenario.__name__
)
def test_weather_series_scenarios_on_sqlite(scenario, test_repo: TimeSeriesRepository) -> None:
    scenario(test_repo)
