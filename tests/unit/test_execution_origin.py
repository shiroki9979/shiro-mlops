"""Resolving a Dagster run's execution origin and as_of from its tags and creation time."""

from datetime import UTC, datetime

import pytest
from dagster import AssetExecutionContext, asset, build_schedule_context, materialize

from shiro_mlops.pipelines.execution_origin import (
    REEXECUTION_TAGS,
    RUN_KEY_TAG,
    SCHEDULE_NAME_TAG,
    SCHEDULED_TICK_TAG,
    ExecutionOrigin,
    NoScheduledTickError,
    WithoutTick,
    resolve_as_of,
    run_as_of,
    tick_run_request,
)
from tests.helpers import REEXECUTION

# run 建立於 2026-11-20 03:40:12 UTC，即台灣 11:40:12，晚於 10:25 的 tick。
CREATED_AT = datetime(2026, 11, 20, 3, 40, 12, tzinfo=UTC)
CREATED_AT_IN_TAIWAN = datetime(2026, 11, 20, 11, 40, 12)
TICK_IN_TAIWAN = datetime(2026, 11, 20, 10, 25)
# 排程 daemon 發起的 run：排程評估產生的兩個標籤，加上只有 daemon 會加的 run key。
SCHEDULED = {
    SCHEDULE_NAME_TAG: "forecast_track_record_schedule",
    SCHEDULED_TICK_TAG: "2026-11-20T10:25:00",
    RUN_KEY_TAG: "2026-11-20T10:25:00",
}
# Dagster UI 的 tick 預覽按下 Launch 時，只把排程評估產生的標籤複製到手動 run 上。
LAUNCHED_FROM_TICK_PREVIEW = {
    SCHEDULE_NAME_TAG: "forecast_track_record_schedule",
    SCHEDULED_TICK_TAG: "2026-11-20T10:25:00",
}

RUNS_WITHOUT_A_SCHEDULED_TICK = [
    pytest.param({}, ExecutionOrigin.MANUAL, id="manual"),
    pytest.param(
        {SCHEDULED_TICK_TAG: "2026-11-20T10:25:00"},
        ExecutionOrigin.MANUAL,
        id="tick-tag-filled-in-by-hand",
    ),
    pytest.param(
        LAUNCHED_FROM_TICK_PREVIEW,
        ExecutionOrigin.MANUAL,
        id="launched-from-the-tick-preview",
    ),
    pytest.param(
        {**LAUNCHED_FROM_TICK_PREVIEW, RUN_KEY_TAG: "2026-11-20T09:25:00"},
        ExecutionOrigin.MANUAL,
        id="run-key-of-another-tick",
    ),
    pytest.param(
        {**LAUNCHED_FROM_TICK_PREVIEW, RUN_KEY_TAG: ""},
        ExecutionOrigin.MANUAL,
        id="empty-run-key",
    ),
    pytest.param(
        {**SCHEDULED, **REEXECUTION},
        ExecutionOrigin.REEXECUTION,
        id="re-execution-of-a-scheduled-run",
    ),
    pytest.param(
        {**SCHEDULED, REEXECUTION_TAGS[0]: "tick-run"},
        ExecutionOrigin.REEXECUTION,
        id="parent-tag-only",
    ),
    pytest.param(
        {**SCHEDULED, REEXECUTION_TAGS[1]: "tick-run"},
        ExecutionOrigin.REEXECUTION,
        id="root-tag-only",
    ),
    pytest.param(
        REEXECUTION,
        ExecutionOrigin.REEXECUTION,
        id="re-execution-of-a-manual-run",
    ),
]


def test_a_scheduled_tick_is_the_as_of_whatever_the_asset_does_without_one() -> None:
    for without_tick in WithoutTick:
        assert resolve_as_of(SCHEDULED, CREATED_AT, without_tick=without_tick) == TICK_IN_TAIWAN


@pytest.mark.parametrize(
    "tick",
    [
        pytest.param("2026-11-20T10:25:00", id="naive-taiwan-local"),
        pytest.param("2026-11-20T02:25:00+00:00", id="aware-utc"),
        pytest.param("2026-11-20T10:25:00+08:00", id="aware-taiwan"),
    ],
)
def test_a_scheduled_tick_becomes_naive_taiwan_local_time(tick: str) -> None:
    tags = {**SCHEDULED, SCHEDULED_TICK_TAG: tick, RUN_KEY_TAG: tick}

    as_of = resolve_as_of(tags, CREATED_AT, without_tick=WithoutTick.REFUSE)

    assert as_of == TICK_IN_TAIWAN
    assert as_of.tzinfo is None


@pytest.mark.parametrize(("tags", "origin"), RUNS_WITHOUT_A_SCHEDULED_TICK)
def test_a_run_without_a_scheduled_tick_falls_back_to_its_creation_time_in_taiwan(
    tags: dict, origin: ExecutionOrigin
) -> None:
    as_of = resolve_as_of(tags, CREATED_AT, without_tick=WithoutTick.FALL_BACK_TO_NOW)

    assert as_of == CREATED_AT_IN_TAIWAN


@pytest.mark.parametrize(("tags", "origin"), RUNS_WITHOUT_A_SCHEDULED_TICK)
def test_a_run_without_a_scheduled_tick_is_refused_naming_its_origin(
    tags: dict, origin: ExecutionOrigin
) -> None:
    with pytest.raises(NoScheduledTickError) as refused:
        resolve_as_of(tags, CREATED_AT, without_tick=WithoutTick.REFUSE)

    assert refused.value.origin == origin
    expected_reason = "re-execut" if origin is ExecutionOrigin.REEXECUTION else "scheduled tick"
    assert expected_reason in str(refused.value)


def test_a_schedule_tick_requests_a_run_keyed_and_tagged_with_its_taiwan_local_time() -> None:
    context = build_schedule_context(
        scheduled_execution_time=datetime(2026, 11, 20, 2, 25, tzinfo=UTC)
    )

    request = tick_run_request(context)

    assert request.run_key == "2026-11-20T10:25:00"
    assert request.tags == {SCHEDULED_TICK_TAG: "2026-11-20T10:25:00"}
    assert not request.run_config


def test_a_schedule_evaluated_without_a_tick_requests_a_run_with_neither_key_nor_tick() -> None:
    """Dagster raises on reading a tick that was never set; the helper must not."""
    request = tick_run_request(build_schedule_context())

    assert request.run_key is None
    assert SCHEDULED_TICK_TAG not in request.tags


@asset
def _issue_like(context: AssetExecutionContext) -> str:
    return run_as_of(context, without_tick=WithoutTick.REFUSE).isoformat()


def _refusal(result) -> str:
    [failure] = [event for event in result.all_events if event.is_step_failure]
    return failure.step_failure_data.user_failure_data.description


def test_a_refusing_asset_in_a_scheduled_run_gets_the_tick(dagster_instance) -> None:
    result = materialize([_issue_like], tags=SCHEDULED, instance=dagster_instance)

    assert result.output_for_node("_issue_like") == "2026-11-20T10:25:00"


@pytest.mark.parametrize(
    ("tags", "reason"),
    [
        pytest.param({}, "scheduled tick", id="manual"),
        pytest.param(LAUNCHED_FROM_TICK_PREVIEW, "scheduled tick", id="tick-preview-launch"),
        pytest.param(
            {**SCHEDULED, **REEXECUTION},
            "re-execut",
            id="re-execution",
        ),
    ],
)
def test_a_refusing_asset_fails_the_run_saying_why_it_has_no_tick(
    dagster_instance, tags: dict, reason: str
) -> None:
    result = materialize([_issue_like], tags=tags, instance=dagster_instance, raise_on_error=False)

    assert not result.success
    assert reason in _refusal(result)
