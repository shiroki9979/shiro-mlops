"""Opt-in Data Explorer pagination acceptance against an isolated local TimescaleDB."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from tests.unit.test_data_explorer_audit_pagination import assert_observation_audit_pages
from tests.unit.test_data_explorer_forecast_pagination import (
    assert_forecast_audit_pages_keep_complete_sort_key,
    assert_forecast_pages_pin_microsecond_vintage,
)


def test_observation_audit_microsecond_pages_on_timescaledb() -> None:
    uri = os.getenv("DATA_EXPLORER_TIMESCALE_URI")
    if not uri:
        pytest.skip("Set DATA_EXPLORER_TIMESCALE_URI for the isolated local acceptance database")
    url = make_url(uri)
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "pagination_acceptance":
        pytest.fail("Acceptance URI must point to local pagination_acceptance database")

    engine = create_engine(uri)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar_one_or_none()
        ensure_timescale_hypertables(engine)
        assert_observation_audit_pages(TimeSeriesRepository(engine=engine, auto_init=False))
    finally:
        engine.dispose()


def test_forecast_pages_on_timescaledb() -> None:
    uri = os.getenv("DATA_EXPLORER_TIMESCALE_URI")
    if not uri:
        pytest.skip("Set DATA_EXPLORER_TIMESCALE_URI for the isolated local acceptance database")
    url = make_url(uri)
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "pagination_acceptance":
        pytest.fail("Acceptance URI must point to local pagination_acceptance database")

    engine = create_engine(uri)
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar_one_or_none()
        ensure_timescale_hypertables(engine)
        repo = TimeSeriesRepository(engine=engine, auto_init=False)
        assert_forecast_pages_pin_microsecond_vintage(repo)
        assert_forecast_audit_pages_keep_complete_sort_key(repo)
    finally:
        engine.dispose()
