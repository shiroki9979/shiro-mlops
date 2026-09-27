"""Observation audit pages retain raw timestamp precision."""

from datetime import datetime

from shiro_mlops.data.cwa_client import CWAObservationBatch
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.weather import ObservationAuditReader


def assert_observation_audit_pages(repo: TimeSeriesRepository) -> None:
    """The expected order is fixed by the fixture, independent of cursor helpers."""
    second = datetime(2026, 9, 27, 12, 0, 0)
    for microsecond, station_id in ((100, "old"), (600, "middle"), (900, "new")):
        repo.upsert_cwa_observation_batch(
            CWAObservationBatch(
                fetched_at=second.replace(microsecond=microsecond),
                status="incomplete",
                missing_station_ids=(station_id,),
                raw_payload={"private": station_id},
                observations=(),
            )
        )

    reader = ObservationAuditReader(repo.engine)
    params = {
        "start": second.replace(microsecond=100).isoformat(timespec="microseconds") + "+08:00",
        "end": second.replace(microsecond=900).isoformat(timespec="microseconds") + "+08:00",
        "status": "incomplete",
        "limit": 1,
    }
    seen = []
    cursor = None
    for expected_id, expected_more in (("new", True), ("middle", True), ("old", False)):
        page = reader.list({**params, **({"cursor": cursor} if cursor else {})})
        assert len(page.items) == 1, (cursor, seen)
        assert page.items[0]["missing_station_ids"] == [expected_id]
        assert page.items[0]["fetched_at"] == "2026-09-27T12:00:00+08:00"
        assert "raw_payload" not in page.items[0]
        assert page.has_more is expected_more
        assert bool(page.next_cursor) is expected_more
        seen.append(expected_id)
        cursor = page.next_cursor
    assert seen == ["new", "middle", "old"]
    assert reader.list({**params, "missing_station_id": "absent"}).items == []


def test_observation_audit_pages_preserve_microseconds(test_repo: TimeSeriesRepository) -> None:
    assert_observation_audit_pages(test_repo)
