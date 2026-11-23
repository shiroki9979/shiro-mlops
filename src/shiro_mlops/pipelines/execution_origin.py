"""Resolve a Dagster run into its execution origin and as_of.

A schedule tags the run its tick launches with that tick, in Taiwan-local ISO
time, through ``tick_run_request``; assets never read the tick from config. The
tick counts only in the run the schedule launched: one Dagster also tagged with
the schedule name, and not a re-execution, which copies the original run's tags.
Any other run has no tick, and each asset with an as_of declares what it does
then (``WithoutTick``): refuse, or fall back to now. Now is the run's creation
time, so every retry inside one run gets the same as_of. Flooring the as_of to
a ten-minute slot or an hour stays with each asset's domain functions.
"""

from collections.abc import Mapping
from datetime import datetime
from enum import Enum, StrEnum
from zoneinfo import ZoneInfo

from dagster import AssetExecutionContext, Failure, RunRequest, ScheduleEvaluationContext
from dagster_shared.check import CheckError

from shiro_mlops.core.datetime_utils import TAIWAN_TZ

SCHEDULED_TICK_TAG = "shiro_mlops/scheduled_tick"
SCHEDULE_NAME_TAG = "dagster/schedule_name"
REEXECUTION_TAGS = ("dagster/parent_run_id", "dagster/root_run_id")


class ExecutionOrigin(StrEnum):
    """Where a run came from; a retry inside a run keeps that run's origin."""

    SCHEDULED_TICK = "scheduled_tick"
    MANUAL = "manual"
    REEXECUTION = "reexecution"


class WithoutTick(Enum):
    """What an asset with an as_of does when its run carries no scheduled tick."""

    REFUSE = "refuse"
    FALL_BACK_TO_NOW = "fall_back_to_now"


class NoScheduledTickError(Exception):
    """The run has no scheduled tick, and the asset refuses to run without one."""

    def __init__(self, origin: ExecutionOrigin) -> None:
        self.origin = origin
        super().__init__(_REFUSAL_REASONS[origin])


_REFUSAL_REASONS = {
    ExecutionOrigin.MANUAL: (
        "This run has no scheduled tick: only the run a schedule tick launched carries one."
    ),
    ExecutionOrigin.REEXECUTION: (
        "This run is a re-execution: it copies the original run's tags, any scheduled tick "
        "among them, but runs later, so that tick is not its as_of."
    ),
}


def resolve_as_of(
    tags: Mapping[str, str], created_at: datetime, *, without_tick: WithoutTick
) -> datetime:
    """The run's as_of in naive Taiwan-local time, not yet floored to any slot."""
    origin = execution_origin(tags)
    if origin is ExecutionOrigin.SCHEDULED_TICK:
        return _to_taiwan_local(datetime.fromisoformat(tags[SCHEDULED_TICK_TAG]))
    if without_tick is WithoutTick.REFUSE:
        raise NoScheduledTickError(origin)
    return _to_taiwan_local(created_at)


def execution_origin(tags: Mapping[str, str]) -> ExecutionOrigin:
    """A tick counts only together with the schedule name Dagster tags each schedule run with."""
    if any(tag in tags for tag in REEXECUTION_TAGS):
        return ExecutionOrigin.REEXECUTION
    if SCHEDULED_TICK_TAG in tags and SCHEDULE_NAME_TAG in tags:
        return ExecutionOrigin.SCHEDULED_TICK
    return ExecutionOrigin.MANUAL


def run_as_of(context: AssetExecutionContext, *, without_tick: WithoutTick) -> datetime:
    """The as_of of the run this asset executes in: its tags and creation time, never the clock.

    A refusal fails the run with a ``Failure`` that says why the run has no tick.
    """
    created_at = context.instance.get_run_record_by_id(context.run_id).create_timestamp
    try:
        return resolve_as_of(context.run.tags, created_at, without_tick=without_tick)
    except NoScheduledTickError as refusal:
        raise Failure(description=str(refusal)) from refusal


def tick_run_request(context: ScheduleEvaluationContext) -> RunRequest:
    """Key and tag the run with the tick; an evaluation without a tick gets neither."""
    tick = tick_run_key(context)
    if tick is None:
        return RunRequest()
    return RunRequest(run_key=tick, tags={SCHEDULED_TICK_TAG: tick})


def tick_run_key(context: ScheduleEvaluationContext) -> str | None:
    """Deduplicate repeated evaluations of the same tick with a run key."""
    tick = scheduled_tick(context)
    if tick is None:
        return None
    return tick.isoformat(timespec="seconds")


def scheduled_tick(context: ScheduleEvaluationContext) -> datetime | None:
    """The tick in naive Taiwan-local time, or None for an evaluation built without one.

    Dagster raises CheckError on access instead of returning None when no tick was
    set, so a plain ``is None`` check never runs.
    """
    try:
        tick = context.scheduled_execution_time
    except CheckError:
        return None
    return _to_taiwan_local(tick)


def _to_taiwan_local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)
