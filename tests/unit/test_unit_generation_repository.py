"""Unit tests for unit-generation snapshot repository persistence."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_unit_generation import parse_unit_generation_payload

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _sample_snapshots(observed_at: datetime | None = None):
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    return parse_unit_generation_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def test_upsert_unit_generation_snapshots_insert_and_fetch(
    test_repo: TimeSeriesRepository,
) -> None:
    """多機組快照應可依 (observed_at, unit_type, unit_name) 寫入並讀回。"""
    snapshots = _sample_snapshots()
    assert test_repo.upsert_unit_generation_snapshots(snapshots) == 4

    fetched = test_repo.fetch_unit_generation_snapshots(datetime(2026, 9, 5, 17, 30))
    assert len(fetched) == 4
    first = next(item for item in fetched if item.unit_name == "大潭CC#1")
    assert first.net_generation_mw == pytest.approx(670.4)
    assert first.capacity_ratio_pct == pytest.approx(90.265)
    assert first.source_time == datetime(2026, 9, 5, 17, 30)
    assert first.raw_payload["DateTime"] == "2026-09-05T17:30:00"
    assert len(first.raw_payload["aaData"]) == 4
    offline = next(item for item in fetched if item.unit_name == "大潭CC#3")
    assert offline.net_generation_mw == pytest.approx(0.0)
    assert offline.remark == "歲修"


def test_upsert_unit_generation_snapshots_is_idempotent(
    test_repo: TimeSeriesRepository,
) -> None:
    """相同機組識別與觀測 slot 重跑時應更新既有快照而非新增列。"""
    first = _sample_snapshots(datetime(2026, 9, 5, 17, 30))
    test_repo.upsert_unit_generation_snapshots(first)

    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    payload["aaData"][0]["淨發電量(MW)"] = "700.0"
    payload["aaData"][0]["淨發電量/裝置容量比(%)"] = "94.250%"
    revised = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
    assert test_repo.upsert_unit_generation_snapshots(revised) == 4

    fetched = test_repo.fetch_unit_generation_snapshots(datetime(2026, 9, 5, 17, 30))
    updated = next(item for item in fetched if item.unit_name == "大潭CC#1")
    assert updated.net_generation_mw == pytest.approx(700.0)
    assert updated.capacity_ratio_pct == pytest.approx(94.25)

    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot"
        ).scalar()
    assert count == 4
