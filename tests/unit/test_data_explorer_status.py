"""Dataset status dimensions stay independent and explainable."""

from datetime import datetime

from shiro_mlops.service.data_explorer.status import (
    DatasetFreshness,
    derive_overall,
    evaluate_freshness,
)


def test_freshness_uses_dataset_cadence_and_two_missed_cycles() -> None:
    """超過兩個預期週期未更新才標 warning；ingestion 與 source age 分開計算。"""
    as_of = datetime(2026, 8, 20, 14, 0)
    source_at = datetime(2026, 8, 20, 13, 50)
    ingested_at = datetime(2026, 8, 20, 13, 55)

    fresh = evaluate_freshness(
        cadence_seconds=600,
        as_of=as_of,
        latest_source_at=source_at,
        latest_ingested_at=ingested_at,
    )
    assert fresh.state == "fresh"
    assert fresh.source_age_seconds == 600
    assert fresh.ingestion_age_seconds == 300

    stale = evaluate_freshness(
        cadence_seconds=3600,
        as_of=as_of,
        latest_source_at=datetime(2026, 8, 20, 11, 0),
        latest_ingested_at=datetime(2026, 8, 20, 11, 5),
    )
    assert stale.state == "warning"
    assert stale.source_age_seconds == 3 * 3600


def test_freshness_unknown_when_timestamps_missing() -> None:
    """沒有來源或入庫時間時 freshness 必須是 unknown。"""
    result = evaluate_freshness(
        cadence_seconds=3600,
        as_of=datetime(2026, 8, 20, 14, 0),
        latest_source_at=None,
        latest_ingested_at=None,
    )
    assert result == DatasetFreshness("unknown", None, None)


def test_overall_severity_maps_availability_and_warnings() -> None:
    """資料庫不可用為 critical；過期、不完整或空資料為 warning。"""
    assert derive_overall("unavailable", "unknown", "unknown") == "critical"
    assert derive_overall("empty", "unknown", "unknown") == "warning"
    assert derive_overall("available", "warning", "complete") == "warning"
    assert derive_overall("available", "fresh", "incomplete") == "warning"
    assert derive_overall("available", "fresh", "complete") == "healthy"
