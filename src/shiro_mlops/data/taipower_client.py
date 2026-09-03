"""Client for fetching historical and real-time Taipower grid load data."""

import io
import json

import httpx
import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL, LOCATION_COL


class TaipowerClient:
    """Client for querying Taipower load data APIs."""

    def __init__(
        self,
        base_url: str = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json",
    ) -> None:
        self.base_url = base_url

    def fetch_load_data(self) -> pd.DataFrame:
        """Fetch latest hourly power load records from CSV or JSON endpoint."""
        with httpx.Client(timeout=10.0) as client:
            response = client.get(self.base_url)
            if hasattr(response, "raise_for_status"):
                response.raise_for_status()
            text_content = response.text.strip()

        # Attempt JSON parse first if it appears to be JSON
        if text_content.startswith(("[", "{")) and not self.base_url.lower().endswith(".csv"):
            try:
                data = json.loads(text_content)
                df = pd.DataFrame(data)
            except (json.JSONDecodeError, ValueError):
                df = pd.read_csv(io.StringIO(text_content))
        else:
            df = pd.read_csv(io.StringIO(text_content))

        # Standardize datetime column
        datetime_candidates = [DATETIME_COL, "time", "日期", "日期時間", "時間", "觀測時間"]
        for col in datetime_candidates:
            if col in df.columns:
                if col != DATETIME_COL:
                    df = df.rename(columns={col: DATETIME_COL})
                break

        if DATETIME_COL in df.columns:
            df[DATETIME_COL] = pd.to_datetime(df[DATETIME_COL])

        # Standardize load column (handling 萬瓩 unit conversion: 1 萬瓩 = 10 MW)
        if LOAD_MW_COL in df.columns:
            df[LOAD_MW_COL] = pd.to_numeric(df[LOAD_MW_COL], errors="coerce").astype(float)
        elif "尖峰負載(萬瓩)" in df.columns:
            df[LOAD_MW_COL] = (
                pd.to_numeric(df["尖峰負載(萬瓩)"], errors="coerce").astype(float) * 10.0
            )
        elif "尖峰負載(MW)" in df.columns:
            df[LOAD_MW_COL] = pd.to_numeric(df["尖峰負載(MW)"], errors="coerce").astype(float)
        elif "尖峰負載" in df.columns:
            # When unit is 萬瓩 (typical values ~2000-4500)
            raw_vals = pd.to_numeric(df["尖峰負載"], errors="coerce").astype(float)
            if (raw_vals < 10000).all():
                df[LOAD_MW_COL] = raw_vals * 10.0
            else:
                df[LOAD_MW_COL] = raw_vals
        elif "瞬時用電量(萬瓩)" in df.columns:
            df[LOAD_MW_COL] = (
                pd.to_numeric(df["瞬時用電量(萬瓩)"], errors="coerce").astype(float) * 10.0
            )
        elif "瞬時用電量(MW)" in df.columns:
            df[LOAD_MW_COL] = pd.to_numeric(df["瞬時用電量(MW)"], errors="coerce").astype(float)

        output_cols = [DATETIME_COL, LOAD_MW_COL]
        if LOCATION_COL in df.columns:
            output_cols.append(LOCATION_COL)

        return df[output_cols] if set(output_cols).issubset(df.columns) else df
