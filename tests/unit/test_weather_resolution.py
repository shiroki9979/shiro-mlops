"""Tests for point-in-time CWA forecast resolution."""

from dataclasses import replace
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from shiro_mlops.core.config import Settings, settings
from shiro_mlops.data.cwa_client import CWALocation, resolve_cwa_location
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
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


@pytest.fixture
def store(sqlite_engine: Engine) -> CWAWeatherStore:
    return CWAWeatherStore(sqlite_engine)


@pytest.mark.parametrize("hour", [14, 15, 16])
def test_resolver_falls_back_to_weekly_around_a_missing_forecast_point(
    store: CWAWeatherStore, hour: int
) -> None:
    points = tuple(
        replace(
            township_forecast(datetime(2026, 8, 20, time), temperature),
            geocode=TAIPEI.geocode,
        )
        for time, temperature in ((12, 30.0), (15, None), (18, 36.0))
    )
    store.upsert_cwa_forecast_releases([forecast_release(datetime(2026, 8, 20, 10), points)])
    weekly = replace(
        township_forecast(datetime(2026, 8, 20, 12), 22.0),
        valid_to=datetime(2026, 8, 20, 19),
        geocode=TAIPEI.geocode,
    )
    store.upsert_cwa_forecast_releases(
        [replace(forecast_release(datetime(2026, 8, 20, 10), (weekly,)), dataset_id="F-D0047-091")]
    )

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, hour),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 14),
        fields=("temperature",),
    )

    assert result.dataframe.loc[0, "temperature"] == 22.0
    assert result.sources[0]["temperature"].kind == "weekly"


def _store_three_day(
    store: CWAWeatherStore,
    issued_at: datetime,
    hours: tuple[int, ...],
    temperature: float,
) -> None:
    points = tuple(
        replace(township_forecast(datetime(2026, 8, 20, hour), temperature), geocode=TAIPEI.geocode)
        for hour in hours
    )
    store.upsert_cwa_forecast_releases([forecast_release(issued_at, points)])


def _store_weekly(store: CWAWeatherStore, issued_at: datetime, temperature: float) -> None:
    interval = replace(
        township_forecast(datetime(2026, 8, 20, 12), temperature),
        valid_to=datetime(2026, 8, 20, 18),
        geocode=TAIPEI.geocode,
    )
    store.upsert_cwa_forecast_releases(
        [replace(forecast_release(issued_at, (interval,)), dataset_id="F-D0047-091")]
    )


def test_resolver_uses_fresh_weekly_when_only_three_day_forecast_is_stale(
    store: CWAWeatherStore,
) -> None:
    """Seven hours are judged by the version supplying the value, not the newest of both."""
    _store_three_day(store, datetime(2026, 8, 20, 2), (12, 13), 30.0)
    _store_weekly(store, datetime(2026, 8, 20, 10), 25.0)

    result = resolve_weather(
        store,
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
    store: CWAWeatherStore,
) -> None:
    _store_three_day(store, datetime(2026, 8, 20, 2), (12, 13), 30.0)
    _store_weekly(store, datetime(2026, 8, 20, 4), 25.0)
    store.upsert_cwa_observation_batch(
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
        store,
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
    store: CWAWeatherStore,
) -> None:
    _store_three_day(store, datetime(2026, 8, 20, 10), (12, 13), 30.0)
    _store_weekly(store, datetime(2026, 8, 20, 10), 25.0)

    result = resolve_weather(
        store,
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
    store: CWAWeatherStore,
) -> None:
    """Vintage fallback depends on the point's own rows, not on the release being complete."""

    def release(issued_at: datetime, geocode: str, temperature: float, *, complete: bool):
        point = replace(township_forecast(datetime(2026, 8, 20, 23), temperature), geocode=geocode)
        return replace(
            forecast_release(issued_at, (point,)),
            missing_geocodes=() if complete else ("some-other-geocode",),
        )

    store.upsert_cwa_forecast_releases(
        [release(datetime(2026, 8, 20, 16), TAIPEI.geocode, 30.0, complete=True)]
    )
    store.upsert_cwa_forecast_releases(
        [release(datetime(2026, 8, 20, 19), TAIPEI.geocode, 31.0, complete=False)]
    )
    store.upsert_cwa_forecast_releases(
        [release(datetime(2026, 8, 20, 22), "64000000", 32.0, complete=False)]
    )

    result = resolve_weather(
        store,
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


def _issues(result) -> list[pd.Timestamp | None]:
    return [point["temperature"].issued_at for point in result.sources]


def test_resolver_serves_hours_before_the_newest_release_from_a_fresh_older_one(
    store: CWAWeatherStore,
) -> None:
    """Degraded only when no version issued within seven hours supplies the value (#367)."""
    _store_three_day(store, datetime(2026, 8, 20, 5, 30), tuple(range(6, 18)), 30.0)
    _store_three_day(store, datetime(2026, 8, 20, 11, 30), tuple(range(12, 18)), 32.0)

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 11),
        horizon_hours=2,
        as_of=datetime(2026, 8, 20, 12, 15),
        fields=("temperature",),
    )

    assert result.mode == "normal"
    assert result.dataframe["temperature"].tolist() == [30.0, 32.0]
    assert [point["temperature"].kind for point in result.sources] == ["three_day"] * 2
    assert _issues(result) == [pd.Timestamp("2026-08-20 05:30"), pd.Timestamp("2026-08-20 11:30")]


def test_resolver_degrades_an_hour_only_a_stale_older_release_holds(
    store: CWAWeatherStore,
) -> None:
    _store_three_day(store, datetime(2026, 8, 20, 5), tuple(range(6, 18)), 30.0)
    _store_three_day(store, datetime(2026, 8, 20, 11, 30), tuple(range(12, 18)), 32.0)
    store.upsert_cwa_observation_batch(
        canonical_observation_batch(
            pd.DataFrame(
                {
                    "datetime": [datetime(2026, 8, 19, 11)],
                    "location": ["Taipei"],
                    "temperature": [28.0],
                    "relative_humidity": [75.0],
                }
            )
        )
    )

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 11),
        horizon_hours=2,
        as_of=datetime(2026, 8, 20, 12, 15),
        fields=("temperature",),
    )

    assert result.mode == "degraded"
    assert result.dataframe["temperature"].tolist() == [28.0, 32.0]
    assert [point["temperature"].kind for point in result.sources] == [
        "previous_day_observation",
        "three_day",
    ]


def test_resolver_never_interpolates_between_two_releases(store: CWAWeatherStore) -> None:
    """Both endpoints come from the one version the value is attributed to."""
    older_end = replace(township_forecast(datetime(2026, 8, 20, 12), 33.0), geocode=TAIPEI.geocode)
    older_start = replace(township_forecast(datetime(2026, 8, 20, 9), 30.0), geocode=TAIPEI.geocode)
    store.upsert_cwa_forecast_releases(
        [forecast_release(datetime(2026, 8, 20, 5, 30), (older_start, older_end))]
    )
    _store_three_day(store, datetime(2026, 8, 20, 11, 30), (12, 15), 36.0)

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 11),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12, 15),
        fields=("temperature",),
    )

    assert result.dataframe["temperature"].tolist() == [pytest.approx(32.0)]
    assert _issues(result) == [pd.Timestamp("2026-08-20 05:30")]


def test_resolver_prefers_a_fresh_older_three_day_release_to_a_newer_weekly_one(
    store: CWAWeatherStore,
) -> None:
    _store_three_day(store, datetime(2026, 8, 20, 5, 30), (12,), 30.0)
    _store_three_day(store, datetime(2026, 8, 20, 11, 30), (13,), 32.0)
    _store_weekly(store, datetime(2026, 8, 20, 11, 30), 25.0)

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
        fields=("temperature",),
    )

    assert result.dataframe["temperature"].tolist() == [30.0]
    assert result.sources[0]["temperature"].kind == "three_day"


def test_resolver_takes_a_field_the_newest_release_lacks_from_an_older_one(
    store: CWAWeatherStore,
) -> None:
    def release(issued_at: datetime, temperature: float, humidity: float | None):
        point = township_forecast(
            datetime(2026, 8, 20, 12), temperature, relative_humidity_pct=humidity
        )
        return forecast_release(issued_at, (replace(point, geocode=TAIPEI.geocode),))

    store.upsert_cwa_forecast_releases([release(datetime(2026, 8, 20, 5, 30), 30.0, 70.0)])
    store.upsert_cwa_forecast_releases([release(datetime(2026, 8, 20, 11, 30), 32.0, None)])

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.mode == "normal"
    assert result.dataframe.loc[0, "temperature"] == 32.0
    assert result.dataframe.loc[0, "relative_humidity"] == 70.0
    assert result.sources[0]["temperature"].issued_at == pd.Timestamp("2026-08-20 11:30")
    assert result.sources[0]["relative_humidity"].issued_at == pd.Timestamp("2026-08-20 05:30")


def test_resolver_serves_the_newest_correction_published_by_the_as_of_time(
    store: CWAWeatherStore,
) -> None:
    """A correction updated after the as-of time did not exist yet at prediction time."""
    point = replace(township_forecast(datetime(2026, 8, 20, 12), 30.0), geocode=TAIPEI.geocode)
    issued_at = datetime(2026, 8, 20, 11)
    for updated_at, temperature in (("11:00", 30.0), ("11:20", 31.0), ("12:20", 99.0)):
        store.upsert_cwa_forecast_releases(
            [
                replace(
                    forecast_release(issued_at, (replace(point, temperature_c=temperature),)),
                    source_updated_at=pd.Timestamp(f"2026-08-20 {updated_at}"),
                )
            ]
        )

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
        fields=("temperature",),
    )

    assert result.dataframe["temperature"].tolist() == [31.0]
    assert result.sources[0]["temperature"].source_updated_at == pd.Timestamp("2026-08-20 11:20")


def test_resolver_interpolates_short_horizon_between_persisted_forecast_points(
    store: CWAWeatherStore,
) -> None:
    geocode = TAIPEI.geocode
    points = tuple(
        replace(
            township_forecast(datetime(2026, 8, 20, hour), temperature, relative_humidity_pct=70.0),
            geocode=geocode,
        )
        for hour, temperature in ((12, 30.0), (15, 33.0))
    )
    store.upsert_cwa_forecast_releases([forecast_release(datetime(2026, 8, 20, 9), points)])
    # A future release must not supply either interpolation endpoint.
    store.upsert_cwa_forecast_releases(
        [
            forecast_release(
                datetime(2026, 8, 20, 14),
                tuple(replace(point, temperature_c=99.0) for point in points),
            )
        ]
    )

    result = resolve_weather(
        store,
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
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
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
    store.fetch_cwa_station_observations.return_value = pd.DataFrame()

    result = resolve_weather(
        store,
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
    store = MagicMock(spec=CWAWeatherStore)
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
    store.fetch_cwa_forecast_rows.side_effect = lambda **kwargs: (
        forecast if kwargs["geocode"] == "99999999" else pd.DataFrame()
    )
    store.fetch_cwa_station_observations.side_effect = lambda **kwargs: (
        observation if kwargs["station_id"] == "999999" else pd.DataFrame()
    )

    result = resolve_weather(
        store,
        reference_point=resolve_cwa_location(settings.cwa_locations, "Taipei"),
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 11),
    )

    assert result.dataframe.loc[0, "temperature"] == 30.0
    assert result.dataframe.loc[0, "relative_humidity"] == 70.0


def test_resolver_uses_previous_day_observation_when_forecast_is_stale() -> None:
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
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
    store.fetch_cwa_station_observations.return_value = pd.DataFrame(
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
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.mode == "degraded"
    assert result.dataframe.loc[0, "temperature"] == 28.0
    assert result.dataframe.loc[0, "relative_humidity"] == 75.0
    assert result.sources[0]["temperature"].kind == "previous_day_observation"


def _stale_forecast_store(observations: pd.DataFrame) -> MagicMock:
    """A store with no forecast at all, so every value has to come from observations."""
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    store.fetch_cwa_station_observations.return_value = observations
    return store


def _same_hour_observations(days: int, *, hour: int = 12) -> pd.DataFrame:
    """One observation at ``hour`` on each of ``days`` August dates, none on the 19th."""
    return pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp(2026, 8, 1 + offset, hour),
                "station_id": "466920",
                "temperature_c": 26.0 + offset,
                "relative_humidity_pct": 60.0 + offset,
            }
            for offset in range(days)
        ]
    )


def test_resolver_uses_climatology_once_seven_days_share_the_month_and_hour() -> None:
    store = _stale_forecast_store(_same_hour_observations(7))

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.mode == "degraded"
    assert result.dataframe.loc[0, "temperature"] == pytest.approx(29.0)
    assert result.dataframe.loc[0, "relative_humidity"] == pytest.approx(63.0)
    assert result.sources[0]["temperature"].kind == "climatology"


def test_resolver_refuses_climatology_from_fewer_than_seven_days() -> None:
    store = _stale_forecast_store(_same_hour_observations(6))

    with pytest.raises(WeatherCoverageError, match="Taipei.*2026-08-20T12:00:00 temperature"):
        resolve_weather(
            store,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 12),
            horizon_hours=1,
            as_of=datetime(2026, 8, 20, 12),
        )


def test_climatology_counts_days_not_observations() -> None:
    """Seven readings on one date are one day of evidence, not seven."""
    one_day = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-05 12:00"),
                "station_id": "466920",
                "temperature_c": 30.0,
                "relative_humidity_pct": 70.0,
            }
        ]
        * 7
    )

    with pytest.raises(WeatherCoverageError):
        resolve_weather(
            _stale_forecast_store(one_day),
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 12),
            horizon_hours=1,
            as_of=datetime(2026, 8, 20, 12),
        )


def test_resolver_chooses_the_substitute_per_field_when_the_previous_day_lacks_one() -> None:
    observations = _same_hour_observations(7)
    observations.loc[len(observations)] = {
        "observed_at": pd.Timestamp("2026-08-19 12:00"),
        "station_id": "466920",
        "temperature_c": 28.0,
        "relative_humidity_pct": float("nan"),
    }

    result = resolve_weather(
        _stale_forecast_store(observations),
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.dataframe.loc[0, "temperature"] == 28.0
    assert result.sources[0]["temperature"].kind == "previous_day_observation"
    assert result.dataframe.loc[0, "relative_humidity"] == pytest.approx(63.0)
    assert result.sources[0]["relative_humidity"].kind == "climatology"


def test_resolver_reads_timezone_aware_observation_times_as_taiwan_local() -> None:
    observations = pd.DataFrame(
        [
            {
                "observed_at": pd.Timestamp("2026-08-19 04:00", tz="UTC"),
                "station_id": "466920",
                "temperature_c": 28.0,
                "relative_humidity_pct": 75.0,
            }
        ]
    )

    result = resolve_weather(
        _stale_forecast_store(observations),
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert result.sources[0]["temperature"].kind == "previous_day_observation"


def test_resolver_degrades_a_whole_week_from_a_year_of_observations() -> None:
    """The outage path: 168 hours, every value a substitute, from one read of the year."""
    hours = pd.date_range("2025-08-20 00:00", "2026-08-20 11:00", freq="h")
    observations = pd.DataFrame(
        {
            "observed_at": hours,
            "station_id": "466920",
            "temperature_c": 20.0 + hours.hour.to_numpy() / 4,
            "relative_humidity_pct": 80.0 - hours.hour.to_numpy() / 2,
        }
    )
    store = _stale_forecast_store(observations)

    result = resolve_weather(
        store,
        reference_point=TAIPEI,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=168,
        as_of=datetime(2026, 8, 20, 12),
    )

    kinds = [source["temperature"].kind for source in result.sources]
    assert kinds[:24] == ["previous_day_observation"] * 24
    assert kinds[24:] == ["climatology"] * 144
    assert result.dataframe["temperature"].tolist() == pytest.approx(
        [20.0 + moment.hour / 4 for moment in result.dataframe["datetime"]]
    )
    assert store.fetch_cwa_station_observations.call_count == 1


def test_resolver_does_not_read_observations_after_the_as_of_time() -> None:
    """Degraded backtests may only use observations that already existed at prediction time."""
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    store.fetch_cwa_station_observations.return_value = pd.DataFrame()
    as_of = datetime(2026, 8, 20, 12)

    with pytest.raises(WeatherCoverageError):
        resolve_weather(
            store,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=24,
            as_of=as_of,
        )

    assert store.fetch_cwa_station_observations.call_args.kwargs["end_time"] == as_of


def test_resolver_reads_only_releases_young_enough_to_serve(
    store: CWAWeatherStore, sqlite_engine: Engine
) -> None:
    """A release older than seven hours is stale whatever it holds, so it is never read."""
    for issued_at in pd.date_range("2026-08-13 12:00", "2026-08-20 06:00", freq="6h"):
        _store_three_day(store, issued_at.to_pydatetime(), (13,), 30.0)
    statements: list[tuple[str, dict]] = []

    def record(conn, cursor, statement, parameters, *_args) -> None:
        statements.append((statement, parameters))

    event.listen(sqlite_engine, "before_cursor_execute", record)
    try:
        result = resolve_weather(
            store,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=1,
            as_of=datetime(2026, 8, 20, 12),
            fields=("temperature",),
        )
    finally:
        event.remove(sqlite_engine, "before_cursor_execute", record)

    assert _issues(result) == [pd.Timestamp("2026-08-20 06:00")]
    forecast_reads = [sql for sql, _ in statements if "raw_cwa_township_forecast" in sql]
    assert len(forecast_reads) == 1
    assert "issued_at >= " in forecast_reads[0]


def test_resolver_does_not_interpolate_wind_direction() -> None:
    """Categorical wind direction may be exact but must never be fabricated between points."""
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame(
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
    store.fetch_cwa_station_observations.return_value = pd.DataFrame()

    with pytest.raises(
        WeatherCoverageError,
        match=r"^Taipei: No weather coverage for 2026-08-20T13:00:00 wind_direction$",
    ):
        resolve_weather(
            store,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=1,
            as_of=datetime(2026, 8, 20, 11),
            fields=("wind_direction",),
        )


@pytest.mark.parametrize("horizon_hours", [0, -1])
def test_resolver_rejects_a_horizon_shorter_than_one_hour(horizon_hours: int) -> None:
    """An empty horizon is a caller contract error, not a lack of weather coverage."""
    store = MagicMock(spec=CWAWeatherStore)

    with pytest.raises(ValueError, match="horizon_hours"):
        resolve_weather(
            store,
            reference_point=TAIPEI,
            start_time=datetime(2026, 8, 20, 13),
            horizon_hours=horizon_hours,
        )

    store.fetch_cwa_forecast_rows.assert_not_called()


def test_resolver_reads_forecasts_and_observations_of_the_weather_reference_point() -> None:
    """Resolve weather from the reference point's forecast geocode and station, not a fixed Taipei code."""
    store = MagicMock(spec=CWAWeatherStore)
    store.fetch_cwa_forecast_rows.return_value = pd.DataFrame()
    store.fetch_cwa_station_observations.return_value = pd.DataFrame(
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
        store,
        reference_point=kaohsiung,
        start_time=datetime(2026, 8, 20, 12),
        horizon_hours=1,
        as_of=datetime(2026, 8, 20, 12),
    )

    assert store.fetch_cwa_forecast_rows.call_args.kwargs["geocode"] == "64000000"
    assert store.fetch_cwa_station_observations.call_args.kwargs["station_id"] == "467441"
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
