"""Tests for point-in-time CWA forecast resolution."""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd

from shiro_mlops.data.weather_resolution import resolve_weather


def test_resolver_prefers_three_day_and_falls_back_to_weekly_per_field() -> None:
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
        [
            {
                "dataset_id": "F-D0047-089",
                "issued_at": pd.Timestamp("2026-08-20 10:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 10:10"),
                "valid_from": pd.Timestamp("2026-08-20 12:00"),
                "valid_to": pd.Timestamp("2026-08-20 12:00"),
                "geocode": "63000050",
                "temperature_c": 30.0,
                "relative_humidity_pct": None,
            },
            {
                "dataset_id": "F-D0047-091",
                "issued_at": pd.Timestamp("2026-08-20 09:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 09:05"),
                "valid_from": pd.Timestamp("2026-08-20 12:00"),
                "valid_to": pd.Timestamp("2026-08-20 15:00"),
                "geocode": "63000050",
                "temperature_c": 29.0,
                "relative_humidity_pct": 70.0,
            },
        ]
    )
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame()

    result = resolve_weather(
        repository,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 11),
    )

    assert result.mode == "normal"
    assert result.dataframe.loc[0, "temperature"] == 30.0
    assert result.dataframe.loc[0, "relative_humidity"] == 70.0
    assert result.sources[0]["temperature"]["source"] == "three_day"
    assert result.sources[0]["relative_humidity"]["source"] == "weekly"


def test_resolver_uses_previous_day_observation_when_forecast_is_stale() -> None:
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
        [
            {
                "dataset_id": "F-D0047-089",
                "issued_at": pd.Timestamp("2026-08-20 01:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 01:05"),
                "valid_from": pd.Timestamp("2026-08-20 12:00"),
                "valid_to": pd.Timestamp("2026-08-20 12:00"),
                "geocode": "63000050",
                "temperature_c": 30.0,
                "relative_humidity_pct": 70.0,
            }
        ]
    )
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-19 12:00"),
                "station_id": "466920",
                "temperature_c": 28.0,
                "relative_humidity_pct": 75.0,
            }
        ]
    )

    result = resolve_weather(
        repository,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.mode == "degraded"
    assert result.dataframe.loc[0, "temperature"] == 28.0
    assert result.dataframe.loc[0, "relative_humidity"] == 75.0
    assert result.sources[0]["temperature"]["source"] == "previous_day_observation"
