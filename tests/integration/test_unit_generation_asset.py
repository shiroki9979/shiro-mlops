"""Integration tests for Taipower unit-generation snapshot materialization."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from dagster import build_asset_context, materialize

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_unit_generation import UnitGenerationParseError
from shiro_mlops.pipelines.assets import raw_taipower_unit_generation_snapshot

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_payload() -> dict:
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
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
        body = json.dumps(
            payload if payload is not None else _load_payload(),
            ensure_ascii=False,
        ).encode("utf-8")
        response.raise_for_status.return_value = None
        response.content = body
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = None
    client.get.return_value = response
    return client


def test_raw_unit_generation_snapshot_materializes_multi_unit_idempotently(
    test_repo: TimeSeriesRepository,
) -> None:
    """mock 機組 JSON 後 materialize 應寫入多機組，重跑同 slot 仍維持列數。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with (
        patch(
            "shiro_mlops.data.taipower_unit_generation.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        snapshots = raw_taipower_unit_generation_snapshot(context)

    assert len(snapshots) == 4
    offline = next(item for item in snapshots if item.unit_name == "大潭CC#3")
    assert offline.net_generation_mw == pytest.approx(0.0)
    assert offline.remark == "歲修"

    revised = _load_payload()
    revised["aaData"][0]["淨發電量(MW)"] = "680.0"
    with (
        patch(
            "shiro_mlops.data.taipower_unit_generation.httpx.Client",
            return_value=_mock_httpx_response(revised),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        raw_taipower_unit_generation_snapshot(context)

    persisted = test_repo.fetch_unit_generation_snapshots(observed_slot)
    assert len(persisted) == 4
    updated = next(item for item in persisted if item.unit_name == "大潭CC#1")
    assert updated.net_generation_mw == pytest.approx(680.0)
    assert updated.raw_payload == revised
    assert len(updated.raw_payload["aaData"]) == 4


def test_materialize_unit_generation_asset_end_to_end(
    test_repo: TimeSeriesRepository,
    dagster_instance,
) -> None:
    """Dagster materialize 應完成 unit client → upsert 端到端路徑。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    with (
        patch(
            "shiro_mlops.data.taipower_unit_generation.httpx.Client",
            return_value=_mock_httpx_response(),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        result = materialize(
            [raw_taipower_unit_generation_snapshot],
            resources={"time_series_repo": test_repo},
            instance=dagster_instance,
        )

    assert result.success
    persisted = test_repo.fetch_unit_generation_snapshots(observed_slot)
    assert len(persisted) == 4


def test_unit_generation_http_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """HTTP 失敗時 asset 必須失敗且不得寫入機組快照。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})

    with (
        patch(
            "shiro_mlops.data.taipower_unit_generation.httpx.Client",
            return_value=_mock_httpx_response(status_error=True),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            raw_taipower_unit_generation_snapshot(context)

    assert test_repo.fetch_unit_generation_snapshots(observed_slot) == []


def test_unit_generation_parse_failure_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """無有效機組列時 asset 必須失敗且不得寫入。"""
    observed_slot = datetime(2026, 9, 5, 17, 30)
    context = build_asset_context(resources={"time_series_repo": test_repo})
    bad_payload = {"DateTime": "2026-09-05T17:30:00", "aaData": []}

    with (
        patch(
            "shiro_mlops.data.taipower_unit_generation.httpx.Client",
            return_value=_mock_httpx_response(bad_payload),
        ),
        patch(
            "shiro_mlops.pipelines.assets.resolve_snapshot_observed_at",
            return_value=observed_slot,
        ),
    ):
        with pytest.raises(UnitGenerationParseError, match="No valid unit rows"):
            raw_taipower_unit_generation_snapshot(context)

    assert test_repo.fetch_unit_generation_snapshots(observed_slot) == []
