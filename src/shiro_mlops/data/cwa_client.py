"""Client for fetching Central Weather Administration (CWA) observations and forecasts."""

import json
import pandas as pd
import httpx
from shiro_mlops.core.constants import DATETIME_COL, TEMPERATURE_COL, RELATIVE_HUMIDITY_COL

class CWAClient:
    """Client for querying Central Weather Administration (CWA) OpenData API."""

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key
        self.obs_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"
        self.forecast_url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-089"

    def fetch_observations(self, location: str = "Taipei") -> pd.DataFrame:
        """Fetch latest weather observations."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.obs_url, params={"Authorization": self.api_key, "locationName": location})
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = json.loads(response.text)

        df = pd.DataFrame(data)
        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = pd.to_datetime(df[DATETIME_COL])
        if TEMPERATURE_COL in df.columns:
            df[TEMPERATURE_COL] = df[TEMPERATURE_COL].astype(float)
        if RELATIVE_HUMIDITY_COL in df.columns:
            df[RELATIVE_HUMIDITY_COL] = df[RELATIVE_HUMIDITY_COL].astype(float)

        return df

    def fetch_forecast(self, location: str = "Taipei", horizon_hours: int = 24) -> pd.DataFrame:
        """Fetch future weather forecasts for up to horizon_hours."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                self.forecast_url,
                params={"Authorization": self.api_key, "locationName": location}
            )
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = json.loads(response.text)

        df = pd.DataFrame(data)
        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = pd.to_datetime(df[DATETIME_COL])
        if TEMPERATURE_COL in df.columns:
            df[TEMPERATURE_COL] = df[TEMPERATURE_COL].astype(float)
        if RELATIVE_HUMIDITY_COL in df.columns:
            df[RELATIVE_HUMIDITY_COL] = df[RELATIVE_HUMIDITY_COL].astype(float)

        if len(df) > horizon_hours:
            df = df.head(horizon_hours)

        return df
