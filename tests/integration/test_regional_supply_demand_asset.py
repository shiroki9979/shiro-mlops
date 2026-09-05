"""Integration tests for Taipower regional supply-demand snapshot materialization."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from dagster import build_asset_context, materialize

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import RegionalSupplyDemandParseError
from shiro_mlops.pipelines.assets import raw_taipower_regional_supply_demand_snapshot

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_csv() -> str:
    return (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(encoding="utf-8")


def _mock_httpx_response(text: str | None = None, *, status_error: bool = False):
    response = MagicMock()
    if status_error:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    else:
        response.raise_for_status.return_value = None
        response.text = text if text is not None else _load_csv()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.get.return_value = response
    return client


def test_raw_regional_snapshot_materializes_multi_region_idempotently(
    test_repo: TimeSeriesRepository,
) -> None:
    """mock 區域 CSV 後 materialize 應寫入四區，重跑同 slot 仍維持四列。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with (
        patch(
            "shiro_mlops.data.taipower_regional_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        snapshots = raw_taipower_regional_supply_demand_snapshot(context)

    assert len(snapshots) == 4
    assert [item.region for item in snapshots] == ["北部", "中部", "南部", "東部"]

    revised = (
        "時間,區域,發電(萬瓩),用電(萬瓩)\n"
        "20260905T173000,北部,1200.0,1100.0\n"
        "20260905T173000,中部,1088.7,977.5\n"
        "20260905T173000,南部,997.0,1146.3\n"
        "20260905T173000,東部,12.8,38.5\n"
    )
    with (
        patch(
            "shiro_mlops.data.taipower_regional_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(revised),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        raw_taipower_regional_supply_demand_snapshot(context)

    persisted = test_repo.fetch_regional_supply_demand_snapshots(observed_slot)
    assert len(persisted) == 4
    assert persisted[0].load_wan_kw == pytest.approx(1100.0)


def test_materialize_regional_asset_end_to_end(
    test_repo: TimeSeriesRepository,
    dagster_instance,
) -> None:
    """Dagster materialize 應完成 regional client → upsert 端到端路徑。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    with (
        patch(
            "shiro_mlops.data.taipower_regional_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        result = materialize(
            [raw_taipower_regional_supply_demand_snapshot],
            resources={"time_series_repo": test_repo},
            instance=dagster_instance,
        )

    assert result.success
    persisted = test_repo.fetch_regional_supply_demand_snapshots(observed_slot)
    assert len(persisted) == 4
    assert persisted[0].load_wan_kw == pytest.approx(1091.7)


def test_regional_http_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """HTTP 失敗時 asset 必須失敗且不得寫入區域快照。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with (
        patch(
            "shiro_mlops.data.taipower_regional_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(status_error=True),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            raw_taipower_regional_supply_demand_snapshot(context)

    assert test_repo.fetch_regional_supply_demand_snapshots(observed_slot) == []


def test_regional_parse_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """無有效區域列時 asset 必須失敗且不得寫入。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})
    bad_csv = "時間,區域,發電(萬瓩),用電(萬瓩)\n,,,\n"

    with (
        patch(
            "shiro_mlops.data.taipower_regional_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(bad_csv),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(RegionalSupplyDemandParseError, match="No valid regional rows"):
            raw_taipower_regional_supply_demand_snapshot(context)

    assert test_repo.fetch_regional_supply_demand_snapshots(observed_slot) == []
