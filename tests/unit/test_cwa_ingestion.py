"""Offline contract tests for canonical CWA ingestion."""

import json
import secrets
from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
from defusedxml.common import DefusedXmlException
from sqlalchemy.exc import IntegrityError

from shiro_mlops.core.config import Settings
from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAClient,
    CWAForecastRelease,
    CWATownshipForecast,
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


def _forecast_file_payload() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<cwaopendata>
  <Dataset>
    <DatasetInfo>
      <IssueTime>2026-09-15T05:00:00+08:00</IssueTime>
      <Update>2026-09-15T05:30:00+08:00</Update>
    </DatasetInfo>
    <Locations>
      <Location>
        <LocationName>臺北市</LocationName>
        <Geocode>63000000</Geocode>
        <WeatherElement>
          <ElementName>溫度</ElementName>
          <Time>
            <DataTime>2026-09-15T06:00:00+08:00</DataTime>
            <ElementValue><Temperature>31</Temperature></ElementValue>
          </Time>
        </WeatherElement>
        <WeatherElement>
          <ElementName>相對濕度</ElementName>
          <Time>
            <DataTime>2026-09-15T06:00:00+08:00</DataTime>
            <ElementValue><RelativeHumidity>70</RelativeHumidity></ElementValue>
          </Time>
        </WeatherElement>
      </Location>
    </Locations>
  </Dataset>
</cwaopendata>"""


def test_default_cwa_location_catalog_uses_stable_source_ids() -> None:
    assert DEFAULT_CWA_LOCATIONS["Taipei"].station_id == "466920"
    assert DEFAULT_CWA_LOCATIONS["Taipei"].geocode == "63000000"
    assert DEFAULT_CWA_LOCATIONS["Taichung"].station_id == "467490"
    assert DEFAULT_CWA_LOCATIONS["Taichung"].geocode == "66000000"
    assert DEFAULT_CWA_LOCATIONS["Kaohsiung"].station_id == "467441"
    assert DEFAULT_CWA_LOCATIONS["Kaohsiung"].geocode == "64000000"


def test_location_allowlist_can_be_overridden_as_one_mapping() -> None:
    settings = Settings(CWA_LOCATION_ALLOWLIST='{"Metro": {"station_id": "123", "geocode": "456"}}')

    assert settings.cwa_locations["Metro"].station_id == "123"
    assert settings.cwa_locations["Metro"].geocode == "456"


def test_client_fetches_versioned_forecast_from_cwa_file_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forecast versions must come from the source file, not flattened REST data."""
    file_url = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-D0047-089"
    object_url = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/forecast.xml"
    api_key = secrets.token_urlsafe()
    requests: list[tuple[str, dict]] = []

    class Response:
        def __init__(
            self,
            text: str,
            headers: dict[str, str] | None = None,
            status_code: int = 200,
        ) -> None:
            self.text = text
            self.headers = headers or {}
            self.status_code = status_code

        def raise_for_status(self) -> None:
            if self.status_code >= 300:
                raise RuntimeError("Redirect response")

    class FileClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, **kwargs: object) -> Response:
            requests.append((url, kwargs))
            if url == file_url:
                return Response("", {"location": object_url}, status_code=302)
            if url == object_url:
                return Response(_forecast_file_payload())
            raise AssertionError(f"Unexpected CWA URL: {url}")

    monkeypatch.setattr("shiro_mlops.data.cwa_client.httpx.Client", FileClient)

    release = CWAClient(api_key=api_key).fetch_forecast_release("F-D0047-089")

    assert release.issued_at == pd.Timestamp("2026-09-15 05:00:00")
    assert release.source_updated_at == pd.Timestamp("2026-09-15 05:30:00")
    assert release.forecasts[0].temperature_c == 31.0
    assert release.raw_payload == _forecast_file_payload()
    assert requests == [
        (file_url, {"params": {"Authorization": api_key}, "follow_redirects": False}),
        (object_url, {}),
    ]


def test_client_rejects_unapproved_forecast_file_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CWA forecast downloads must not redirect credentials to unapproved hosts."""
    requests: list[str] = []

    class Response:
        status_code = 302
        headers = {"location": "https://untrusted.example/forecast.xml"}

        def raise_for_status(self) -> None:
            return None

    class FileClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, url: str, **_: object) -> Response:
            requests.append(url)
            return Response()

    monkeypatch.setattr("shiro_mlops.data.cwa_client.httpx.Client", FileClient)

    with pytest.raises(ValueError, match="not an approved HTTPS target"):
        CWAClient().fetch_forecast_release("F-D0047-089")

    assert requests == ["https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/F-D0047-089"]


def test_client_does_not_expose_authorization_in_file_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed file requests must not echo the authorization query value."""

    class Response:
        status_code = 401

        def raise_for_status(self) -> None:
            raise RuntimeError("https://example.test/?Authorization=sensitive-query-value")

    class FileClient:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def get(self, *_: object, **__: object) -> Response:
            return Response()

    monkeypatch.setattr("shiro_mlops.data.cwa_client.httpx.Client", FileClient)

    with pytest.raises(ValueError, match="got 401") as exc_info:
        CWAClient().fetch_forecast_release("F-D0047-089")

    assert "sensitive-query-value" not in str(exc_info.value)


def test_client_rejects_xml_entities_in_forecast_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forecast XML parsing must reject entity declarations from external input."""
    payload = """<!DOCTYPE cwaopendata [<!ENTITY unsafe "unsafe">]>
<cwaopendata>
  <Dataset>
    <DatasetInfo>
      <IssueTime>2026-09-15T05:00:00+08:00</IssueTime>
      <Update>2026-09-15T05:30:00+08:00</Update>
    </DatasetInfo>
    <Locations><Location><Geocode>63000000</Geocode><LocationName>&unsafe;</LocationName></Location></Locations>
  </Dataset>
</cwaopendata>"""
    monkeypatch.setattr(CWAClient, "_fetch_forecast_file", lambda *_: payload)

    with pytest.raises(DefusedXmlException):
        CWAClient().fetch_forecast_release("F-D0047-089")


def test_client_rejects_unapproved_forecast_file_api_url() -> None:
    """The CWA membership key must only be sent to the approved API origin."""
    client = CWAClient()
    client.forecast_urls["F-D0047-089"] = "https://untrusted.example/forecast.xml"

    with pytest.raises(ValueError, match="file API URL is not an approved HTTPS target"):
        client.fetch_forecast_release("F-D0047-089")


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


@pytest.mark.parametrize("value", ["upstream-schema-changed", "NaN", "Infinity"])
def test_observation_parser_rejects_invalid_numbers_with_source_context(value: str) -> None:
    payload = _observation_payload()
    payload["records"]["Station"][0]["WeatherElement"]["AirTemperature"] = value

    with pytest.raises(ValueError, match="466920.*temperature_c"):
        parse_observation_batch(payload)


def test_forecast_parser_rejects_invalid_numbers_with_source_context() -> None:
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:20:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000000",
                            "weatherElement": [
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "elementValue": [{"value": "invalid-temperature"}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ],
        },
    }

    with pytest.raises(ValueError, match="F-D0047-089.*63000000.*temperature_c"):
        parse_forecast_release(payload, dataset_id="F-D0047-089")


def test_forecast_parser_treats_hyphen_as_missing_numeric_and_text() -> None:
    """F-D0047-091 emits '-' when a period has no value, including PoP."""
    payload = {
        "records": {
            "IssueTime": "2026-09-29T17:00:00+08:00",
            "Update": "2026-09-29T17:00:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000000",
                            "weatherElement": [
                                {
                                    "elementName": "PoP12h",
                                    "time": [
                                        {
                                            "startTime": "2026-10-03T06:00:00+08:00",
                                            "endTime": "2026-10-03T18:00:00+08:00",
                                            "elementValue": [{"value": "-"}],
                                        }
                                    ],
                                },
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "startTime": "2026-10-03T06:00:00+08:00",
                                            "endTime": "2026-10-03T18:00:00+08:00",
                                            "elementValue": [{"value": "28"}],
                                        }
                                    ],
                                },
                                {
                                    "elementName": "WD",
                                    "time": [
                                        {
                                            "startTime": "2026-10-03T06:00:00+08:00",
                                            "endTime": "2026-10-03T18:00:00+08:00",
                                            "elementValue": [{"value": "-"}],
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

    release = parse_forecast_release(payload, dataset_id="F-D0047-091")
    point = release.forecasts[0]

    assert point.valid_from == pd.Timestamp("2026-10-03 06:00:00")
    assert point.probability_of_precipitation_pct is None
    assert point.temperature_c == 28.0
    assert point.wind_direction is None


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
                            "geocode": "63000000",
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
    assert release.missing_geocodes == ("64000000", "66000000")
    assert release.raw_payload == payload
    point = next(point for point in release.forecasts if point.valid_from.hour == 12)
    assert point.geocode == "63000000"
    assert point.temperature_c == 31.0
    assert point.relative_humidity_pct == 70.0
    assert point.valid_to == point.valid_from


def test_parse_forecast_release_rejects_live_opendata_json_without_source_vintage() -> None:
    """A missing source vintage cannot be replaced with the fetch time."""
    payload = {
        "success": "true",
        "records": {
            "Locations": [
                {
                    "DatasetDescription": "臺灣各縣市鄉鎮未來3天天氣預報",
                    "LocationsName": "台灣",
                    "Dataid": "D0047-089",
                    "Location": [
                        {
                            "LocationName": "臺北市",
                            "Geocode": "63000000",
                            "WeatherElement": [
                                {
                                    "ElementName": "溫度",
                                    "Time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "ElementValue": [{"Temperature": "31"}],
                                        }
                                    ],
                                },
                                {
                                    "ElementName": "相對濕度",
                                    "Time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "ElementValue": [{"RelativeHumidity": "70"}],
                                        }
                                    ],
                                },
                                {
                                    "ElementName": "風向",
                                    "Time": [
                                        {
                                            "DataTime": "2026-08-20T12:00:00+08:00",
                                            "ElementValue": [{"WindDirection": "偏東風"}],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    }

    with pytest.raises(ValueError, match="missing or invalid IssueTime/Update"):
        parse_forecast_release(
            payload,
            dataset_id="F-D0047-089",
            fetched_at=datetime(2026, 8, 20, 11, 40),
        )


def test_parse_forecast_release_rejects_invalid_source_vintage() -> None:
    """Reject a source vintage that is present but cannot be parsed."""
    payload = {
        "records": {
            "IssueTime": "not-a-timestamp",
            "Update": "also-not-a-timestamp",
            "locations": [],
        }
    }

    with pytest.raises(ValueError, match="missing or invalid IssueTime/Update"):
        parse_forecast_release(payload, dataset_id="F-D0047-089")


def test_parse_forecast_release_reads_dataset_info_vintage() -> None:
    payload = {
        "records": {
            "datasetInfo": {
                "issueTime": "2026-08-20T11:00:00+08:00",
                "update": "2026-08-20T11:20:00+08:00",
            },
            "Locations": [],
        }
    }

    release = parse_forecast_release(
        payload,
        dataset_id="F-D0047-089",
        fetched_at=datetime(2026, 8, 20, 11, 40),
    )

    assert release.issued_at == pd.Timestamp("2026-08-20 11:00:00")
    assert release.source_updated_at == pd.Timestamp("2026-08-20 11:20:00")


def test_parse_forecast_release_uses_interval_boundaries() -> None:
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:00:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000000",
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


def test_parse_forecast_release_marks_a_geocode_missing_when_all_its_times_are_invalid() -> None:
    """A present location without usable child rows must remain retryable as incomplete."""
    payload = {
        "records": {
            "IssueTime": "2026-08-20T11:00:00+08:00",
            "Update": "2026-08-20T11:00:00+08:00",
            "locations": [
                {
                    "location": [
                        {
                            "geocode": "63000000",
                            "weatherElement": [
                                {
                                    "elementName": "T",
                                    "time": [
                                        {
                                            "DataTime": "not-a-time",
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

    release = parse_forecast_release(payload, dataset_id="F-D0047-089")

    assert "63000000" in release.missing_geocodes


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
                            "geocode": "63000000",
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
    rows = test_repo.fetch_cwa_forecast_rows(geocode="63000000")

    assert len(rows) == 2
    assert set(rows["source_updated_at"].dt.hour) == {11}
    assert len(set(rows["source_updated_at"])) == 2


def test_forecast_product_write_failure_rolls_back_entire_batch(
    test_repo: TimeSeriesRepository,
) -> None:
    issued_at = pd.Timestamp("2026-08-20 11:00")
    first = CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=issued_at,
        source_updated_at=issued_at,
        fetched_at=issued_at.to_pydatetime(),
        status="complete",
        missing_geocodes=(),
        raw_payload={},
        forecasts=(),
    )
    invalid_second = replace(first, dataset_id="F-D0047-091", status=None)

    with pytest.raises(IntegrityError):
        test_repo.upsert_cwa_forecast_releases([first, invalid_second])

    headers = pd.read_sql_query("SELECT * FROM raw_cwa_forecast_release", test_repo.engine)
    assert headers.empty


def test_repository_json_encodes_xml_forecast_raw_payload(
    test_repo: TimeSeriesRepository,
) -> None:
    """Forecast release headers must store XML source files as JSON strings."""
    source_xml = "<cwaopendata><Dataset /></cwaopendata>"
    release = parse_forecast_release(
        {
            "records": {
                "IssueTime": "2026-08-20T11:00:00+08:00",
                "Update": "2026-08-20T11:20:00+08:00",
                "Locations": [],
            }
        },
        dataset_id="F-D0047-089",
        raw_payload=source_xml,
    )

    assert test_repo.upsert_cwa_forecast_release(release) == 0
    stored = pd.read_sql_query("SELECT raw_payload FROM raw_cwa_forecast_release", test_repo.engine)

    assert json.loads(stored.iloc[0]["raw_payload"]) == source_xml


def test_forecast_query_uses_previous_complete_release_when_latest_lacks_requested_geocode(
    test_repo: TimeSeriesRepository,
) -> None:
    """A newer incomplete release without Taipei must not hide the prior complete vintage."""

    def release(
        issued_at: str,
        status: str,
        geocode: str,
        temperature: float,
    ) -> CWAForecastRelease:
        timestamp = pd.Timestamp(issued_at)
        return CWAForecastRelease(
            dataset_id="F-D0047-089",
            issued_at=timestamp,
            source_updated_at=timestamp,
            fetched_at=timestamp.to_pydatetime(),
            status=status,  # type: ignore[arg-type]
            missing_geocodes=() if status == "complete" else ("63000050",),
            raw_payload={},
            forecasts=(
                CWATownshipForecast(
                    valid_from=pd.Timestamp("2026-08-20 14:00"),
                    valid_to=pd.Timestamp("2026-08-20 14:00"),
                    geocode=geocode,
                    location_name=None,
                    temperature_c=temperature,
                    dew_point_c=None,
                    apparent_temperature_c=None,
                    relative_humidity_pct=70.0,
                    probability_of_precipitation_pct=None,
                    wind_speed_m_s=None,
                    wind_direction=None,
                ),
            ),
        )

    test_repo.upsert_cwa_forecast_release(release("2026-08-20 10:00", "complete", "63000050", 30.0))
    test_repo.upsert_cwa_forecast_release(
        release("2026-08-20 11:00", "incomplete", "63000050", 31.0)
    )
    test_repo.upsert_cwa_forecast_release(
        release("2026-08-20 12:00", "incomplete", "64000040", 32.0)
    )

    rows = test_repo.fetch_cwa_forecast_rows(
        geocode="63000050",
        issued_before="2026-08-20 12:00",
        source_updated_before="2026-08-20 12:00",
    )

    assert list(rows["temperature_c"]) == [30.0]
