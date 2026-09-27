"""Client for fetching Central Weather Administration (CWA) observations and forecasts."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
from defusedxml import ElementTree

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime


@dataclass(frozen=True)
class CWALocation:
    """Stable mapping between public alias and CWA source identities."""

    alias: str
    station_id: str
    geocode: str


DEFAULT_CWA_LOCATIONS: dict[str, CWALocation] = {
    "Taipei": CWALocation("Taipei", "466920", "63000000"),
    "Taichung": CWALocation("Taichung", "467490", "66000000"),
    "Kaohsiung": CWALocation("Kaohsiung", "467441", "64000000"),
}

CWAIngestionStatus = Literal["complete", "incomplete"]

_CWA_FORECAST_FILE_API = "https://opendata.cwa.gov.tw/fileapi/v1/opendataapi"
_CWA_FORECAST_FILE_API_HOST = "opendata.cwa.gov.tw"
_CWA_FORECAST_FILE_HOST = "cwaopendata.s3.ap-northeast-1.amazonaws.com"
_CWA_FORECAST_FILE_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class CWAStationObservation:
    """Canonical typed observation parsed from one CWA station row."""

    observed_at: pd.Timestamp
    station_id: str
    station_name: str | None
    town_code: str | None
    temperature_c: float | None
    relative_humidity_pct: float | None
    air_pressure_hpa: float | None
    precipitation_mm: float | None
    wind_speed_m_s: float | None
    wind_direction_deg: float | None


@dataclass(frozen=True)
class CWAObservationBatch:
    """One source response and its canonical observations."""

    fetched_at: datetime
    status: CWAIngestionStatus
    missing_station_ids: tuple[str, ...]
    raw_payload: Any
    observations: tuple[CWAStationObservation, ...]


@dataclass(frozen=True)
class CWATownshipForecast:
    """Canonical typed forecast row for one township and valid interval."""

    valid_from: pd.Timestamp
    valid_to: pd.Timestamp
    geocode: str
    location_name: str | None
    temperature_c: float | None
    dew_point_c: float | None
    apparent_temperature_c: float | None
    relative_humidity_pct: float | None
    probability_of_precipitation_pct: float | None
    wind_speed_m_s: float | None
    wind_direction: str | None


@dataclass(frozen=True)
class CWAForecastRelease:
    """One versioned CWA forecast response and its typed township rows."""

    dataset_id: str
    issued_at: pd.Timestamp
    source_updated_at: pd.Timestamp
    fetched_at: datetime
    status: CWAIngestionStatus
    missing_geocodes: tuple[str, ...]
    raw_payload: Any
    forecasts: tuple[CWATownshipForecast, ...]


def _normalize_location_name(name: str) -> str:
    """Normalize common Chinese station names to standard English identifiers."""
    mapping = {
        "臺北": "Taipei",
        "台北": "Taipei",
        "臺中": "Taichung",
        "台中": "Taichung",
        "高雄": "Kaohsiung",
    }
    return mapping.get(name.strip(), name.strip())


def _source_value(value: Any) -> Any:
    """Extract a scalar source value from CWA's value-object variants."""
    if isinstance(value, dict):
        for key in ("value", "Value", "Precipitation", "valueDescription"):
            if key in value:
                return value[key]
    return value


def _find_element_value(elements: Any, names: set[str]) -> Any:
    """Find an element value across dict and list-shaped CWA payloads."""
    if isinstance(elements, dict):
        for name in names:
            if name in elements:
                return _source_value(elements[name])
        for key, value in elements.items():
            if str(key).lower() in {name.lower() for name in names}:
                return _source_value(value)
        return None
    if isinstance(elements, list):
        for element in elements:
            if not isinstance(element, dict):
                continue
            element_name = element.get("elementName") or element.get("ElementName")
            if element_name in names:
                raw = element.get("elementValue", element.get("ElementValue"))
                return _source_value(raw)
    return None


def _coerce_number(
    value: Any, context: str, *, zero_markers: set[str] | None = None
) -> float | None:
    """Normalize CWA numeric values and documented missing markers."""
    if value is None:
        return None
    raw = str(_source_value(value)).strip()
    if raw in {"", "X", "x", "-99"}:
        return None
    if zero_markers and raw in zero_markers:
        return 0.0
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid CWA numeric value for {context}: {raw!r}") from exc
    if not math.isfinite(number):
        raise ValueError(f"Non-finite CWA numeric value for {context}: {raw!r}")
    return number


def _observation_datetime(value: Any) -> pd.Timestamp | None:
    """Normalize an observation timestamp to timezone-naive Taiwan local time."""
    if isinstance(value, dict):
        value = value.get("DateTime") or value.get("datetime") or value.get("obsTime")
    if value is None:
        return None
    try:
        return pd.Timestamp(standardize_taiwan_datetime(pd.Series([value])).iloc[0])
    except (TypeError, ValueError):
        return None


def _station_records(payload: Any) -> list[dict[str, Any]]:
    """Locate station rows in flat and nested CWA observation responses."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    records = payload.get("records") or payload.get("Records") or {}
    if isinstance(records, dict):
        stations = records.get("Station") or records.get("station") or records.get("location")
        if isinstance(stations, list):
            return [row for row in stations if isinstance(row, dict)]
    return []


def parse_observation_batch(
    payload: Any,
    *,
    fetched_at: datetime | None = None,
    locations: dict[str, CWALocation] | None = None,
) -> CWAObservationBatch:
    """Parse one CWA observation response into a canonical batch."""
    catalog = locations or DEFAULT_CWA_LOCATIONS
    stations_by_id = {location.station_id: location for location in catalog.values()}
    observations: list[CWAStationObservation] = []
    seen_station_ids: set[str] = set()

    for station in _station_records(payload):
        station_id = str(station.get("StationId") or station.get("stationId") or "").strip()
        if not station_id or station_id not in stations_by_id:
            continue
        observed_at = _observation_datetime(
            station.get("ObsTime") or station.get("obsTime") or station.get("time")
        )
        if observed_at is None:
            continue
        elements = station.get("WeatherElement") or station.get("weatherElement") or {}
        precipitation = _find_element_value(elements, {"Precipitation", "NOW", "Now"})
        if isinstance(elements, dict) and isinstance(elements.get("Now"), dict):
            precipitation = elements["Now"].get("Precipitation", precipitation)
        wind_direction = _coerce_number(
            _find_element_value(elements, {"WindDirection", "WD", "WindDir"}),
            f"station {station_id} wind_direction_deg",
        )
        if wind_direction == 990:
            wind_direction = None
        observations.append(
            CWAStationObservation(
                observed_at=observed_at,
                station_id=station_id,
                station_name=station.get("StationName") or station.get("stationName"),
                town_code=str(station.get("TownCode") or station.get("townCode") or "") or None,
                temperature_c=_coerce_number(
                    _find_element_value(elements, {"AirTemperature", "TEMP", "T"}),
                    f"station {station_id} temperature_c",
                ),
                relative_humidity_pct=_coerce_number(
                    _find_element_value(elements, {"RelativeHumidity", "HUMD", "RH"}),
                    f"station {station_id} relative_humidity_pct",
                ),
                air_pressure_hpa=_coerce_number(
                    _find_element_value(elements, {"AirPressure", "PRES", "Pressure"}),
                    f"station {station_id} air_pressure_hpa",
                ),
                precipitation_mm=_coerce_number(
                    precipitation,
                    f"station {station_id} precipitation_mm",
                    zero_markers={"T", "t", "-98"},
                ),
                wind_speed_m_s=_coerce_number(
                    _find_element_value(elements, {"WindSpeed", "WDSD", "WS"}),
                    f"station {station_id} wind_speed_m_s",
                ),
                wind_direction_deg=wind_direction,
            )
        )
        seen_station_ids.add(station_id)

    missing = tuple(sorted(set(stations_by_id) - seen_station_ids))
    return CWAObservationBatch(
        fetched_at=fetched_at or datetime.now(ZoneInfo("Asia/Taipei")),
        status="complete" if not missing else "incomplete",
        missing_station_ids=missing,
        raw_payload=payload,
        observations=tuple(observations),
    )


def _forecast_timestamp(value: Any) -> pd.Timestamp | None:
    """Normalize a forecast timestamp to timezone-naive Taiwan local time."""
    if value is None:
        return None
    try:
        return pd.Timestamp(standardize_taiwan_datetime(pd.Series([value])).iloc[0])
    except (TypeError, ValueError):
        return None


def _forecast_locations(payload: Any) -> list[dict[str, Any]]:
    """Flatten CWA township forecast location containers."""
    if not isinstance(payload, dict):
        return []
    records = payload.get("records") or payload.get("Records") or {}
    containers = records.get("locations") or records.get("Locations") or []
    if isinstance(containers, dict):
        containers = [containers]
    result: list[dict[str, Any]] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        locations = container.get("location") or container.get("Location") or []
        if isinstance(locations, dict):
            locations = [locations]
        result.extend(row for row in locations if isinstance(row, dict))
    return result


_FORECAST_VALUE_KEYS = (
    "value",
    "Value",
    "description",
    "Temperature",
    "DewPoint",
    "DewPointTemperature",
    "ApparentTemperature",
    "RelativeHumidity",
    "ProbabilityOfPrecipitation",
    "WindSpeed",
    "WindDirection",
)


def _as_mapping(value: Any) -> dict[str, Any]:
    """將 payload 片段正規化為 mapping。"""
    return value if isinstance(value, dict) else {}


def _first_present(*values: Any) -> Any:
    """取得第一個非空的 CWA 欄位候選值。"""
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _forecast_value(value: Any) -> Any:
    """從預報氣象因子值物件取得實際值。"""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        for key in _FORECAST_VALUE_KEYS:
            if key in value:
                return value[key]
        for nested in value.values():
            if nested not in (None, ""):
                return nested
    return value


def _forecast_metadata_value(
    sources: tuple[dict[str, Any], ...],
    field_names: tuple[str, str],
) -> Any:
    """依 CWA payload 的常見層級取得預報版本欄位。"""
    return _first_present(*(source.get(name) for source in sources for name in field_names))


def _forecast_release_timestamps(payload: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    """讀取來源 IssueTime 與 Update 作為預報版本身分。"""
    records = _as_mapping(payload.get("records") if isinstance(payload, dict) else None)
    dataset_info = _as_mapping(records.get("datasetInfo") or records.get("DatasetInfo"))
    containers = records.get("Locations") or records.get("locations") or []
    first_container = _as_mapping(
        containers[0] if isinstance(containers, list) and containers else None
    )
    payload_map = _as_mapping(payload)
    issued_at = _forecast_timestamp(
        _forecast_metadata_value(
            (records, dataset_info, first_container, payload_map),
            ("IssueTime", "issueTime"),
        )
    )
    source_updated_at = _forecast_timestamp(
        _forecast_metadata_value(
            (records, dataset_info, first_container, payload_map),
            ("Update", "update"),
        )
    )
    if issued_at is None or source_updated_at is None:
        raise ValueError("CWA forecast response is missing or invalid IssueTime/Update")
    return issued_at, source_updated_at


def _forecast_element_rows(
    location: dict[str, Any],
) -> dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]]:
    """Collect forecast elements into rows keyed by valid interval."""
    rows: dict[tuple[pd.Timestamp, pd.Timestamp], dict[str, Any]] = {}
    elements = location.get("weatherElement") or location.get("WeatherElement") or []
    if isinstance(elements, dict):
        elements = [elements]
    for element in elements:
        if not isinstance(element, dict):
            continue
        name = str(element.get("elementName") or element.get("ElementName") or "")
        times = element.get("time") or element.get("Time") or []
        if isinstance(times, dict):
            times = [times]
        for time_row in times:
            if not isinstance(time_row, dict):
                continue
            valid_from = _forecast_timestamp(
                time_row.get("DataTime")
                or time_row.get("dataTime")
                or time_row.get("StartTime")
                or time_row.get("startTime")
            )
            valid_to = (
                _forecast_timestamp(
                    time_row.get("EndTime") or time_row.get("endTime") or time_row.get("endtime")
                )
                or valid_from
            )
            if valid_from is None or valid_to is None:
                continue
            values = time_row.get("elementValue") or time_row.get("ElementValue")
            value = _forecast_value(values)
            rows.setdefault((valid_from, valid_to), {})[name] = value
    return rows


def _forecast_numeric(values: dict[str, Any], names: set[str], context: str) -> float | None:
    """Normalize a numeric forecast element from its aliases."""
    raw = _find_element_value(values, names)
    return _coerce_number(raw, context, zero_markers={"-98", "T", "t"})


def _forecast_text(values: dict[str, Any], names: set[str]) -> str | None:
    """Read a non-numeric forecast element without interpolation."""
    for name in names:
        if name in values and values[name] not in (None, "", "X", "-99"):
            value = _source_value(values[name])
            return None if value in (None, "", "X", "-99") else str(value)
    return None


def parse_forecast_release(
    payload: Any,
    *,
    dataset_id: str,
    fetched_at: datetime | None = None,
    locations: dict[str, CWALocation] | None = None,
    raw_payload: Any | None = None,
) -> CWAForecastRelease:
    """Parse a versioned CWA township forecast response."""
    fetch_time = fetched_at or datetime.now(ZoneInfo("Asia/Taipei"))
    issued_at, source_updated_at = _forecast_release_timestamps(payload)

    catalog = locations or DEFAULT_CWA_LOCATIONS
    expected_geocodes = {location.geocode for location in catalog.values()}
    forecasts: list[CWATownshipForecast] = []
    seen_geocodes: set[str] = set()
    aliases = {
        "temperature_c": {"T", "Temperature", "AirTemperature", "溫度", "平均溫度"},
        "dew_point_c": {"Td", "DewPoint", "DewPointTemperature", "露點溫度", "平均露點溫度"},
        "apparent_temperature_c": {"AT", "ApparentTemperature", "體感溫度", "最高體感溫度"},
        "relative_humidity_pct": {"RH", "RelativeHumidity", "相對濕度", "平均相對濕度"},
        "probability_of_precipitation_pct": {
            "PoP6h",
            "PoP12h",
            "PoP24h",
            "PoP",
            "3小時降雨機率",
            "12小時降雨機率",
        },
        "wind_speed_m_s": {"WS", "WindSpeed", "風速"},
    }
    for location in _forecast_locations(payload):
        geocode = str(location.get("geocode") or location.get("Geocode") or "").strip()
        if not geocode or geocode not in expected_geocodes:
            continue
        element_rows = _forecast_element_rows(location)
        if not element_rows:
            continue
        seen_geocodes.add(geocode)
        for (valid_from, valid_to), values in element_rows.items():
            forecasts.append(
                CWATownshipForecast(
                    valid_from=valid_from,
                    valid_to=valid_to,
                    geocode=geocode,
                    location_name=location.get("locationName") or location.get("LocationName"),
                    **{
                        field: _forecast_numeric(
                            values,
                            names,
                            f"dataset {dataset_id} geocode {geocode} {valid_from} {field}",
                        )
                        for field, names in aliases.items()
                    },
                    wind_direction=_forecast_text(values, {"WD", "WindDirection", "風向"}),
                )
            )
    forecasts.sort(key=lambda row: (row.geocode, row.valid_from, row.valid_to))
    missing_geocodes = tuple(sorted(expected_geocodes - seen_geocodes))
    return CWAForecastRelease(
        dataset_id=dataset_id,
        issued_at=issued_at,
        source_updated_at=source_updated_at,
        fetched_at=fetch_time,
        status="complete" if not missing_geocodes else "incomplete",
        missing_geocodes=missing_geocodes,
        raw_payload=payload if raw_payload is None else raw_payload,
        forecasts=tuple(forecasts),
    )


def _xml_tag_name(tag: str) -> str:
    """Remove an XML namespace from a CWA element name."""
    return tag.rsplit("}", maxsplit=1)[-1]


def _xml_value(element: Element) -> Any:
    """Convert one CWA XML element into the JSON-like shape used by the parser."""
    children = list(element)
    if not children:
        return (element.text or "").strip()

    value: dict[str, Any] = {}
    for child in children:
        name = _xml_tag_name(child.tag)
        child_value = _xml_value(child)
        existing = value.get(name)
        if existing is None:
            value[name] = child_value
        elif isinstance(existing, list):
            existing.append(child_value)
        else:
            value[name] = [existing, child_value]
    return value


def _parse_forecast_file_payload(payload: str) -> dict[str, Any]:
    """Adapt CWA's versioned XML file into the canonical forecast parser input."""
    root = ElementTree.fromstring(payload)
    document = _xml_value(root)
    dataset = document.get("Dataset") if isinstance(document, dict) else None
    if not isinstance(dataset, dict):
        raise ValueError("CWA forecast file is missing Dataset")
    return {"records": dataset}


def _parse_cwa_observations_payload(data: Any, fallback_location: str = "Taipei") -> pd.DataFrame:
    """Parse flat or nested CWA observation payload into standardized DataFrame."""
    if isinstance(data, list):
        df = pd.DataFrame(data)
        if LOCATION_COL not in df.columns:
            df[LOCATION_COL] = fallback_location
        return df

    if not isinstance(data, dict):
        return pd.DataFrame(
            columns=[DATETIME_COL, LOCATION_COL, TEMPERATURE_COL, RELATIVE_HUMIDITY_COL]
        )

    records = data.get("records", {})
    stations = records.get("Station") or records.get("location") or []

    rows: list[dict[str, Any]] = []
    for st in stations:
        raw_loc = st.get("StationName") or st.get("locationName") or fallback_location
        loc = _normalize_location_name(str(raw_loc))

        # Extract observation datetime
        obs_time = st.get("ObsTime") or st.get("obsTime") or st.get("time")
        if isinstance(obs_time, dict):
            dt_str = obs_time.get("DateTime") or obs_time.get("obsTime")
        else:
            dt_str = obs_time

        temp: float | None = None
        rh: float | None = None

        we = st.get("WeatherElement") or st.get("weatherElement")
        if isinstance(we, dict):
            t_val = (
                we.get("AirTemperature") if we.get("AirTemperature") is not None else we.get("TEMP")
            )
            if t_val is not None:
                try:
                    temp = float(t_val)
                except (ValueError, TypeError):
                    pass
            h_val = (
                we.get("RelativeHumidity")
                if we.get("RelativeHumidity") is not None
                else we.get("HUMD")
            )
            if h_val is not None:
                try:
                    rh = float(h_val)
                except (ValueError, TypeError):
                    pass
        elif isinstance(we, list):
            for elem in we:
                elem_name = elem.get("elementName")
                raw_val = elem.get("elementValue")
                if isinstance(raw_val, dict):
                    raw_val = raw_val.get("value")
                if elem_name in {"AirTemperature", "TEMP"} and raw_val is not None:
                    try:
                        temp = float(raw_val)
                    except (ValueError, TypeError):
                        pass
                elif elem_name in {"RelativeHumidity", "HUMD"} and raw_val is not None:
                    try:
                        rh = float(raw_val)
                    except (ValueError, TypeError):
                        pass

        rows.append(
            {
                DATETIME_COL: dt_str,
                LOCATION_COL: loc,
                TEMPERATURE_COL: temp,
                RELATIVE_HUMIDITY_COL: rh,
            }
        )

    return pd.DataFrame(rows)


class CWAClient:
    """Client for querying Central Weather Administration (CWA) OpenData API."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.obs_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"
        self.forecast_urls = {
            "F-D0047-089": f"{_CWA_FORECAST_FILE_API}/F-D0047-089",
            "F-D0047-091": f"{_CWA_FORECAST_FILE_API}/F-D0047-091",
        }
        self.forecast_url = self.forecast_urls["F-D0047-089"]

    def fetch_observation_batch(
        self, locations: dict[str, CWALocation] | None = None
    ) -> CWAObservationBatch:
        """Fetch and parse all configured station observations as one batch."""
        payload = self._fetch_json(self.obs_url)
        return parse_observation_batch(payload, locations=locations)

    def fetch_forecast_release(
        self,
        dataset_id: str,
        locations: dict[str, CWALocation] | None = None,
    ) -> CWAForecastRelease:
        """Fetch and parse one versioned township forecast dataset."""
        if dataset_id not in self.forecast_urls:
            raise ValueError(f"Unsupported CWA forecast dataset: {dataset_id}")
        raw_payload = self._fetch_forecast_file(self.forecast_urls[dataset_id])
        payload = _parse_forecast_file_payload(raw_payload)
        return parse_forecast_release(
            payload,
            dataset_id=dataset_id,
            locations=locations,
            raw_payload=raw_payload,
        )

    def _fetch_json(self, url: str) -> Any:
        """Fetch one CWA source payload through the canonical ingestion boundary."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params={"Authorization": self.api_key})
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            return json.loads(response.text)

    def _fetch_forecast_file(self, url: str) -> str:
        """Fetch a versioned CWA forecast file without forwarding credentials to storage."""
        file_api_url = self._validated_forecast_file_api_url(url)
        with httpx.Client(timeout=_CWA_FORECAST_FILE_TIMEOUT_SECONDS) as client:
            redirect = client.get(
                file_api_url, params={"Authorization": self.api_key}, follow_redirects=False
            )
            if redirect.status_code != 302:
                raise ValueError(
                    f"CWA forecast file request expected HTTP 302, got {redirect.status_code}"
                )
            location = redirect.headers.get("location")
            if location is None:
                raise ValueError("CWA forecast file response is missing a download location")
            file_url = self._validated_forecast_file_url(location)
            response = client.get(file_url)
            response.raise_for_status()
            return response.text

    @staticmethod
    def _validated_forecast_file_api_url(url: str) -> str:
        """Require the authorized CWA API origin before sending the membership key."""
        target = urlparse(url)
        if (
            target.scheme != "https"
            or target.hostname != _CWA_FORECAST_FILE_API_HOST
            or target.port not in (None, 443)
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
        ):
            raise ValueError("CWA forecast file API URL is not an approved HTTPS target")
        return url

    @staticmethod
    def _validated_forecast_file_url(location: str) -> str:
        """Allow CWA's known HTTPS storage target and reject credential-forwarding redirects."""
        target = urlparse(location)
        if (
            target.scheme != "https"
            or target.hostname != _CWA_FORECAST_FILE_HOST
            or target.port not in (None, 443)
            or target.username is not None
            or target.password is not None
            or target.query
            or target.fragment
        ):
            raise ValueError("CWA forecast file download location is not an approved HTTPS target")
        return location
