"""Task definitions: ``tasks/<task_id>.toml`` read with tomllib and validated in two stages.

Stage one validates the fields every task shares; stage two validates ``[params]``
and ``[health]`` against the models of the named task type. Every failure raises
``TaskDefinitionError`` naming the file and the offending field, so a bad
definition stops the process at startup (ADR-0009).
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar, get_args

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationError,
    field_validator,
)

from shiro_mlops.data.cwa_client import CWALocation, resolve_cwa_location
from shiro_mlops.tasks.types import UnknownTaskTypeError, get_task_type
from shiro_mlops.tasks.types.base import TaskType

HOURLY_ACTUAL_LOAD_TARGET = "hourly_actual_load"
# 訓練讀測站觀測、預報讀鄉鎮預報；兩者同時提供的欄位才可作為任務的氣象欄位。
WeatherField = Literal["temperature", "relative_humidity"]
Model = TypeVar("Model", bound=BaseModel)
# minute hour day-of-month month day-of-week；只接受數字、*、範圍、步進與逗號清單，
# 為 Dagster 可解析之 cron 的嚴格子集，錯誤得以在載入任務設定時就失敗。
CRON_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_CRON_PART = re.compile(r"^(?:\*|(\d+)(?:-(\d+))?)(?:/(\d+))?$")


class TaskDefinitionError(ValueError):
    """A task definition file is missing, malformed, or references unknown catalog entries."""

    def __init__(self, path: Path, detail: str):
        super().__init__(f"Invalid task definition {path}: {detail}")
        self.path = path
        self.detail = detail


class TaskPolicies(BaseModel):
    """Shared-component parameters; task types must not reimplement these rules."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_training_hours: PositiveInt
    stale_anchor_max_lag_hours: PositiveInt
    validation_fraction: float = Field(gt=0.0, lt=1.0)


def _validate_cron(expression: str) -> str:
    fields = expression.split()
    if len(fields) != len(CRON_FIELD_RANGES):
        raise ValueError(
            f"{expression!r} must have five fields: minute hour day-of-month month day-of-week"
        )
    for field, (low, high) in zip(fields, CRON_FIELD_RANGES, strict=True):
        if not all(_is_valid_cron_part(part, low, high) for part in field.split(",")):
            raise ValueError(
                f"{expression!r} has an invalid field {field!r} (allowed {low}-{high})"
            )
    return expression


def _is_valid_cron_part(part: str, low: int, high: int) -> bool:
    match = _CRON_PART.match(part)
    if match is None:
        return False
    start, end, step = match.groups()
    bounds = [int(value) for value in (start, end) if value is not None]
    in_range = all(low <= value <= high for value in bounds)
    ordered = end is None or int(start) <= int(end)
    return in_range and ordered and (step is None or int(step) > 0)


CronExpression = Annotated[str, AfterValidator(_validate_cron)]


class TaskSchedule(BaseModel):
    """Cron expressions in Asia/Taipei time for the task's training and monitoring runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    training: CronExpression
    monitoring: CronExpression


class _WeatherSection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_points: list[str] = Field(min_length=1)
    fields: list[WeatherField] = Field(min_length=1)

    @field_validator("reference_points")
    @classmethod
    def _single_reference_point(cls, value: list[str]) -> list[str]:
        if len(value) > 1:
            raise ValueError(
                "multiple weather reference points are not supported yet "
                "(weighting is deferred to M3); list exactly one"
            )
        return value


class _TaskFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    task_type: str
    subject: str = Field(min_length=1)
    target: Literal["hourly_actual_load"]
    weather: _WeatherSection
    policies: TaskPolicies
    params: dict[str, Any]
    schedule: TaskSchedule
    health: dict[str, Any]


@dataclass(frozen=True)
class WeatherSpec:
    """The task's weather reference point, resolved against the ingestion catalog."""

    reference_point: CWALocation
    fields: tuple[str, ...]


@dataclass(frozen=True)
class TaskDefinition:
    """A validated ML task: which values to use; its task type decides how."""

    task_id: str
    task_type: str
    subject: str
    target: str
    weather: WeatherSpec
    policies: TaskPolicies
    params: BaseModel
    schedule: TaskSchedule
    # 依任務類型的 health_model 驗證；判定規則見 TaskType.assess_health。
    health: BaseModel


def load_task_definitions(
    directory: Path, catalog: Mapping[str, CWALocation]
) -> dict[str, TaskDefinition]:
    """Load every ``*.toml`` task definition in ``directory``, keyed by task id."""
    definitions = [load_task_definition(path, catalog) for path in sorted(directory.glob("*.toml"))]
    return {definition.task_id: definition for definition in definitions}


def load_task_definition(path: Path, catalog: Mapping[str, CWALocation]) -> TaskDefinition:
    """Load one task definition file and resolve its references."""
    spec = _validate(path, _TaskFile, _read_toml(path))
    if spec.task_id != path.stem:
        raise TaskDefinitionError(
            path, f"task_id: {spec.task_id!r} must match the file name {path.stem!r}"
        )
    try:
        task_type = get_task_type(spec.task_type)
    except UnknownTaskTypeError as error:
        raise TaskDefinitionError(path, f"task_type: {error}") from error
    _require_item_weather_fields(path, task_type, spec.weather)
    return TaskDefinition(
        task_id=spec.task_id,
        task_type=spec.task_type,
        subject=spec.subject,
        target=spec.target,
        weather=WeatherSpec(
            reference_point=_resolve_reference_point(path, spec.weather, catalog),
            fields=tuple(spec.weather.fields),
        ),
        policies=spec.policies,
        params=_validate(path, task_type.params_model, spec.params, location="params"),
        schedule=spec.schedule,
        health=_validate(path, task_type.health_model, spec.health, location="health"),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            return tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise TaskDefinitionError(path, str(error)) from error


def _validate(path: Path, model: type[Model], raw: Mapping[str, Any], location: str = "") -> Model:
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        raise TaskDefinitionError(path, _describe(error, location)) from error


def _describe(error: ValidationError, location: str) -> str:
    problems = []
    for issue in error.errors():
        field = ".".join(str(part) for part in (location, *issue["loc"]) if part != "")
        problems.append(f"{field or '<root>'}: {issue['msg']}")
    return "; ".join(problems)


def _require_item_weather_fields(path: Path, task_type: TaskType, weather: _WeatherSection) -> None:
    """Weather the prediction item echoes must be read, or the response fails validation (500)."""
    echoed = set(task_type.prediction_item.model_fields) & set(get_args(WeatherField))
    missing = sorted(echoed - set(weather.fields))
    if missing:
        raise TaskDefinitionError(
            path,
            f"weather.fields: task type {task_type.name!r} returns {missing} in every "
            "prediction item, so they must be declared",
        )


def _resolve_reference_point(
    path: Path, weather: _WeatherSection, catalog: Mapping[str, CWALocation]
) -> CWALocation:
    try:
        return resolve_cwa_location(catalog, weather.reference_points[0])
    except ValueError as error:
        raise TaskDefinitionError(path, f"weather.reference_points: {error}") from error
