"""Observation audit pages retain raw timestamp precision."""

from shiro_mlops.data.repository import TimeSeriesRepository
from tests.scenarios.data_explorer_audit import assert_observation_audit_pages


def test_observation_audit_pages_preserve_microseconds(test_repo: TimeSeriesRepository) -> None:
    assert_observation_audit_pages(test_repo)
