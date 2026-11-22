"""Data Explorer missing-slot HTTP scenarios shared across database dialects."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from shiro_mlops.core.config import settings
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.api import app
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.query import TimeWindow
from tests.helpers import regional_supply_demand_snapshots, rfc3339


@contextmanager
def explorer_http_client(repo: TimeSeriesRepository) -> Iterator[TestClient]:
    """Serve the Data Explorer routes from the given repository on either dialect."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "DATA_EXPLORER_ENABLED", True)
        patch.setattr("shiro_mlops.service.api.repository_store", repo)
        yield TestClient(app)


@contextmanager
def _regional_rows_in(repo: TimeSeriesRepository, window: TimeWindow, rows: list) -> Iterator[None]:
    repo.upsert_regional_supply_demand_snapshots(rows)
    try:
        yield
    finally:
        clauses, params = ExplorerDb(repo.engine).time_window("observed_at", window)
        with repo.engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM raw_taipower_regional_supply_demand_snapshot "
                    f"WHERE {' AND '.join(clauses)}"
                ),
                params,
            )


def assert_regional_gaps_list_zero_region_slots_on_every_page(
    repo: TimeSeriesRepository,
) -> None:
    """A slot with no region rows is a gap, and every page reports the same window gaps."""
    complete_old, empty, partial, complete_new = (
        datetime(2026, 9, 6, 8, 0) + timedelta(minutes=10 * index) for index in range(4)
    )
    rows = (
        regional_supply_demand_snapshots(complete_old)
        + regional_supply_demand_snapshots(partial)[:1]
        + regional_supply_demand_snapshots(complete_new)
    )
    params = {"start": rfc3339(complete_old), "end": rfc3339(complete_new), "limit": 4}

    with (
        _regional_rows_in(repo, TimeWindow(complete_old, complete_new), rows),
        explorer_http_client(repo) as client,
    ):
        first = client.get("/data/power/regional", params=params)
        second = client.get(
            "/data/power/regional", params={**params, "cursor": first.json()["next_cursor"]}
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["has_more"] is True
    assert first.json()["missing_slots"] == [rfc3339(empty), rfc3339(partial)]
    assert second.json()["missing_slots"] == first.json()["missing_slots"]
