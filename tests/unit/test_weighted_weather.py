"""Weighted weather derives the forecast mode from every reference point's sources (ADR-0012)."""

import pandas as pd
import pytest

from shiro_mlops.data.weather_resolution import (
    ForecastMode,
    WeatherResolution,
    WeatherSourceKind,
    WeatherValueSource,
)
from shiro_mlops.tasks.weighted_weather import PointResolution, weighted_resolution

HOURS = pd.date_range("2026-08-20 12:00", periods=2, freq="h")
THREE_DAY = WeatherValueSource.forecast(
    WeatherSourceKind.THREE_DAY,
    pd.Series(
        {
            "dataset_id": "F-D0047-089",
            "issued_at": pd.Timestamp("2026-08-20 10:00"),
            "source_updated_at": pd.Timestamp("2026-08-20 10:10"),
        }
    ),
)
CLIMATOLOGY = WeatherValueSource.substitute(WeatherSourceKind.CLIMATOLOGY)


def _point(alias: str, weight: float, sources: list[WeatherValueSource]) -> PointResolution:
    frame = pd.DataFrame({"datetime": HOURS, "temperature": [30.0, 31.0]})
    resolution = WeatherResolution(frame, tuple({"temperature": source} for source in sources))
    return PointResolution(alias, weight, resolution)


def test_weighted_weather_is_normal_when_every_point_uses_forecasts() -> None:
    points = [
        _point("Taipei", 0.6, [THREE_DAY, THREE_DAY]),
        _point("Kaohsiung", 0.4, [THREE_DAY, THREE_DAY]),
    ]

    assert weighted_resolution(points, ["temperature"]).mode is ForecastMode.NORMAL


@pytest.mark.parametrize(
    ("taipei", "kaohsiung"),
    [
        ([THREE_DAY, THREE_DAY], [THREE_DAY, CLIMATOLOGY]),
        ([CLIMATOLOGY, THREE_DAY], [THREE_DAY, THREE_DAY]),
    ],
)
def test_weighted_weather_is_degraded_when_any_point_has_a_substitute_value(
    taipei: list[WeatherValueSource], kaohsiung: list[WeatherValueSource]
) -> None:
    points = [_point("Taipei", 0.6, taipei), _point("Kaohsiung", 0.4, kaohsiung)]

    assert weighted_resolution(points, ["temperature"]).mode is ForecastMode.DEGRADED
