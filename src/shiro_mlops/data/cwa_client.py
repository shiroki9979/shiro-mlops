"""Client for fetching Central Weather Administration (CWA) observations and forecasts."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

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
    "Taipei": CWALocation("Taipei", "466920", "63000050"),
    "Taichung": CWALocation("Taichung", "467490", "66000050"),
    "Kaohsiung": CWALocation("Kaohsiung", "467441", "64000040"),
}


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
    status: str
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
    status: str
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


def _coerce_number(value: Any, *, zero_markers: set[str] | None = None) -> float | None:
    """Normalize CWA numeric values and documented missing markers."""
    if value is None:
        return None
    raw = str(_source_value(value)).strip()
    if raw in {"", "X", "x", "-99"}:
        return None
    if zero_markers and raw in zero_markers:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


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
            _find_element_value(elements, {"WindDirection", "WD", "WindDir"})
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
                    _find_element_value(elements, {"AirTemperature", "TEMP", "T"})
                ),
                relative_humidity_pct=_coerce_number(
                    _find_element_value(elements, {"RelativeHumidity", "HUMD", "RH"})
                ),
                air_pressure_hpa=_coerce_number(
                    _find_element_value(elements, {"AirPressure", "PRES", "Pressure"})
                ),
                precipitation_mm=_coerce_number(precipitation, zero_markers={"T", "t", "-98"}),
                wind_speed_m_s=_coerce_number(
                    _find_element_value(elements, {"WindSpeed", "WDSD", "WS"})
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


def _forecast_value(value: Any) -> Any:
    """Extract the value field from a forecast element value object."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        for key in ("value", "Value", "description"):
            if key in value:
                return value[key]
    return value


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


def _forecast_numeric(values: dict[str, Any], names: set[str]) -> float | None:
    """Normalize a numeric forecast element from its aliases."""
    raw = _find_element_value(values, names)
    return _coerce_number(raw, zero_markers={"-98", "T", "t"})


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
) -> CWAForecastRelease:
    """Parse a versioned CWA township forecast response."""
    records = payload.get("records", {}) if isinstance(payload, dict) else {}
    issued_at = _forecast_timestamp(
        records.get("IssueTime")
        or records.get("issueTime")
        or (payload.get("IssueTime") if isinstance(payload, dict) else None)
    )
    source_updated_at = _forecast_timestamp(
        records.get("Update")
        or records.get("update")
        or (payload.get("Update") if isinstance(payload, dict) else None)
    )
    fetch_time = fetched_at or datetime.now(ZoneInfo("Asia/Taipei"))
    if issued_at is None or source_updated_at is None:
        raise ValueError("CWA forecast response is missing or invalid IssueTime/Update")

    catalog = locations or DEFAULT_CWA_LOCATIONS
    expected_geocodes = {location.geocode for location in catalog.values()}
    forecasts: list[CWATownshipForecast] = []
    seen_geocodes: set[str] = set()
    aliases = {
        "temperature_c": {"T", "Temperature", "AirTemperature"},
        "dew_point_c": {"Td", "DewPoint", "DewPointTemperature"},
        "apparent_temperature_c": {"AT", "ApparentTemperature"},
        "relative_humidity_pct": {"RH", "RelativeHumidity"},
        "probability_of_precipitation_pct": {"PoP6h", "PoP12h", "PoP24h", "PoP"},
        "wind_speed_m_s": {"WS", "WindSpeed"},
    }
    for location in _forecast_locations(payload):
        geocode = str(location.get("geocode") or location.get("Geocode") or "").strip()
        if not geocode or geocode not in expected_geocodes:
            continue
        seen_geocodes.add(geocode)
        for (valid_from, valid_to), values in _forecast_element_rows(location).items():
            forecasts.append(
                CWATownshipForecast(
                    valid_from=valid_from,
                    valid_to=valid_to,
                    geocode=geocode,
                    location_name=location.get("locationName") or location.get("LocationName"),
                    temperature_c=_forecast_numeric(values, aliases["temperature_c"]),
                    dew_point_c=_forecast_numeric(values, aliases["dew_point_c"]),
                    apparent_temperature_c=_forecast_numeric(
                        values, aliases["apparent_temperature_c"]
                    ),
                    relative_humidity_pct=_forecast_numeric(
                        values, aliases["relative_humidity_pct"]
                    ),
                    probability_of_precipitation_pct=_forecast_numeric(
                        values, aliases["probability_of_precipitation_pct"]
                    ),
                    wind_speed_m_s=_forecast_numeric(values, aliases["wind_speed_m_s"]),
                    wind_direction=_forecast_text(values, {"WD", "WindDirection"}),
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
        raw_payload=payload,
        forecasts=tuple(forecasts),
    )


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
            "F-D0047-089": "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089",
            "F-D0047-091": "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-091",
        }
        self.forecast_url = self.forecast_urls["F-D0047-089"]

    def fetch_observation_batch(
        self, locations: dict[str, CWALocation] | None = None
    ) -> CWAObservationBatch:
        """Fetch and parse all configured station observations as one batch."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.obs_url, params={"Authorization": self.api_key})
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = json.loads(response.text)
        return parse_observation_batch(payload, locations=locations)

    def fetch_forecast_release(
        self,
        dataset_id: str,
        locations: dict[str, CWALocation] | None = None,
    ) -> CWAForecastRelease:
        """Fetch and parse one versioned township forecast dataset."""
        if dataset_id not in self.forecast_urls:
            raise ValueError(f"Unsupported CWA forecast dataset: {dataset_id}")
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                self.forecast_urls[dataset_id], params={"Authorization": self.api_key}
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            payload = json.loads(response.text)
        return parse_forecast_release(payload, dataset_id=dataset_id, locations=locations)

    def fetch_observations(self, location: str = "Taipei") -> pd.DataFrame:
        """Fetch latest weather observations."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                self.obs_url, params={"Authorization": self.api_key, "locationName": location}
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = json.loads(response.text)

        df = _parse_cwa_observations_payload(data, fallback_location=location)

        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = standardize_taiwan_datetime(df[DATETIME_COL])
        if TEMPERATURE_COL in df.columns:
            df[TEMPERATURE_COL] = pd.to_numeric(df[TEMPERATURE_COL], errors="coerce").astype(float)
        if RELATIVE_HUMIDITY_COL in df.columns:
            df[RELATIVE_HUMIDITY_COL] = pd.to_numeric(
                df[RELATIVE_HUMIDITY_COL], errors="coerce"
            ).astype(float)

        return df

    def fetch_forecast(self, location: str = "Taipei", horizon_hours: int = 24) -> pd.DataFrame:
        """Fetch future weather forecasts for up to horizon_hours."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                self.forecast_url, params={"Authorization": self.api_key, "locationName": location}
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = json.loads(response.text)

        df = _parse_cwa_observations_payload(data, fallback_location=location)

        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = standardize_taiwan_datetime(df[DATETIME_COL])
        if TEMPERATURE_COL in df.columns:
            df[TEMPERATURE_COL] = pd.to_numeric(df[TEMPERATURE_COL], errors="coerce").astype(float)
        if RELATIVE_HUMIDITY_COL in df.columns:
            df[RELATIVE_HUMIDITY_COL] = pd.to_numeric(
                df[RELATIVE_HUMIDITY_COL], errors="coerce"
            ).astype(float)

        if len(df) > horizon_hours:
            df = df.head(horizon_hours)

        return df
