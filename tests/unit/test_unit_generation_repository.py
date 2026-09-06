"""Unit tests for unit-generation snapshot repository persistence."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import (
    TaipowerUnitGenerationRepository,
    TimeSeriesRepository,
)
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


def test_upsert_unit_generation_snapshots_excludes_corrupted_and_fake_identity_rows(
    test_repo: TimeSeriesRepository,
) -> None:
    """含缺失識別鍵與格式損壞列的 payload 經解析後僅有效列入庫，資料庫無任何 None/假識別資料。"""
    payload = {
        "DateTime": "2026-09-05T17:30:00",
        "aaData": [
            {
                "機組類型": None,
                "機組名稱": "Null型態機組",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "損壞機組",
                "裝置容量(MW)": "corrupted",
                "淨發電量(MW)": "50.0",
            },
            {
                "機組類型": "燃氣",
                "機組名稱": "有效機組A",
                "裝置容量(MW)": "100.0",
                "淨發電量(MW)": "50.0",
                "淨發電量/裝置容量比(%)": "50.0%",
                "備註": "正常運轉",
            },
        ],
    }

    observed_at = datetime(2026, 9, 5, 17, 30)
    snapshots = parse_unit_generation_payload(payload, observed_at=observed_at)
    assert len(snapshots) == 1
    assert snapshots[0].unit_name == "有效機組A"

    assert test_repo.upsert_unit_generation_snapshots(snapshots) == 1

    fetched = test_repo.fetch_unit_generation_snapshots(observed_at)
    assert len(fetched) == 1
    assert fetched[0].unit_name == "有效機組A"

    with test_repo.engine.connect() as conn:
        fake_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot "
            "WHERE unit_type = 'None' OR unit_name = 'None' OR unit_type = '' OR unit_name = ''"
        ).scalar()
        total_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot"
        ).scalar()

    assert fake_count == 0
    assert total_count == 1


def test_standalone_taipower_unit_generation_repository_lifecycle(
    sqlite_engine: Engine,
) -> None:
    """獨立 TaipowerUnitGenerationRepository 應可獨立初始化、驗證、冪等 upsert 與 fetch。"""
    repo = TaipowerUnitGenerationRepository(engine=sqlite_engine)
    snapshots = _sample_snapshots()
    slot = datetime(2026, 9, 5, 17, 30)

    # 驗證空資料與首次寫入
    assert repo.upsert([]) == 0
    assert repo.upsert(snapshots) == 4

    # 驗證讀回與排序
    fetched = repo.fetch(slot)
    assert len(fetched) == 4
    assert (fetched[0].unit_type, fetched[0].unit_name) <= (
        fetched[1].unit_type,
        fetched[1].unit_name,
    )

    # 驗證同一機組與 slot 冪等更新
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    payload["aaData"][0]["淨發電量(MW)"] = "750.0"
    revised = parse_unit_generation_payload(payload, observed_at=slot)
    assert repo.upsert(revised) == 4

    updated = repo.fetch(slot)
    target = next(item for item in updated if item.unit_name == "大潭CC#1")
    assert target.net_generation_mw == pytest.approx(750.0)

    # 驗證非法機組識別（空白、假標識）直接防禦拒絕
    invalid_snapshot = snapshots[0]
    object.__setattr__(invalid_snapshot, "unit_name", "")
    with pytest.raises(ValueError, match="unit_name"):
        repo.upsert([invalid_snapshot])

    object.__setattr__(invalid_snapshot, "unit_name", "None")
    with pytest.raises(ValueError, match="unit_name"):
        repo.upsert([invalid_snapshot])
