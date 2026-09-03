"""Integration tests for Taipower and CWA clients with mocked network responses."""

from pathlib import Path

import httpx
import pandas as pd
import pytest

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.taipower_client import TaipowerClient

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def test_taipower_client_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test TaipowerClient with mock JSON fixture."""
    with open(FIXTURES_DIR / "taipower_sample.json", encoding="utf-8") as f:
        mock_json_str = f.read()

    class MockResponse:
        status_code = 200
        text = mock_json_str

        def raise_for_status(self) -> None:
            pass

    client = TaipowerClient()
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: MockResponse())

    df = client.fetch_load_data()
    assert not df.empty
    assert DATETIME_COL in df.columns
    assert LOAD_MW_COL in df.columns
    assert len(df) == 48


def test_cwa_client_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test CWAClient observation and forecast parsing with mock JSON fixtures."""
    with open(FIXTURES_DIR / "cwa_obs_sample.json", encoding="utf-8") as f:
        obs_json_str = f.read()

    with open(FIXTURES_DIR / "cwa_forecast_sample.json", encoding="utf-8") as f:
        forecast_json_str = f.read()

    class MockObsResponse:
        status_code = 200
        text = obs_json_str

    class MockForecastResponse:
        status_code = 200
        text = forecast_json_str

    cwa_client = CWAClient(api_key="test_key")

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, *args, **kwargs: (
            MockForecastResponse() if "F-D0047-089" in str(url) else MockObsResponse()
        ),
    )

    obs_df = cwa_client.fetch_observations()
    assert not obs_df.empty
    assert "temperature" in obs_df.columns

    forecast_df = cwa_client.fetch_forecast(horizon_hours=12)
    assert len(forecast_df) == 12
    assert "temperature" in forecast_df.columns


def test_taipower_client_csv_parsing_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test TaipowerClient with realistic CSV open data fixture."""
    with open(FIXTURES_DIR / "taipower_sample.csv", encoding="utf-8") as f:
        mock_csv_str = f.read()

    class MockResponse:
        status_code = 200
        text = mock_csv_str

        def raise_for_status(self) -> None:
            pass

    client = TaipowerClient(
        base_url="https://data.taipower.com.tw/opendata/apply/file/d015046/台灣電力公司_過去電力供需資訊.csv"
    )
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: MockResponse())

    df = client.fetch_load_data()
    assert not df.empty
    assert DATETIME_COL in df.columns
    assert LOAD_MW_COL in df.columns
    assert len(df) == 24
    assert pd.api.types.is_datetime64_any_dtype(df[DATETIME_COL])
    assert pd.api.types.is_float_dtype(df[LOAD_MW_COL])
    # 2650.0 萬瓩 * 10 = 26500.0 MW
    assert df.iloc[0][LOAD_MW_COL] == pytest.approx(26500.0)


def test_cwa_client_nested_payload_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test CWAClient with realistic nested Station/WeatherElement JSON fixture."""
    with open(FIXTURES_DIR / "cwa_obs_nested_sample.json", encoding="utf-8") as f:
        mock_nested_json = f.read()

    class MockResponse:
        status_code = 200
        text = mock_nested_json

        def raise_for_status(self) -> None:
            pass

    cwa_client = CWAClient(api_key="test_key")
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: MockResponse())

    df = cwa_client.fetch_observations()
    assert not df.empty
    assert DATETIME_COL in df.columns
    assert "location" in df.columns
    assert "temperature" in df.columns
    assert "relative_humidity" in df.columns
    assert len(df) == 2

    locations = set(df["location"])
    assert "Taipei" in locations
    assert "Kaohsiung" in locations

    taipei_row = df[df["location"] == "Taipei"].iloc[0]
    assert taipei_row["temperature"] == pytest.approx(35.7)
    assert taipei_row["relative_humidity"] == pytest.approx(57.0)
