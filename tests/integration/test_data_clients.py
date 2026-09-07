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

    batch = cwa_client.fetch_observation_batch()
    assert len(batch.observations) == 1

    stations = {observation.station_id for observation in batch.observations}
    assert stations == {"466920"}
    taipei = next(
        observation for observation in batch.observations if observation.station_id == "466920"
    )
    assert taipei.temperature_c == pytest.approx(35.7)
    assert taipei.relative_humidity_pct == pytest.approx(57.0)
    assert taipei.observed_at == pd.Timestamp("2026-08-20 14:00:00")


def test_taipower_and_cwa_timezone_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Taipower CSV (tz-naive) and CWA nested JSON (tz-aware +08:00) align at identical timestamp."""
    with open(FIXTURES_DIR / "taipower_sample.csv", encoding="utf-8") as f:
        csv_str = f.read()
    with open(FIXTURES_DIR / "cwa_obs_nested_sample.json", encoding="utf-8") as f:
        json_str = f.read()

    class MockCSVResp:
        status_code = 200
        text = csv_str

        def raise_for_status(self) -> None:
            pass

    class MockJSONResp:
        status_code = 200
        text = json_str

        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, *a, **kw: MockCSVResp())
    taipower_client = TaipowerClient()
    load_df = taipower_client.fetch_load_data()

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, *a, **kw: MockJSONResp())
    cwa_client = CWAClient(api_key="test_key")
    weather_batch = cwa_client.fetch_observation_batch()

    # Both clients must yield naive datetime64[ns] in Asia/Taipei
    assert getattr(load_df[DATETIME_COL].dtype, "tz", None) is None
    assert all(observation.observed_at.tzinfo is None for observation in weather_batch.observations)

    # Target timestamp: 2026-08-20 14:00:00 exists in both
    target_dt = pd.Timestamp("2026-08-20 14:00:00")
    assert target_dt in load_df[DATETIME_COL].values
    assert target_dt in {observation.observed_at for observation in weather_batch.observations}
