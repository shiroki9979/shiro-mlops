"""Pytest shared fixtures."""

import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def taipower_raw_df() -> pd.DataFrame:
    """Load sample Taipower raw DataFrame."""
    with open(FIXTURES_DIR / "taipower_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@pytest.fixture
def cwa_obs_df() -> pd.DataFrame:
    """Load sample CWA weather observation DataFrame."""
    with open(FIXTURES_DIR / "cwa_obs_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


@pytest.fixture
def cwa_forecast_df() -> pd.DataFrame:
    """Load sample CWA weather forecast DataFrame."""
    with open(FIXTURES_DIR / "cwa_forecast_sample.json", encoding="utf-8") as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df
