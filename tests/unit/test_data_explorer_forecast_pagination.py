"""Forecast pages retain complete keys and the resolved vintage across requests."""

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_forecast import (
    assert_forecast_audit_pages_keep_complete_sort_key,
    assert_forecast_pages_pin_microsecond_vintage,
)


def test_forecast_pages_pin_microsecond_vintage(test_repo: TimeSeriesRepository) -> None:
    assert_forecast_pages_pin_microsecond_vintage(test_repo)


def test_forecast_audit_pages_keep_complete_sort_key(test_repo: TimeSeriesRepository) -> None:
    assert_forecast_audit_pages_keep_complete_sort_key(test_repo)
