"""Unit tests for regional supply-demand snapshot repository persistence."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.engine import Engine

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import parse_regional_supply_demand_csv
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from tests.helpers import regional_supply_demand_snapshots


def test_upsert_then_fetch_returns_the_regional_snapshots(
    test_repo: TimeSeriesRepository,
) -> None:
    """多區域快照應可依 (observed_at, region) 寫入並讀回萬瓩欄位與 raw payload。"""
    snapshots = regional_supply_demand_snapshots()
    assert test_repo.regional_supply_demand_store.upsert(snapshots) == 4

    fetched = test_repo.regional_supply_demand_store.fetch(datetime(2026, 9, 5, 17, 30))
    assert [item.region for item in fetched] == ["北部", "中部", "南部", "東部"]
    assert fetched[0].load_wan_kw == pytest.approx(1091.7)
    assert fetched[0].generation_wan_kw == pytest.approx(1155.4)
    assert fetched[0].source_time == datetime(2026, 9, 5, 17, 30)
    assert fetched[0].raw_payload["發電(萬瓩)"] == "1155.4"


def test_upsert_is_idempotent_on_region_and_slot(
    test_repo: TimeSeriesRepository,
) -> None:
    """相同區域與觀測 slot 重跑時應更新既有快照而非新增列。"""
    first = regional_supply_demand_snapshots(datetime(2026, 9, 5, 17, 30))
    test_repo.regional_supply_demand_store.upsert(first)

    revised_csv = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,1200.0,1100.0\n"
        "20260905T173000,中部,1088.7,977.5\n"
        "20260905T173000,南部,997.0,1146.3\n"
        "20260905T173000,東部,12.8,38.5\n"
    )
    revised = parse_regional_supply_demand_csv(
        revised_csv, observed_at=datetime(2026, 9, 5, 17, 30)
    )
    assert test_repo.regional_supply_demand_store.upsert(revised) == 4

    fetched = test_repo.regional_supply_demand_store.fetch(datetime(2026, 9, 5, 17, 30))
    north = next(item for item in fetched if item.region == "北部")
    assert north.load_wan_kw == pytest.approx(1100.0)
    assert north.generation_wan_kw == pytest.approx(1200.0)

    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_regional_supply_demand_snapshot"
        ).scalar()
    assert count == 4


def test_upsert_excludes_corrupted_rows(
    test_repo: TimeSeriesRepository,
) -> None:
    """含非約定格式錯誤列的 CSV 經解析後僅有效區域寫入資料庫，損壞列不寫入。"""
    corrupted_csv = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,corrupted,1091.7\n"  # 損壞列
        "20260905T173000,中部,1088.7,977.5\n"  # 有效列
        "20260905T173000,南投,997.0,1146.3\n"  # 未知區域列
        "20260905T173000,東部,12.8,38.5\n"  # 有效列
    )
    observed_at = datetime(2026, 9, 5, 17, 30)
    snapshots = parse_regional_supply_demand_csv(corrupted_csv, observed_at=observed_at)
    assert len(snapshots) == 2
    assert [item.region for item in snapshots] == ["中部", "東部"]

    assert test_repo.regional_supply_demand_store.upsert(snapshots) == 2

    fetched = test_repo.regional_supply_demand_store.fetch(observed_at)
    assert len(fetched) == 2
    assert [item.region for item in fetched] == ["中部", "東部"]

    with test_repo.engine.connect() as conn:
        total_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_regional_supply_demand_snapshot"
        ).scalar()
    assert total_count == 2


def test_standalone_taipower_regional_supply_demand_repository_lifecycle(
    sqlite_engine: Engine,
) -> None:
    """獨立 TaipowerRegionalSupplyDemandRepository 應可獨立初始化、驗證、冪等 upsert 與 fetch。"""
    repo = TaipowerRegionalSupplyDemandRepository(engine=sqlite_engine)
    snapshots = regional_supply_demand_snapshots()
    slot = datetime(2026, 9, 5, 17, 30)

    # 驗證空資料與首次寫入
    assert repo.upsert([]) == 0
    assert repo.upsert(snapshots) == 4

    # 驗證依北中南東領域順序讀回
    fetched = repo.fetch(slot)
    assert len(fetched) == 4
    assert [item.region for item in fetched] == ["北部", "中部", "南部", "東部"]
    assert fetched[0].load_wan_kw == pytest.approx(1091.7)

    # 驗證同一 slot 冪等更新
    revised_csv = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,1200.0,1150.0\n"
        "20260905T173000,中部,1088.7,977.5\n"
        "20260905T173000,南部,997.0,1146.3\n"
        "20260905T173000,東部,12.8,38.5\n"
    )
    revised = parse_regional_supply_demand_csv(revised_csv, observed_at=slot)
    assert repo.upsert(revised) == 4

    updated = repo.fetch(slot)
    north = next(item for item in updated if item.region == "北部")
    assert north.load_wan_kw == pytest.approx(1150.0)

    # 驗證非法 region 直接防禦拒絕
    invalid_snapshot = regional_supply_demand_snapshots(datetime(2026, 9, 5, 18, 0))[0]
    object.__setattr__(invalid_snapshot, "region", "未知區域")
    with pytest.raises(ValueError, match="region"):
        repo.upsert([invalid_snapshot])


def test_fetch_by_source_time_uses_half_open_window(
    test_repo: TimeSeriesRepository,
) -> None:
    """Hourly-load derivation reads snapshots by source time in [start, end), independently of observation slots."""
    for observed_at in (
        datetime(2026, 9, 5, 16, 50),
        datetime(2026, 9, 5, 17, 0),
        datetime(2026, 9, 5, 18, 0),
    ):
        csv_text = (
            "時間,區域,發電(萬瓩),用電(萬瓩)\n"
            f"{observed_at:%Y%m%dT%H%M%S},北部,1155.4,1091.7\n"
            f"{observed_at:%Y%m%dT%H%M%S},東部,12.8,38.5\n"
        )
        test_repo.regional_supply_demand_store.upsert(
            parse_regional_supply_demand_csv(csv_text, observed_at=observed_at)
        )

    fetched = test_repo.regional_supply_demand_store.fetch_by_source_time(
        start_time=datetime(2026, 9, 5, 17, 0),
        end_time=datetime(2026, 9, 5, 18, 0),
    )

    assert [(item.source_time, item.region) for item in fetched] == [
        (datetime(2026, 9, 5, 17, 0), "北部"),
        (datetime(2026, 9, 5, 17, 0), "東部"),
    ]


def test_fetch_by_source_time_rejects_rows_without_observed_at() -> None:
    """A missing observation slot signals corrupt data and cannot be replaced with the query start."""
    engine = MagicMock(spec=Engine)
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = [
        {
            "observed_at": None,
            "region": "北部",
            "source_time": datetime(2026, 9, 5, 9, 0),
            "generation_wan_kw": 1155.4,
            "load_wan_kw": 1091.7,
            "raw_payload": "{}",
        }
    ]
    repository = TaipowerRegionalSupplyDemandRepository(engine=engine, auto_init=False)

    with pytest.raises(ValueError, match="observed_at for region '北部' is NULL"):
        repository.fetch_by_source_time(
            start_time=datetime(2026, 9, 5, 17, 0), end_time=datetime(2026, 9, 5, 18, 0)
        )


def test_regional_snapshots_store_every_instant_as_aware_utc(
    test_repo: TimeSeriesRepository,
) -> None:
    """區域快照的觀測時刻與來源時刻皆存為帶 +00:00 的 UTC 字串。"""
    test_repo.regional_supply_demand_store.upsert(regional_supply_demand_snapshots())

    with test_repo.engine.connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT DISTINCT observed_at, source_time "
            "FROM raw_taipower_regional_supply_demand_snapshot"
        ).all()

    assert [tuple(row) for row in stored] == [
        ("2026-09-05 09:30:00+00:00", "2026-09-05 09:30:00+00:00")
    ]
