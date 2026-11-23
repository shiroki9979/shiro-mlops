"""Resolve a Dagster run into its execution origin and as_of."""

from collections.abc import Mapping
from datetime import datetime
from enum import Enum, StrEnum
from zoneinfo import ZoneInfo

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
        "This run is a re-execution: it copies the original run's scheduled tick but runs later, "
        "so that tick is not its as_of."
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


def _to_taiwan_local(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(ZoneInfo(TAIWAN_TZ)).replace(tzinfo=None)
