"""Client for fetching historical and real-time Taipower grid load data."""

import json

import httpx
import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL


class TaipowerClient:
    """Client for querying Taipower load data APIs."""

    def __init__(
        self,
        base_url: str = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json",
    ) -> None:
        self.base_url = base_url

    def fetch_load_data(self) -> pd.DataFrame:
        """Fetch latest hourly power load records."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.base_url)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            data = json.loads(response.text)

        df = pd.DataFrame(data)
        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = pd.to_datetime(df[DATETIME_COL])
        if LOAD_MW_COL in df.columns:
            df[LOAD_MW_COL] = df[LOAD_MW_COL].astype(float)

        return df
