"""Tests for point-in-time CWA forecast resolution."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from shiro_mlops.core.config import Settings, settings
from shiro_mlops.data.cwa_client import CWALocation, resolve_cwa_location
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import (
    ForecastMode,
    WeatherCoverageError,
    WeatherSourceKind,
    WeatherValueSource,
    forecast_mode,
    resolve_weather,
)
from tests.helpers import canonical_observation_batch, forecast_release, township_forecast

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
    assert result.sources[0]["temperature"].kind == "weekly"


def _store_three_day(
    repository: TimeSeriesRepository,
    issued_at: datetime,
    hours: tuple[int, ...],
    temperature: float,
) -> None:
    points = tuple(
        replace(township_forecast(datetime(2026, 8, 20, hour), temperature), geocode=TAIPEI.geocode)
        for hour in hours
    )
    repository.upsert_cwa_forecast_release(forecast_release(issued_at, points))


def _store_weekly(
    repository: TimeSeriesRepository, issued_at: datetime, temperature: float
) -> None:
    interval = replace(
        township_forecast(datetime(2026, 8, 20, 12), temperature),
        valid_to=datetime(2026, 8, 20, 18),
        geocode=TAIPEI.geocode,
    )
    repository.upsert_cwa_forecast_release(
        replace(forecast_release(issued_at, (interval,)), dataset_id="F-D0047-091")
    )


def test_resolver_uses_fresh_weekly_when_only_three_day_forecast_is_stale(
    test_repo: TimeSeriesRepository,
) -> None:
    """Seven hours are judged by the version supplying the value, not the newest of both."""
    _store_three_day(test_repo, datetime(2026, 8, 20, 2), (12, 13), 30.0)
    _store_weekly(test_repo, datetime(2026, 8, 20, 10), 25.0)

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=2,
        as_of=datetime(2026, 8, 20, 12),
        fields=("temperature",),
    )

    assert result.mode == "normal"
    assert result.dataframe["temperature"].tolist() == [25.0, 25.0]
    assert [point["temperature"].kind for point in result.sources] == ["weekly", "weekly"]


def test_resolver_degrades_to_observation_when_both_forecasts_are_stale(
    test_repo: TimeSeriesRepository,
) -> None:
    _store_three_day(test_repo, datetime(2026, 8, 20, 2), (12, 13), 30.0)
    _store_weekly(test_repo, datetime(2026, 8, 20, 4), 25.0)
    test_repo.upsert_cwa_observation_batch(
        canonical_observation_batch(
            pd.DataFrame(
                {
                    "datetime": [datetime(2026, 8, 19, 12)],
                    "location": ["Taipei"],
                    "temperature": [28.0],
                    "relative_humidity": [75.0],
                }
            )
        )
    )

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
        fields=("temperature",),
    )

    assert result.mode == "degraded"
    assert result.dataframe.loc[0, "temperature"] == 28.0
    assert result.sources[0]["temperature"].kind == "previous_day_observation"


def test_resolver_fills_hours_outside_fresh_three_day_coverage_from_weekly(
    test_repo: TimeSeriesRepository,
) -> None:
    _store_three_day(test_repo, datetime(2026, 8, 20, 10), (12, 13), 30.0)
    _store_weekly(test_repo, datetime(2026, 8, 20, 10), 25.0)

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=3,
        as_of=datetime(2026, 8, 20, 12),
        fields=("temperature",),
    )

    assert result.mode == "normal"
    assert result.dataframe["temperature"].tolist() == [30.0, 30.0, 25.0]
    assert [point["temperature"].kind for point in result.sources] == [
        "three_day",
        "three_day",
        "weekly",
    ]


def test_resolver_falls_back_to_latest_release_holding_the_reference_point(
    test_repo: TimeSeriesRepository,
) -> None:
    """Vintage fallback depends on the point's own rows, not on the release being complete."""

    def release(issued_at: datetime, geocode: str, temperature: float, *, complete: bool):
        point = replace(township_forecast(datetime(2026, 8, 20, 23), temperature), geocode=geocode)
        return replace(
            forecast_release(issued_at, (point,)),
            status="complete" if complete else "incomplete",
            missing_geocodes=() if complete else ("some-other-geocode",),
        )

    test_repo.upsert_cwa_forecast_release(
        release(datetime(2026, 8, 20, 16), TAIPEI.geocode, 30.0, complete=True)
    )
    test_repo.upsert_cwa_forecast_release(
        release(datetime(2026, 8, 20, 19), TAIPEI.geocode, 31.0, complete=False)
    )
    test_repo.upsert_cwa_forecast_release(
        release(datetime(2026, 8, 20, 22), "64000000", 32.0, complete=False)
    )

    result = resolve_weather(
        test_repo,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 23),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 22),
        fields=("temperature",),
    )

    assert result.dataframe.loc[0, "temperature"] == 31.0
    source = result.sources[0]["temperature"]
    assert source.kind == "three_day"
    assert source.issued_at == pd.Timestamp("2026-08-20 19:00")


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
    assert result.sources[0]["temperature"].kind == "three_day"


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
    assert result.sources[0]["temperature"].kind == "three_day"
    assert result.sources[0]["relative_humidity"].kind == "weekly"


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
        reference_point=resolve_cwa_location(settings.cwa_locations, "Taipei"),
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
    assert result.sources[0]["temperature"].kind == "previous_day_observation"


def test_resolver_does_not_read_observations_after_the_as_of_time() -> None:
    """Degraded backtests may only use observations that already existed at prediction time."""
    repository = MagicMock()
    repository.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    repository.fetch_cwa_station_observations.return_value = pd.DataFrame()
    as_of = datetime(2026, 8, 20, 12)

    with pytest.raises(WeatherCoverageError):
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

    with pytest.raises(
        WeatherCoverageError,
        match=r"^Taipei: No weather coverage for 2026-08-20T13:00:00 wind_direction$",
    ):
        resolve_weather(
            repository,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=1,
            as_of=datetime(2026, 8, 20, 11),
            fields=("wind_direction",),
        )


@pytest.mark.parametrize("horizon_hours", [0, -1])
def test_resolver_rejects_a_horizon_shorter_than_one_hour(horizon_hours: int) -> None:
    """An empty horizon is a caller contract error, not a lack of weather coverage."""
    repository = MagicMock()

    with pytest.raises(ValueError, match="horizon_hours"):
        resolve_weather(
            repository,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=horizon_hours,
        )

    repository.fetch_cwa_forecast_rows.assert_not_called()


def test_resolver_reads_forecasts_and_observations_of_the_weather_reference_point() -> None:
    """Resolve weather from the reference point's forecast geocode and station, not a fixed Taipei code."""
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


def test_ingestion_catalog_from_settings_resolves_weather_reference_point_alias() -> None:
    settings = Settings(
        CWA_LOCATION_ALLOWLIST='{"Hualien": {"station_id": "466990", "geocode": "10015000"}}'
    )

    assert resolve_cwa_location(settings.cwa_locations, "Hualien") == CWALocation(
        "Hualien", "466990", "10015000"
    )
    with pytest.raises(ValueError, match="not in the CWA ingestion catalog"):
        resolve_cwa_location(settings.cwa_locations, "Taipei")


FORECAST_ROW = pd.Series(
    {
        "dataset_id": "F-D0047-089",
        "issued_at": pd.Timestamp("2026-08-20 10:00"),
        "source_updated_at": pd.Timestamp("2026-08-20 10:10"),
    }
)


def test_only_previous_day_observation_and_climatology_are_substitutes() -> None:
    assert {kind for kind in WeatherSourceKind if kind.is_substitute} == {
        WeatherSourceKind.PREVIOUS_DAY_OBSERVATION,
        WeatherSourceKind.CLIMATOLOGY,
    }
    assert [kind.value for kind in WeatherSourceKind] == [
        "three_day",
        "weekly",
        "previous_day_observation",
        "climatology",
        "station_observation",
    ]


@pytest.mark.parametrize("kind", [WeatherSourceKind.THREE_DAY, WeatherSourceKind.WEEKLY])
def test_forecast_source_serializes_the_version_that_supplied_the_value(
    kind: WeatherSourceKind,
) -> None:
    assert WeatherValueSource.forecast(kind, FORECAST_ROW).as_dict() == {
        "source": kind.value,
        "dataset_id": "F-D0047-089",
        "issued_at": "2026-08-20T10:00:00",
        "source_updated_at": "2026-08-20T10:10:00",
    }


def test_forecast_source_reports_version_times_in_taiwan_local_time() -> None:
    row = FORECAST_ROW.copy()
    row["issued_at"] = pd.Timestamp("2026-08-20 02:00", tz="UTC")
    row["source_updated_at"] = pd.Timestamp("2026-08-20 02:10", tz="UTC")

    source = WeatherValueSource.forecast(WeatherSourceKind.THREE_DAY, row).as_dict()

    assert source["issued_at"] == "2026-08-20T10:00:00"
    assert source["source_updated_at"] == "2026-08-20T10:10:00"


@pytest.mark.parametrize(
    "kind", [WeatherSourceKind.PREVIOUS_DAY_OBSERVATION, WeatherSourceKind.CLIMATOLOGY]
)
def test_substitute_source_serializes_only_its_kind(kind: WeatherSourceKind) -> None:
    assert WeatherValueSource.substitute(kind).as_dict() == {"source": kind.value}


@pytest.mark.parametrize(
    "kind",
    [
        WeatherSourceKind.THREE_DAY,
        WeatherSourceKind.WEEKLY,
        WeatherSourceKind.STATION_OBSERVATION,
    ],
)
def test_substitute_source_rejects_a_kind_that_is_not_a_substitute(
    kind: WeatherSourceKind,
) -> None:
    with pytest.raises(ValueError, match="not a substitute"):
        WeatherValueSource.substitute(kind)


def test_observed_source_serializes_the_observation_time() -> None:
    source = WeatherValueSource.observed(pd.Timestamp("2026-08-20 12:00"))

    assert source.as_dict() == {
        "source": "station_observation",
        "observed_at": "2026-08-20T12:00:00",
    }


@pytest.mark.parametrize(
    "build",
    [
        lambda: WeatherValueSource.forecast(WeatherSourceKind.CLIMATOLOGY, FORECAST_ROW),
        lambda: WeatherValueSource.forecast(WeatherSourceKind.STATION_OBSERVATION, FORECAST_ROW),
        lambda: WeatherValueSource.substitute(WeatherSourceKind.THREE_DAY),
        lambda: WeatherValueSource.substitute(WeatherSourceKind.STATION_OBSERVATION),
        lambda: WeatherValueSource(WeatherSourceKind.WEEKLY, dataset_id="F-D0047-091"),
        lambda: WeatherValueSource(
            WeatherSourceKind.THREE_DAY,
            dataset_id="F-D0047-089",
            issued_at=pd.Timestamp("2026-08-20 10:00"),
            source_updated_at=pd.Timestamp("2026-08-20 10:10"),
            observed_at=pd.Timestamp("2026-08-20 10:00"),
        ),
        lambda: WeatherValueSource(
            WeatherSourceKind.STATION_OBSERVATION,
            observed_at=pd.Timestamp("2026-08-20 12:00"),
            dataset_id="F-D0047-089",
        ),
        lambda: WeatherValueSource(
            WeatherSourceKind.CLIMATOLOGY, observed_at=pd.Timestamp("2026-08-20 12:00")
        ),
        lambda: WeatherValueSource("three_day"),
    ],
)
def test_source_whose_fields_do_not_match_its_kind_is_rejected(build) -> None:
    with pytest.raises(ValueError):
        build()


OBSERVED = WeatherValueSource.observed(pd.Timestamp("2026-08-20 12:00"))
THREE_DAY = WeatherValueSource.forecast(WeatherSourceKind.THREE_DAY, FORECAST_ROW)


def test_forecast_mode_has_only_normal_and_degraded() -> None:
    assert [mode.value for mode in ForecastMode] == ["normal", "degraded"]


def test_forecast_mode_is_normal_when_every_value_is_a_station_observation() -> None:
    assert forecast_mode([OBSERVED, OBSERVED]) == "normal"


def test_forecast_mode_is_normal_when_every_value_comes_from_a_forecast() -> None:
    weekly = WeatherValueSource.forecast(WeatherSourceKind.WEEKLY, FORECAST_ROW)

    assert forecast_mode([THREE_DAY, weekly]) == "normal"


@pytest.mark.parametrize(
    "kind", [WeatherSourceKind.PREVIOUS_DAY_OBSERVATION, WeatherSourceKind.CLIMATOLOGY]
)
def test_forecast_mode_is_degraded_when_any_value_is_a_substitute(
    kind: WeatherSourceKind,
) -> None:
    sources = [THREE_DAY, WeatherValueSource.substitute(kind), OBSERVED]

    assert forecast_mode(sources) == "degraded"
