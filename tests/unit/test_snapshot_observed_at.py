"""Unit tests for realtime snapshot observation-slot resolution."""

from datetime import datetime

from shiro_mlops.data.taipower_supply_demand import resolve_snapshot_observed_at


def test_resolve_snapshot_observed_at_uses_schedule_tick_iso() -> None:
    """排程 tick 的 ISO 字串應解析為觀測 slot（已對齊 10 分鐘）。"""
    assert resolve_snapshot_observed_at("2026-09-05T17:30:00") == datetime(2026, 9, 5, 17, 30)


def test_resolve_snapshot_observed_at_floors_off_slot_tick() -> None:
    """非整點 tick 應向下取整至 10 分鐘 slot。"""
    assert resolve_snapshot_observed_at("2026-09-05T17:37:42") == datetime(2026, 9, 5, 17, 30)


def test_resolve_snapshot_observed_at_falls_back_to_manual(monkeypatch) -> None:
    """未提供 tick 時應回退手動 materialize 的取整邏輯。"""
    monkeypatch.setattr(
        "shiro_mlops.data.taipower_supply_demand.resolve_manual_observed_at",
        lambda: datetime(2026, 9, 5, 18, 10),
    )
    assert resolve_snapshot_observed_at(None) == datetime(2026, 9, 5, 18, 10)
