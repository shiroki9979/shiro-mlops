"""Unit tests for unit-generation snapshot repository persistence."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_unit_generation import parse_unit_generation_payload
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)
from tests.helpers import unit_generation_batch

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_upsert_then_fetch_returns_the_unit_generation_batch(
    test_repo: TimeSeriesRepository,
) -> None:
    """一次成功回應應以 batch 寫入，讀回同一份完整回應與各機組快照。"""
    batch = unit_generation_batch()
    assert test_repo.unit_generation_store.upsert(batch) == 4

    stored = test_repo.unit_generation_store.fetch(datetime(2026, 9, 5, 17, 30))
    assert stored is not None
    assert stored.observed_at == datetime(2026, 9, 5, 17, 30)
    assert stored.raw_payload["DateTime"] == "2026-09-05T17:30:00"
    assert len(stored.raw_payload["aaData"]) == 4
    fetched = stored.snapshots
    assert len(fetched) == 4
    first = next(item for item in fetched if item.unit_name == "大潭CC#1")
    assert first.net_generation_mw == pytest.approx(670.4)
    assert first.capacity_ratio_pct == pytest.approx(90.265)
    assert first.source_time == datetime(2026, 9, 5, 17, 30)
    offline = next(item for item in fetched if item.unit_name == "大潭CC#3")
    assert offline.net_generation_mw == pytest.approx(0.0)
    assert offline.remark == "歲修"


def test_upsert_is_idempotent(
    test_repo: TimeSeriesRepository,
) -> None:
    """相同機組識別與觀測 slot 重跑時應更新既有快照而非新增列。"""
    test_repo.unit_generation_store.upsert(unit_generation_batch(datetime(2026, 9, 5, 17, 30)))

    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        payload = json.load(f)
    payload["aaData"][0]["淨發電量(MW)"] = "700.0"
    payload["aaData"][0]["淨發電量/裝置容量比(%)"] = "94.250%"
    revised = parse_unit_generation_payload(payload, observed_at=datetime(2026, 9, 5, 17, 30))
    assert test_repo.unit_generation_store.upsert(revised) == 4

    stored = test_repo.unit_generation_store.fetch(datetime(2026, 9, 5, 17, 30))
    assert stored is not None
    assert stored.raw_payload["aaData"][0]["淨發電量(MW)"] == "700.0"
    updated = next(item for item in stored.snapshots if item.unit_name == "大潭CC#1")
    assert updated.net_generation_mw == pytest.approx(700.0)
    assert updated.capacity_ratio_pct == pytest.approx(94.25)

    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot"
        ).scalar()
    assert count == 4


def test_upsert_excludes_corrupted_and_fake_identity_rows(
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
    batch = parse_unit_generation_payload(payload, observed_at=observed_at)
    assert [snapshot.unit_name for snapshot in batch.snapshots] == ["有效機組A"]

    assert test_repo.unit_generation_store.upsert(batch) == 1

    stored = test_repo.unit_generation_store.fetch(observed_at)
    assert stored is not None
    assert [snapshot.unit_name for snapshot in stored.snapshots] == ["有效機組A"]
    assert len(stored.raw_payload["aaData"]) == 4

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
    batch = unit_generation_batch()
    slot = datetime(2026, 9, 5, 17, 30)

    assert repo.fetch(slot) is None
    assert repo.upsert(batch) == 4

    # 驗證讀回與排序
    stored = repo.fetch(slot)
    assert stored is not None
    fetched = stored.snapshots
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
    assert updated is not None
    target = next(item for item in updated.snapshots if item.unit_name == "大潭CC#1")
    assert target.net_generation_mw == pytest.approx(750.0)

    # 驗證非法機組識別（空白、假標識）直接防禦拒絕
    invalid_snapshot = batch.snapshots[0]
    object.__setattr__(invalid_snapshot, "unit_name", "")
    with pytest.raises(ValueError, match="unit_name"):
        repo.upsert(batch)

    object.__setattr__(invalid_snapshot, "unit_name", "None")
    with pytest.raises(ValueError, match="unit_name"):
        repo.upsert(batch)


def test_unit_generation_snapshots_store_every_instant_as_aware_utc(
    test_repo: TimeSeriesRepository,
) -> None:
    """機組快照的觀測時刻與來源時刻皆存為帶 +00:00 的 UTC 字串。"""
    test_repo.unit_generation_store.upsert(unit_generation_batch())

    with test_repo.engine.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT DISTINCT observed_at, source_time FROM raw_taipower_unit_generation_snapshot"
        ).all()

    assert [tuple(row) for row in stored] == [
        ("2026-09-05 09:30:00+00:00", "2026-09-05 09:30:00+00:00")
    ]


def _unit_generation_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "observed_at": "2026-09-05 09:30:00+00:00",
        "unit_type": "燃氣",
        "unit_name": "大潭CC#1",
        "source_time": "2026-09-05 09:30:00+00:00",
        "capacity_mw": 742.7,
        "net_generation_mw": 670.4,
        "capacity_ratio_pct": 90.265,
        "remark": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("column", ["observed_at", "source_time"])
def test_fetch_rejects_rows_without_an_instant(column: str) -> None:
    """NOT NULL 的觀測或來源時刻讀到 NULL 代表儲存毀損，不可拿查詢條件或觀測時刻代填。"""
    engine = MagicMock(spec=Engine)
    connection = engine.connect.return_value.__enter__.return_value
    result = connection.execute.return_value.mappings.return_value
    result.first.return_value = {
        "observed_at": "2026-09-05 09:30:00+00:00",
        "raw_payload": "{}",
    }
    result.all.return_value = [_unit_generation_row(**{column: None})]
    repository = TaipowerUnitGenerationRepository(engine=engine, auto_init=False)

    with pytest.raises(ValueError, match=f"{column} is NULL"):
        repository.fetch(datetime(2026, 9, 5, 17, 30))


def test_fetch_rejects_a_header_without_unit_rows(test_repo: TimeSeriesRepository) -> None:
    """header 與機組列在同一交易寫入；只有 header 代表儲存毀損，不可讀成空 batch。"""
    with test_repo.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO raw_taipower_unit_generation_batch (observed_at, raw_payload) "
            "VALUES ('2026-09-05 09:30:00+00:00', '{}')"
        )

    with pytest.raises(ValueError, match="at least one snapshot"):
        test_repo.unit_generation_store.fetch(datetime(2026, 9, 5, 17, 30))
