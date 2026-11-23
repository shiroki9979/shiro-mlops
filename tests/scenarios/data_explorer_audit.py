"""Observation audit pagination scenario shared across database dialects."""

from datetime import datetime

from shiro_mlops.data.cwa_client import CWAObservationBatch
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.datasets import CWA_OBSERVATION_AUDITS
from tests.helpers import DatasetLister


def assert_observation_audit_pages(repo: TimeSeriesRepository) -> None:
    """The expected order is fixed by the fixture, independent of cursor helpers."""
    second = datetime(2026, 9, 27, 12, 0, 0)
    for microsecond, station_id in ((100, "old"), (600, "middle"), (900, "new")):
        repo.cwa_weather_store.upsert_cwa_observation_batch(
            CWAObservationBatch(
                fetched_at=second.replace(microsecond=microsecond),
                status="incomplete",
                missing_station_ids=(station_id,),
                raw_payload={"private": station_id},
                observations=(),
            )
        )
    reader = DatasetLister(repo.engine, CWA_OBSERVATION_AUDITS)
    params = {
        "start": "2026-09-27T12:00:00.000100+08:00",
        "end": "2026-09-27T12:00:00.000900+08:00",
        "status": "incomplete",
        "limit": 1,
    }

    first = reader.list(params)
    second_page = reader.list({**params, "cursor": first.next_cursor})
    third_page = reader.list({**params, "cursor": second_page.next_cursor})
    absent = reader.list({**params, "missing_station_id": "absent"})

    pages = (first, second_page, third_page)
    assert [page.items[0]["missing_station_ids"] for page in pages] == [
        ["new"],
        ["middle"],
        ["old"],
    ]
    assert all(len(page.items) == 1 for page in pages)
    assert all(page.items[0]["fetched_at"] == "2026-09-27T12:00:00+08:00" for page in pages)
    assert all("raw_payload" not in page.items[0] for page in pages)
    assert [page.has_more for page in pages] == [True, True, False]
    assert [bool(page.next_cursor) for page in pages] == [True, True, False]
    assert absent.items == []
