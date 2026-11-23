"""Resolving a Dagster run's execution origin and as_of from its tags and creation time."""

from datetime import UTC, datetime

import pytest
from dagster import build_schedule_context

from shiro_mlops.pipelines.execution_origin import (
    SCHEDULE_NAME_TAG,
    SCHEDULED_TICK_TAG,
    ExecutionOrigin,
    NoScheduledTickError,
    WithoutTick,
    resolve_as_of,
    tick_run_request,
)

# run 建立於 2026-11-20 03:40:12 UTC，即台灣 11:40:12，晚於 10:25 的 tick。
CREATED_AT = datetime(2026, 11, 20, 3, 40, 12, tzinfo=UTC)
CREATED_AT_IN_TAIWAN = datetime(2026, 11, 20, 11, 40, 12)
TICK_IN_TAIWAN = datetime(2026, 11, 20, 10, 25)
SCHEDULED = {
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
        {**SCHEDULED, "dagster/parent_run_id": "tick-run", "dagster/root_run_id": "tick-run"},
        ExecutionOrigin.REEXECUTION,
        id="re-execution-of-a-scheduled-run",
    ),
    pytest.param(
        {**SCHEDULED, "dagster/parent_run_id": "tick-run"},
        ExecutionOrigin.REEXECUTION,
        id="parent-tag-only",
    ),
    pytest.param(
        {**SCHEDULED, "dagster/root_run_id": "tick-run"},
        ExecutionOrigin.REEXECUTION,
        id="root-tag-only",
    ),
    pytest.param(
        {"dagster/parent_run_id": "manual-run", "dagster/root_run_id": "manual-run"},
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
    tags = {**SCHEDULED, SCHEDULED_TICK_TAG: tick}

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
