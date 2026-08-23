"""Integration tests for Taipower and CWA clients with mocked network responses."""

from pathlib import Path

import httpx
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
