"""Weather series HTTP scenarios shared by the SQLite suite and the opt-in TimescaleDB run."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from tests.helpers import rfc3339
from tests.scenarios.data_explorer_series import series_client

OBSERVATION_SERIES_PATH = "/data/weather/observations/series"
FORECAST_SERIES_PATH = "/data/weather/forecasts/series"
FORECAST_DAY = datetime(2026, 8, 5)
EARLY_ISSUE = FORECAST_DAY.replace(hour=9)
LATE_ISSUE = FORECAST_DAY.replace(hour=15)
SHARED_ISSUE = datetime(2030, 8, 5, 11)
FORECAST_WINDOW = {
    "start": rfc3339(FORECAST_DAY.replace(hour=16)),
    "end": rfc3339(FORECAST_DAY.replace(hour=19)),
}


def _observation(observed_at: datetime, station_id: str, temperature_c: float):
    return CWAStationObservation(
        observed_at=pd.Timestamp(observed_at),
        station_id=station_id,
        station_name=station_id,
        town_code=None,
        temperature_c=temperature_c,
        relative_humidity_pct=70.0,
        air_pressure_hpa=1012.0,
        precipitation_mm=0.0,
        wind_speed_m_s=2.0,
        wind_direction_deg=90.0,
    )


@contextmanager
def _seeded_observations(
    repo: TimeSeriesRepository, temperatures: dict[tuple[str, datetime], float]
) -> Iterator[tuple[TestClient, dict[str, str]]]:
    """Seed observations under unique station ids (keyed by alias) and remove them afterwards."""
    aliases = sorted({alias for alias, _ in temperatures})
    station_ids = {alias: f"s{uuid4().hex[:8]}" for alias in aliases}
    fetched_at = max(moment for _, moment in temperatures)
    batch = CWAObservationBatch(
        fetched_at=fetched_at,
        missing_station_ids=(),
        raw_payload={},
        observations=tuple(
            _observation(moment, station_ids[alias], value)
            for (alias, moment), value in temperatures.items()
        ),
    )
    repo.cwa_weather_store.upsert_cwa_observation_batch(batch)
    try:
        with series_client(repo) as client:
            yield client, station_ids
    finally:
        with repo.engine.begin() as connection:
            for station_id in station_ids.values():
                connection.execute(
                    text("DELETE FROM raw_cwa_station_observation WHERE station_id = :station_id"),
                    {"station_id": station_id},
                )
            connection.execute(
                text("DELETE FROM raw_cwa_observation_batch WHERE fetched_at = :fetched_at"),
                {"fetched_at": to_storage_time(batch.fetched_at)},
            )


def _own_series(body: dict, key: str, values: dict[str, str]) -> dict[str, list]:
    """Map alias to points for the seeded group values; other rows in a shared DB are ignored."""
    alias_of = {value: alias for alias, value in values.items()}
    return {
        alias_of[series["group"][key]]: [(point["t"], point["v"]) for point in series["points"]]
        for series in body["series"]
        if series["group"].get(key) in alias_of
    }


def assert_observation_series_draws_one_temperature_line_per_station(
    repo: TimeSeriesRepository,
) -> None:
    """測站觀測依 station_id 分組，預設 temperature_c；某站缺一小時時補 null。"""
    first = datetime(2026, 8, 3, 10, 0)
    temperatures = {
        ("taipei", first): 28.0,
        ("taipei", first + timedelta(hours=1)): 29.0,
        ("taipei", first + timedelta(hours=2)): 30.0,
        ("kaohsiung", first): 31.0,
        ("kaohsiung", first + timedelta(hours=2)): 32.5,
    }
    with _seeded_observations(repo, temperatures) as (client, station_ids):
        response = client.get(
            OBSERVATION_SERIES_PATH,
            params={"start": rfc3339(first), "end": rfc3339(first + timedelta(hours=2))},
        )

    assert response.status_code == 200
    body = response.json()
    own = [s for s in body["series"] if s["group"]["station_id"] in station_ids.values()]
    assert {(s["field"], s["unit"]) for s in own} == {("temperature_c", "°C")}
    assert all(set(s["group"]) == {"station_id"} for s in own)
    assert _own_series(body, "station_id", station_ids) == {
        "taipei": [
            ("2026-08-03T10:00:00+08:00", 28.0),
            ("2026-08-03T11:00:00+08:00", 29.0),
            ("2026-08-03T12:00:00+08:00", 30.0),
        ],
        "kaohsiung": [
            ("2026-08-03T10:00:00+08:00", 31.0),
            ("2026-08-03T11:00:00+08:00", None),
            ("2026-08-03T12:00:00+08:00", 32.5),
        ],
    }


def assert_observation_series_rejects_any_group_by(repo: TimeSeriesRepository) -> None:
    """測站觀測永不跨測站合成：任何 group_by 都回 422。"""
    first = datetime(2026, 8, 3, 10, 0)
    window = {"start": rfc3339(first), "end": rfc3339(first + timedelta(hours=1))}
    with _seeded_observations(repo, {("taipei", first): 28.0}) as (client, _station_ids):
        statuses = [
            client.get(OBSERVATION_SERIES_PATH, params={**window, "group_by": group_by}).status_code
            for group_by in ("station_id", "none", "town_code")
        ]

    assert statuses == [422, 422, 422]


def _forecast(
    geocode: str,
    hour: int,
    temperature_c: float | None,
    *,
    period_hours: int = 0,
    probability_of_precipitation_pct: float | None = None,
) -> CWATownshipForecast:
    valid_from = FORECAST_DAY.replace(hour=hour)
    return CWATownshipForecast(
        valid_from=pd.Timestamp(valid_from),
        valid_to=pd.Timestamp(valid_from + timedelta(hours=period_hours)),
        geocode=geocode,
        location_name=geocode,
        temperature_c=temperature_c,
        dew_point_c=None,
        apparent_temperature_c=None,
        relative_humidity_pct=None,
        probability_of_precipitation_pct=probability_of_precipitation_pct,
        wind_speed_m_s=None,
        wind_direction=None,
    )


@contextmanager
def _seeded_forecasts(
    repo: TimeSeriesRepository,
) -> Iterator[tuple[TestClient, str, dict[str, str]]]:
    """Seed three releases of one unique dataset: the 09:00 issue, its correction, and 15:00.

    The 15:00 release has an instant row and a three-hour precipitation row at 17:00 and no
    row at 18:00, as CWA township forecasts do.
    """
    dataset_id = f"T-{uuid4().hex[:8]}"
    geocodes = {alias: f"g{uuid4().hex[:8]}" for alias in ("north", "south")}
    north, south = geocodes["north"], geocodes["south"]
    releases = {
        (EARLY_ISSUE, EARLY_ISSUE): (
            _forecast(north, 16, 20.0),
            _forecast(north, 17, 21.0),
            _forecast(north, 18, 22.0),
        ),
        (EARLY_ISSUE, EARLY_ISSUE + timedelta(hours=1)): (
            _forecast(north, 16, 19.5),
            _forecast(north, 17, 20.5),
            _forecast(north, 18, 21.5),
        ),
        (LATE_ISSUE, LATE_ISSUE): (
            _forecast(north, 16, 26.0),
            _forecast(north, 17, 27.0),
            _forecast(north, 17, None, period_hours=3, probability_of_precipitation_pct=30.0),
            _forecast(north, 19, 25.0),
            _forecast(south, 16, 30.0),
        ),
    }
    for (issued_at, source_updated_at), forecasts in releases.items():
        repo.cwa_weather_store.upsert_cwa_forecast_releases(
            [
                CWAForecastRelease(
                    dataset_id=dataset_id,
                    issued_at=pd.Timestamp(issued_at),
                    source_updated_at=pd.Timestamp(source_updated_at),
                    fetched_at=source_updated_at,
                    missing_geocodes=(),
                    raw_payload={},
                    forecasts=forecasts,
                )
            ]
        )
    try:
        with series_client(repo) as client:
            yield client, dataset_id, geocodes
    finally:
        with repo.engine.begin() as connection:
            for table in ("raw_cwa_township_forecast", "raw_cwa_forecast_release"):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE dataset_id = :dataset_id"),
                    {"dataset_id": dataset_id},
                )


def assert_forecast_series_draws_latest_version_per_geocode_without_null_points(
    repo: TimeSeriesRepository,
) -> None:
    """鄉鎮預報依 valid_from、每個 geocode 一條最新版本的氣溫線；不補值，沒有 null 點。"""
    with _seeded_forecasts(repo) as (client, dataset_id, geocodes):
        response = client.get(
            FORECAST_SERIES_PATH, params={**FORECAST_WINDOW, "dataset_id": dataset_id}
        )
        precipitation = client.get(
            FORECAST_SERIES_PATH,
            params={
                **FORECAST_WINDOW,
                "dataset_id": dataset_id,
                "fields": "probability_of_precipitation_pct",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "raw"
    assert {(s["field"], s["unit"]) for s in body["series"]} == {("temperature_c", "°C")}
    assert all(set(s["group"]) == {"geocode"} for s in body["series"])
    assert all(point["v"] is not None for s in body["series"] for point in s["points"])
    assert _own_series(body, "geocode", geocodes) == {
        "north": [
            ("2026-08-05T16:00:00+08:00", 26.0),
            ("2026-08-05T17:00:00+08:00", 27.0),
            ("2026-08-05T19:00:00+08:00", 25.0),
        ],
        "south": [("2026-08-05T16:00:00+08:00", 30.0)],
    }
    assert _own_series(precipitation.json(), "geocode", geocodes) == {
        "north": [("2026-08-05T17:00:00+08:00", 30.0)],
    }


def assert_forecast_all_vintages_draws_one_series_per_issued_at(
    repo: TimeSeriesRepository,
) -> None:
    """開啟 all_vintages 時，每個 issued_at 各成一條 series；同一發布時間取最新更正版本，即使數值較小。"""
    with _seeded_forecasts(repo) as (client, dataset_id, geocodes):
        response = client.get(
            FORECAST_SERIES_PATH,
            params={**FORECAST_WINDOW, "geocode": geocodes["north"], "all_vintages": "true"},
        )

    assert response.status_code == 200
    vintages = {
        series["group"]["issued_at"]: [(point["t"], point["v"]) for point in series["points"]]
        for series in response.json()["series"]
    }
    assert {series["group"]["dataset_id"] for series in response.json()["series"]} == {dataset_id}
    assert vintages == {
        "2026-08-05T09:00:00+08:00": [
            ("2026-08-05T16:00:00+08:00", 19.5),
            ("2026-08-05T17:00:00+08:00", 20.5),
            ("2026-08-05T18:00:00+08:00", 21.5),
        ],
        "2026-08-05T15:00:00+08:00": [
            ("2026-08-05T16:00:00+08:00", 26.0),
            ("2026-08-05T17:00:00+08:00", 27.0),
            ("2026-08-05T19:00:00+08:00", 25.0),
        ],
    }


def _shared_issue_release(
    dataset_id: str, issued_at: datetime, source_updated_at: datetime, geocode: str, value: float
) -> CWAForecastRelease:
    forecast = replace(
        _forecast(geocode, 0, value),
        valid_from=pd.Timestamp(issued_at + timedelta(hours=3)),
        valid_to=pd.Timestamp(issued_at + timedelta(hours=3)),
    )
    return CWAForecastRelease(
        dataset_id=dataset_id,
        issued_at=pd.Timestamp(issued_at),
        source_updated_at=pd.Timestamp(source_updated_at),
        fetched_at=source_updated_at,
        missing_geocodes=(),
        raw_payload={},
        forecasts=(forecast,),
    )


def assert_forecast_series_prefers_three_day_dataset_on_shared_issue(
    repo: TimeSeriesRepository,
) -> None:
    """未指定 dataset_id 時，同一最新 issued_at 下優先 F-D0047-089，即使 091 的更新時間較晚。"""
    issued_at = SHARED_ISSUE + timedelta(microseconds=uuid4().int % 1_000_000)
    geocode = f"g{uuid4().hex[:8]}"
    releases = {
        "F-D0047-089": _shared_issue_release(
            "F-D0047-089", issued_at, issued_at + timedelta(minutes=5), geocode, 21.0
        ),
        "F-D0047-091": _shared_issue_release(
            "F-D0047-091", issued_at, issued_at + timedelta(minutes=5, seconds=30), geocode, 23.0
        ),
    }
    for release in releases.values():
        repo.cwa_weather_store.upsert_cwa_forecast_releases([release])
    window = {
        "start": rfc3339(issued_at.replace(microsecond=0)),
        "end": rfc3339(issued_at.replace(microsecond=0) + timedelta(hours=6)),
        "geocode": geocode,
    }
    try:
        with series_client(repo) as client:
            default = client.get(FORECAST_SERIES_PATH, params=window)
            weekly = client.get(
                FORECAST_SERIES_PATH, params={**window, "dataset_id": "F-D0047-091"}
            )
    finally:
        with repo.engine.begin() as connection:
            for table in ("raw_cwa_township_forecast", "raw_cwa_forecast_release"):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE issued_at = :issued_at"),
                    {"issued_at": to_storage_time(issued_at)},
                )

    assert default.status_code == 200
    assert [point["v"] for s in default.json()["series"] for point in s["points"]] == [21.0]
    assert [point["v"] for s in weekly.json()["series"] for point in s["points"]] == [23.0]


WEATHER_SERIES_SCENARIOS = (
    assert_observation_series_draws_one_temperature_line_per_station,
    assert_observation_series_rejects_any_group_by,
    assert_forecast_series_draws_latest_version_per_geocode_without_null_points,
    assert_forecast_all_vintages_draws_one_series_per_issued_at,
    assert_forecast_series_prefers_three_day_dataset_on_shared_issue,
)
