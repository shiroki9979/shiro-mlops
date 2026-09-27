"""Tests for point-in-time CWA forecast resolution."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from shiro_mlops.core.config import Settings, settings
from shiro_mlops.data.cwa_client import CWALocation
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import resolve_weather
from tests.helpers import forecast_release, township_forecast

TAIPEI = CWALocation("Taipei", "466920", "63000000")


@pytest.mark.parametrize("hour", [14, 15, 16])
def test_resolver_falls_back_to_weekly_around_a_missing_forecast_point(
    test_repo: TimeSeriesRepository, hour: int
) -> None:
    points = tuple(
        replace(
            township_forecast(datetime(2026, 8, 20, time), temperature),
            geocode=TAIPEI.geocode,
        )
        for time, temperature in ((12, 30.0), (15, None), (18, 36.0))
    )
    test_repo.upsert_cwa_forecast_release(forecast_release(datetime(2026, 8, 20, 10), points))
    weekly = replace(
        township_forecast(datetime(2026, 8, 20, 12), 22.0),
        valid_to=datetime(2026, 8, 20, 19),
        geocode=TAIPEI.geocode,
    )
    test_repo.upsert_cwa_forecast_release(
        replace(forecast_release(datetime(2026, 8, 20, 10), (weekly,)), dataset_id="F-D0047-091")
    )

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, hour),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 14),
        fields=("temperature",),
    )

    assert result.dataframe.loc[0, "temperature"] == 22.0
    assert result.sources[0]["temperature"]["source"] == "weekly"


def test_resolver_interpolates_short_horizon_between_persisted_forecast_points(
    test_repo: TimeSeriesRepository,
) -> None:
    geocode = TAIPEI.geocode
    points = tuple(
        replace(
            township_forecast(datetime(2026, 8, 20, hour), temperature, relative_humidity_pct=70.0),
            geocode=geocode,
        )
        for hour, temperature in ((12, 30.0), (15, 33.0))
    )
    test_repo.upsert_cwa_forecast_release(forecast_release(datetime(2026, 8, 20, 9), points))
    # A future release must not supply either interpolation endpoint.
    test_repo.upsert_cwa_forecast_release(
        forecast_release(
            datetime(2026, 8, 20, 14),
            tuple(replace(point, temperature_c=99.0) for point in points),
        )
    )

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 13),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 13),
    )

    assert result.mode == "normal"
    assert result.dataframe["temperature"].tolist() == [31.0]
    assert result.dataframe["relative_humidity"].tolist() == [70.0]
    assert result.sources[0]["temperature"]["source"] == "three_day"


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


def test_resolver_uses_configured_taipei_forecast_and_observation_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings,
        "CWA_LOCATION_ALLOWLIST",
        '{"Taipei": {"station_id": "999999", "geocode": "99999999"}}',
    )
    repository = MagicMock()
    forecast = pd.DataFrame(
        [
            {
                "dataset_id": "F-D0047-089",
                "issued_at": pd.Timestamp("2026-08-20 10:00"),
                "source_updated_at": pd.Timestamp("2026-08-20 10:10"),
                "valid_from": pd.Timestamp("2026-08-20 12:00"),
                "valid_to": pd.Timestamp("2026-08-20 12:00"),
                "geocode": "99999999",
                "temperature_c": 30.0,
                "relative_humidity_pct": None,
            }
        ]
    )
    observation = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-19 12:00"),
                "station_id": "999999",
                "temperature_c": 28.0,
                "relative_humidity_pct": 70.0,
            }
        ]
    )
    repository.fetch_cwa_forecast_rows.side_effect = lambda **kwargs: (
        forecast if kwargs["geocode"] == "99999999" else pd.DataFrame()
    )
    repository.fetch_cwa_station_observations.side_effect = lambda **kwargs: (
        observation if kwargs["station_id"] == "999999" else pd.DataFrame()
    )

    result = resolve_weather(
        repository,
        reference_point=settings.weather_reference_point("Taipei"),
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 11),
    )

    assert result.dataframe.loc[0, "temperature"] == 30.0
    assert result.dataframe.loc[0, "relative_humidity"] == 70.0


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
