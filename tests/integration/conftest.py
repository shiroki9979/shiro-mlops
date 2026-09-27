"""Shared fixtures for opt-in integration acceptance."""

import os
from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from shiro_mlops.core.database import ensure_timescale_hypertables


@pytest.fixture
def data_explorer_timescaledb_engine(
    request: pytest.FixtureRequest,
) -> Generator[Engine, None, None]:
    uri = os.getenv("DATA_EXPLORER_TIMESCALE_URI")
    if not uri:
        pytest.skip("Set DATA_EXPLORER_TIMESCALE_URI for the isolated local acceptance database")
    url = make_url(uri)
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "pagination_acceptance":
        pytest.fail("Acceptance URI must point to local pagination_acceptance database")

    timezone = getattr(request, "param", "UTC")
    engine = create_engine(uri, connect_args={"options": f"-c timezone={timezone}"})
    try:
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            ).scalar_one_or_none()
        ensure_timescale_hypertables(engine)
        yield engine
    finally:
        engine.dispose()
