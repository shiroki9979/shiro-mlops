"""Opt-in power pagination acceptance against an isolated local TimescaleDB."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from shiro_mlops.core.database import ensure_timescale_hypertables
from shiro_mlops.data.repository import TimeSeriesRepository
from tests.unit.test_data_explorer_power import (
    assert_national_reader_pages,
    assert_regional_reader_pages,
    assert_unit_reader_pages,
)


def test_power_microsecond_and_composite_pages_on_timescaledb() -> None:
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
        assert_national_reader_pages(repo)
        assert_regional_reader_pages(repo)
        assert_unit_reader_pages(repo)
    finally:
        engine.dispose()
