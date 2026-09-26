"""Integration tests for CWA clients with mocked network responses."""

from pathlib import Path

import httpx
import pandas as pd
import pytest

from shiro_mlops.data.cwa_client import CWAClient

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


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
