"""Tests for point-in-time CWA forecast resolution."""

from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from shiro_mlops.core.config import Settings
from shiro_mlops.data.cwa_client import CWALocation
from shiro_mlops.data.weather_resolution import resolve_weather

TAIPEI = CWALocation("Taipei", "466920", "63000000")


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
        reference_point=TAIPEI,
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
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.mode == "degraded"
    assert result.dataframe.loc[0, "temperature"] == 28.0
    assert result.dataframe.loc[0, "relative_humidity"] == 75.0
    assert result.sources[0]["temperature"]["source"] == "previous_day_observation"


def test_resolver_does_not_read_observations_after_the_as_of_time() -> None:
    """Degraded backtests may only use observations that already existed at prediction time."""
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame()
    as_of = datetime(2026, 8, 20, 12)

    resolve_weather(
        repository,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 13),
        horizon_hours=24,
        as_of=as_of,
    )

    assert repository.fetch_cwa_station_observations.call_args.kwargs["end_time"] == as_of
    assert repository.fetch_cwa_forecast_rows.call_args.kwargs["source_updated_before"] == as_of


def test_resolver_does_not_interpolate_wind_direction() -> None:
    """Categorical wind direction may be exact but must never be fabricated between points."""
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
        [
            {
                "dataset_id": "F-D0047-089",
                "issued_at": pd.Timestamp("2026-08-20 10:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 10:00"),
                "valid_from": pd.Timestamp("2026-08-20 12:00"),
                "valid_to": pd.Timestamp("2026-08-20 12:00"),
                "geocode": "63000050",
                "wind_direction": "East",
            },
            {
                "dataset_id": "F-D0047-089",
                "issued_at": pd.Timestamp("2026-08-20 10:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 10:00"),
                "valid_from": pd.Timestamp("2026-08-20 14:00"),
                "valid_to": pd.Timestamp("2026-08-20 14:00"),
                "geocode": "63000050",
                "wind_direction": "West",
            },
        ]
    )
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame()

    result = resolve_weather(
        repository,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 13),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 11),
        fields=("wind_direction",),
    )

    assert result.mode == "unavailable"


def test_resolver_reads_forecasts_and_observations_of_the_weather_reference_point() -> None:
    """天氣以氣象代表點的鄉鎮預報區與測站取值，而非固定的臺北代碼。"""
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-19 12:00"),
                "station_id": "467441",
                "temperature_c": 31.0,
                "relative_humidity_pct": 68.0,
            }
        ]
    )
    kaohsiung = CWALocation("Kaohsiung", "467441", "64000000")

    result = resolve_weather(
        repository,
        reference_point=kaohsiung,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert repository.fetch_cwa_forecast_rows.call_args.kwargs["geocode"] == "64000000"
    assert repository.fetch_cwa_station_observations.call_args.kwargs["station_id"] == "467441"
    assert result.dataframe.loc[0, "temperature"] == 31.0


def test_weather_reference_point_resolves_alias_from_ingestion_catalog() -> None:
    settings = Settings(
        CWA_LOCATION_ALLOWLIST='{"Hualien": {"station_id": "466990", "geocode": "10015000"}}'
    )

    assert settings.weather_reference_point("Hualien") == CWALocation(
        "Hualien", "466990", "10015000"
    )
    with pytest.raises(ValueError, match="not in the CWA ingestion catalog"):
        settings.weather_reference_point("Taipei")
