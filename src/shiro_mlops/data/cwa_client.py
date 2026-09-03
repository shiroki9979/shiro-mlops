"""Client for fetching Central Weather Administration (CWA) observations and forecasts."""

import json
from typing import Any

import httpx
import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import standardize_taiwan_datetime


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
        self.forecast_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089"

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
