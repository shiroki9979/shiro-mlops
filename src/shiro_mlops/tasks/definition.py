"""Task definitions: ``tasks/<task_id>.toml`` read with tomllib and validated in two stages.

Stage one validates the fields every task shares; stage two validates ``[params]``
and ``[health]`` against the models of the named task type. Every failure raises
``TaskDefinitionError`` naming the file and the offending field, so a bad
definition stops the process at startup (ADR-0009).
"""

from __future__ import annotations

import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    ValidationError,
    model_validator,
)

from shiro_mlops.data.cwa_client import CWALocation, resolve_cwa_location
from shiro_mlops.tasks.types import UnknownTaskTypeError, get_task_type

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
    """Shared-component parameters; task types must not reimplement these rules.

    ``max_training_hours`` bounds the training window: training reads only that many
    hours of target history ending at ``as_of``; omitted, it reads all history.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_training_hours: PositiveInt
    stale_anchor_max_lag_hours: PositiveInt
    validation_fraction: float = Field(gt=0.0, lt=1.0)
    max_training_hours: PositiveInt | None = None

    @model_validator(mode="after")
    def _window_holds_the_minimum_accumulation(self) -> TaskPolicies:
        if (
            self.max_training_hours is not None
            and self.max_training_hours < self.min_training_hours
        ):
            raise ValueError(
                f"max_training_hours={self.max_training_hours} is shorter than "
                f"min_training_hours={self.min_training_hours}; the training window could "
                "never hold the history training waits for"
            )
        return self


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


# 權重總和容許的浮點誤差；TOML 中的十進位權重（例如 0.45、0.3、0.25）相加不一定剛好為 1。
WEIGHT_SUM_TOLERANCE = 1e-6


class _WeatherSection(BaseModel):
    """Weather reference points with their weights for the task's weighted weather (ADR-0012)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_points: list[str] = Field(min_length=1)
    # 單一代表點可省略（權重為 1）；多個代表點必須逐一給權重。
    weights: list[float] | None = None
    fields: list[WeatherField] = Field(min_length=1)

    @model_validator(mode="after")
    def _weights_combine_into_one_value(self) -> _WeatherSection:
        points = self.reference_points
        if len(set(points)) != len(points):
            raise ValueError("a weather reference point is listed more than once")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("a weather field is listed more than once")
        if self.weights is None:
            if len(points) > 1:
                raise ValueError("multiple weather reference points need weights")
            return self
        if len(self.weights) != len(points):
            raise ValueError("list one weight per reference point")
        if any(weight <= 0.0 for weight in self.weights):
            raise ValueError("every weight must be greater than 0")
        if not math.isclose(sum(self.weights), 1.0, abs_tol=WEIGHT_SUM_TOLERANCE):
            raise ValueError(f"weights must sum to 1, got {sum(self.weights)}")
        return self

    @property
    def point_weights(self) -> list[float]:
        return list(self.weights) if self.weights is not None else [1.0]


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
class WeightedReferencePoint:
    """One weather reference point and its share of the task's weighted weather."""

    location: CWALocation
    weight: float


@dataclass(frozen=True)
class WeatherSpec:
    """The task's weighted weather reference points, resolved against the ingestion catalog."""

    reference_points: tuple[WeightedReferencePoint, ...]
    fields: tuple[str, ...]

    @property
    def aliases(self) -> tuple[str, ...]:
        """Catalog aliases of the reference points, in task definition order."""
        return tuple(point.location.alias for point in self.reference_points)


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
    return TaskDefinition(
        task_id=spec.task_id,
        task_type=spec.task_type,
        subject=spec.subject,
        target=spec.target,
        weather=WeatherSpec(
            reference_points=_resolve_reference_points(path, spec.weather, catalog),
            fields=tuple(spec.weather.fields),
        ),
        policies=spec.policies,
        params=_validate(path, task_type.params_model, spec.params, location="params"),
        schedule=spec.schedule,
        health=_validate(path, task_type.health_model, spec.health, location="health"),
    )


def build_weather_spec(
    reference_points: Sequence[str],
    weights: Sequence[float] | None,
    fields: Sequence[str],
    catalog: Mapping[str, CWALocation],
) -> WeatherSpec:
    """Validate and resolve weighted weather outside a task file, with the TOML's rules.

    Lets research tools try other reference-point combinations without editing a
    shipped definition. Invalid weights, fields or reference points raise ``ValueError``.
    """
    raw: dict[str, Any] = {"reference_points": list(reference_points), "fields": list(fields)}
    if weights is not None:
        raw["weights"] = list(weights)
    try:
        section = _WeatherSection.model_validate(raw)
    except ValidationError as error:
        raise ValueError(_describe(error, "weather")) from error
    return WeatherSpec(
        reference_points=_weighted_points(section, catalog), fields=tuple(section.fields)
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


def _resolve_reference_points(
    path: Path, weather: _WeatherSection, catalog: Mapping[str, CWALocation]
) -> tuple[WeightedReferencePoint, ...]:
    try:
        return _weighted_points(weather, catalog)
    except ValueError as error:
        raise TaskDefinitionError(path, f"weather.reference_points: {error}") from error


def _weighted_points(
    weather: _WeatherSection, catalog: Mapping[str, CWALocation]
) -> tuple[WeightedReferencePoint, ...]:
    return tuple(
        WeightedReferencePoint(resolve_cwa_location(catalog, name), weight)
        for name, weight in zip(weather.reference_points, weather.point_weights, strict=True)
    )
