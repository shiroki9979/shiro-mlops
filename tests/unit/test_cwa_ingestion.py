"""Offline contract tests for canonical CWA ingestion."""

import json
from datetime import datetime

import pandas as pd

from shiro_mlops.core.config import Settings
from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAClient,
    parse_forecast_release,
    parse_observation_batch,
)
from shiro_mlops.data.repository import TimeSeriesRepository


def _observation_payload() -> dict:
    return {
        "success": "true",
        "records": {
            "Station": [
                {
                    "StationId": "466920",
                    "StationName": "臺北",
                    "TownCode": "63000050",
                    "ObsTime": {"DateTime": "2026-08-20T14:00:00+08:00"},
                    "WeatherElement": {
                        "AirTemperature": "35.7",
                        "RelativeHumidity": "57",
                        "AirPressure": "1008.2",
                        "Now": {"Precipitation": "T"},
                        "WindSpeed": "3.2",
                        "WindDirection": "990",
                    },
                }
            ]
        },
    }


def test_default_cwa_location_catalog_uses_stable_source_ids() -> None:
    assert DEFAULT_CWA_LOCATIONS["Taipei"].station_id == "466920"
    assert DEFAULT_CWA_LOCATIONS["Taichung"].station_id == "467490"
    assert DEFAULT_CWA_LOCATIONS["Kaohsiung"].station_id == "467441"
    assert DEFAULT_CWA_LOCATIONS["Kaohsiung"].geocode == "64000040"


def test_location_allowlist_can_be_overridden_as_one_mapping() -> None:
    settings = Settings(CWA_LOCATION_ALLOWLIST='{"Metro": {"station_id": "123", "geocode": "456"}}')

    assert settings.cwa_locations["Metro"].station_id == "123"
    assert settings.cwa_locations["Metro"].geocode == "456"


def test_parse_observation_batch_preserves_raw_and_normalizes_special_values() -> None:
    payload = _observation_payload()

    batch = parse_observation_batch(payload, fetched_at=datetime(2026, 8, 20, 14, 5))

    assert batch.status == "incomplete"
    assert batch.missing_station_ids == ("467441", "467490")
    assert batch.raw_payload == payload
    assert len(batch.observations) == 1
    observation = batch.observations[0]
    assert observation.station_id == "466920"
    assert observation.observed_at == pd.Timestamp("2026-08-20 14:00:00")
    assert observation.temperature_c == 35.7
    assert observation.relative_humidity_pct == 57.0
    assert observation.air_pressure_hpa == 1008.2
    assert observation.precipitation_mm == 0.0
    assert observation.wind_direction_deg is None


def test_client_observation_compatibility_dataframe_still_works(monkeypatch) -> None:
    payload = _observation_payload()

    class Response:
        text = json.dumps(payload)

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("httpx.Client.get", lambda *args, **kwargs: Response())

    frame = CWAClient(api_key="test").fetch_observations()

    assert isinstance(frame, pd.DataFrame)
    assert frame.loc[0, "temperature"] == 35.7
    assert frame.loc[0, "relative_humidity"] == 57.0


def test_repository_persists_canonical_observation_batch(test_repo: TimeSeriesRepository) -> None:
    batch = parse_observation_batch(_observation_payload(), fetched_at=datetime(2026, 8, 20, 14, 5))

    assert test_repo.upsert_cwa_observation_batch(batch) == 1

    observations = test_repo.fetch_cwa_station_observations(station_id="466920")

    assert len(observations) == 1
    assert observations.iloc[0]["station_id"] == "466920"
    assert observations.iloc[0]["temperature_c"] == 35.7
    assert observations.iloc[0]["precipitation_mm"] == 0.0
    assert observations.iloc[0]["wind_direction_deg"] is None


def test_parse_forecast_release_preserves_vintage_and_typed_elements() -> None:
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:20:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000050",
                            "locationName": "臺北市",
                            "weatherElement": [
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "elementValue": [{"value": "31"}],
                                        }
                                    ],
                                },
                                {
                                    "elementName": "RH",
                                    "time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "elementValue": [{"value": "70"}],
                                        }
                                    ],
                                },
                                {
                                    "elementName": "WD",
                                    "time": [
                                        {
                                            "StartTime": "2026-08-20T12:00:00+08:00",
                                            "EndTime": "2026-08-20T13:00:00+08:00",
                                            "elementValue": [{"value": "偏東風"}],
                                        }
                                    ],
                                },
                            ],
                        }
                    ]
                }
            ],
        }
    }

    release = parse_forecast_release(payload, dataset_id="F-D0047-089")

    assert release.issued_at == pd.Timestamp("2026-08-20 11:00:00")
    assert release.source_updated_at == pd.Timestamp("2026-08-20 11:20:00")
    assert release.status == "incomplete"
    assert release.missing_geocodes == ("64000040", "66000050")
    assert release.raw_payload == payload
    point = next(point for point in release.forecasts if point.valid_from.hour == 12)
    assert point.geocode == "63000050"
    assert point.temperature_c == 31.0
    assert point.relative_humidity_pct == 70.0
    assert point.valid_to == point.valid_from


def test_parse_forecast_release_uses_interval_boundaries() -> None:
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:00:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000050",
                            "weatherElement": [
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "startTime": "2026-08-20T12:00:00+08:00",
                                            "endTime": "2026-08-20T15:00:00+08:00",
                                            "elementValue": [{"value": "30"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ],
        }
    }

    release = parse_forecast_release(payload, dataset_id="F-D0047-091")
    point = release.forecasts[0]

    assert point.valid_from == pd.Timestamp("2026-08-20 12:00:00")
    assert point.valid_to == pd.Timestamp("2026-08-20 15:00:00")


def test_repository_persists_forecast_vintages_without_overwriting(
    test_repo: TimeSeriesRepository,
) -> None:
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:20:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000050",
                            "weatherElement": [
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "elementValue": [{"value": "31"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ],
        }
    }
    first = parse_forecast_release(payload, dataset_id="F-D0047-089")
    corrected = parse_forecast_release(
        {**payload, "records": {**payload["records"], "Update": "2026-08-20T11:25:00+08:00"}},
        dataset_id="F-D0047-089",
    )

    assert test_repo.upsert_cwa_forecast_release(first) == 1
    assert test_repo.upsert_cwa_forecast_release(corrected) == 1
    rows = test_repo.fetch_cwa_forecast_rows(geocode="63000050")

    assert len(rows) == 2
    assert set(rows["source_updated_at"].dt.hour) == {11}
    assert len(set(rows["source_updated_at"])) == 2


def test_repository_archives_legacy_weather_without_deleting_values(
    test_repo: TimeSeriesRepository,
) -> None:
    frame = pd.DataFrame(
        [
            {
                "datetime": "2026-08-20 12:00",
                "location": "Taipei",
                "temperature": 30.0,
                "relative_humidity": 70.0,
            }
        ]
    )
    test_repo.upsert_cwa_weather(frame)

    test_repo.archive_legacy_cwa_weather()
    test_repo.archive_legacy_cwa_weather()

    archived = pd.read_sql_query("SELECT * FROM legacy_cwa_weather", test_repo.engine)
    assert len(archived) == 1
    assert archived.iloc[0]["temperature"] == 30.0
