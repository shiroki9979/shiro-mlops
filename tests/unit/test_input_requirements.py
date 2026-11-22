"""Input requirements: every task type must state its load history coverage explicitly."""

import pytest

from shiro_mlops.tasks.types.base import InputRequirements, WeatherInput


def test_requirements_without_history_coverage_fail_at_construction() -> None:
    """Omitting the coverage must not silently skip the lookback completeness check (#226)."""
    with pytest.raises(TypeError, match="history_coverage"):
        InputRequirements(weather=WeatherInput.FORECAST, lookback_hours=168)  # type: ignore[call-arg]
