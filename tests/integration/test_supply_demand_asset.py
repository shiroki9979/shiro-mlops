"""Integration tests for Taipower supply-demand snapshot materialization."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from dagster import build_asset_context, materialize

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_supply_demand import SupplyDemandParseError
from shiro_mlops.pipelines.assets import raw_taipower_supply_demand_snapshot

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_payload() -> dict:
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        return json.load(f)


def _mock_httpx_response(payload: dict | None = None, *, status_error: bool = False):
    response = MagicMock()
    if status_error:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )
    else:
        response.raise_for_status.return_value = None
        response.json.return_value = payload if payload is not None else _load_payload()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.get.return_value = response
    return client


def test_raw_taipower_supply_demand_snapshot_materializes_to_repository(
    test_repo: TimeSeriesRepository,
) -> None:
    """mock 台電回應後 materialize 應以觀測 slot 冪等 upsert 並可讀回。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    with (
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
        patch(
            "shiro_mlops.data.taipower_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        snapshot = raw_taipower_supply_demand_snapshot(context)

    assert snapshot.observed_at == observed_slot
    assert snapshot.curr_load_wan_kw == pytest.approx(3242.1)

    persisted = test_repo.fetch_supply_demand_snapshot(observed_slot)
    assert persisted is not None
    assert persisted.curr_util_rate_pct == pytest.approx(78.0)
    assert persisted.source_publish_time == datetime(2026, 9, 5, 17, 30)
    assert persisted.raw_payload["records"][0]["curr_load"] == "3242.1"

    revised = _load_payload()
    revised["records"][0]["curr_load"] = "3400.5"
    with (
        patch(
            "shiro_mlops.data.taipower_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(revised),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        raw_taipower_supply_demand_snapshot(context)

    updated = test_repo.fetch_supply_demand_snapshot(observed_slot)
    assert updated is not None
    assert updated.curr_load_wan_kw == pytest.approx(3400.5)
    with test_repo.engine.connect() as conn:
        count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_supply_demand_snapshot"
        ).scalar()
    assert count == 1


def test_materialize_supply_demand_asset_end_to_end(
    test_repo: TimeSeriesRepository,
    dagster_instance,
) -> None:
    """Dagster materialize 應完成 client → upsert 端到端路徑。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    with (
        patch(
            "shiro_mlops.data.taipower_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        result = materialize(
            [raw_taipower_supply_demand_snapshot],
            resources={"time_series_repo": test_repo},
            instance=dagster_instance,
        )

    assert result.success
    persisted = test_repo.fetch_supply_demand_snapshot(observed_slot)
    assert persisted is not None
    assert persisted.curr_load_wan_kw == pytest.approx(3242.1)


def test_supply_demand_http_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """HTTP 失敗時 asset 必須失敗且不得寫入快照。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    with (
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
        patch(
            "shiro_mlops.data.taipower_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(status_error=True),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            raw_taipower_supply_demand_snapshot(context)

    assert test_repo.fetch_supply_demand_snapshot(observed_slot) is None


def test_supply_demand_parse_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """核心欄位缺失時 asset 必須失敗且不得寫入快照。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    bad_payload = {"records": [{"curr_load": "3000"}]}

    with (
        build_asset_context(resources={"time_series_repo": test_repo}) as context,
        patch(
            "shiro_mlops.data.taipower_supply_demand.httpx.Client",
            return_value=_mock_httpx_response(bad_payload),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(SupplyDemandParseError, match="curr_util_rate"):
            raw_taipower_supply_demand_snapshot(context)

    assert test_repo.fetch_supply_demand_snapshot(observed_slot) is None
