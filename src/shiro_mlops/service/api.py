"""FastAPI dynamic on-demand load forecasting service."""

import logging
import operator
from collections.abc import AsyncGenerator, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache, reduce
from pathlib import Path
from typing import Literal, Self

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, create_model
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from shiro_mlops import __version__
from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, DEFAULT_HORIZON_HOURS, MAX_HORIZON_HOURS
from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.router import router as data_explorer_router
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import (
    DYNAMIC_HORIZON_FORECAST,
    UnknownTaskError,
    deployed_task,
    deployed_tasks,
)
from shiro_mlops.tasks.model_store import load_model
from shiro_mlops.tasks.runner import (
    MODEL_NOT_LOADED_REASON,
    PredictionOutcome,
    Readiness,
    TaskNotReady,
    TaskRuntime,
    TaskUnavailableError,
    check_task_ready,
    predict_task,
)
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import TaskModel, WeatherEchoingItem


class ModelStore:
    """In-memory models of the deployed tasks, keyed by task id; untrained tasks are absent."""

    def __init__(self) -> None:
        self.models: dict[str, TaskModel] = {}


model_store = ModelStore()
repository_store: TimeSeriesRepository | None = None
request_clock: Callable[[], pd.Timestamp] = taiwan_now
logger = logging.getLogger(__name__)
WEATHER_SOURCES_FIELD = "weather_sources"


def _served_task() -> TaskDefinition:
    """/predict is the alias of the dynamic horizon forecast task (ADR-0009)."""
    return deployed_task(DYNAMIC_HORIZON_FORECAST)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ensure DB schema, fail fast on invalid task definitions, and load every task model."""
    if settings.ENVIRONMENT != "test":
        try:
            from shiro_mlops.core.database import init_db

            init_db()
        except Exception:
            logger.exception("Database initialization failed; readiness will remain unavailable.")

    _load_task_models(deployed_tasks().values(), settings.models_dir)
    yield


def _load_task_models(tasks: Iterable[TaskDefinition], root: Path) -> None:
    for task in tasks:
        model = _load_task_model(task, root)
        if model is not None:
            model_store.models[task.task_id] = model


def _load_task_model(task: TaskDefinition, root: Path) -> TaskModel | None:
    """A broken model leaves only its own task unserved; the other tasks still load."""
    try:
        return load_model(root, task)
    except Exception:
        logger.exception("Could not load the %s model from %s.", task.task_id, root)
        return None


app = FastAPI(
    title="shiro-mlops Dynamic Horizon Load Forecasting API",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(data_explorer_router)


class TaskModelHealth(BaseModel):
    task_type: str
    model_loaded: bool


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str
    model_loaded: bool = Field(
        description="Whether the model of the task served by /predict is loaded"
    )
    tasks: dict[str, TaskModelHealth] = Field(description="Model load state of each task")
    data_explorer_enabled: bool


class ReadyResponse(BaseModel):
    status: str
    mode: str | None = None
    model_loaded: bool
    reason: str | None = None


class TaskPredictionRequest(BaseModel):
    horizon_hours: int = Field(
        default=DEFAULT_HORIZON_HOURS,
        ge=1,
        le=MAX_HORIZON_HOURS,
        description=(
            f"Hours to predict (1-{MAX_HORIZON_HOURS}): for forecast-weather tasks, the "
            "forecast horizon after the latest actual load; for observed-weather tasks, "
            "how many of the latest window end hours up to that load to score"
        ),
    )


class PredictionRequest(BaseModel):
    horizon_hours: int = Field(
        default=DEFAULT_HORIZON_HOURS,
        ge=1,
        le=MAX_HORIZON_HOURS,
        description=f"Forecast horizon in hours (1-{MAX_HORIZON_HOURS})",
    )
    location: str | None = Field(
        default=None,
        deprecated=True,
        description=(
            "Deprecated and ignored: the forecast subject is always nationwide, "
            "whatever value is sent."
        ),
    )


@dataclass(frozen=True)
class _ItemSchema:
    """What shapes one task's prediction item; hashable, so each schema is built once."""

    task_type: str
    weather_fields: tuple[str, ...]

    @classmethod
    def of(cls, task: TaskDefinition) -> Self:
        return cls(task.task_type, task.weather.fields)


@cache
def _prediction_item(schema: _ItemSchema, name: str) -> type[BaseModel]:
    """The task type's item, plus the task's own weather fields when the item echoes weather."""
    item = get_task_type(schema.task_type).prediction_item
    if not issubclass(item, WeatherEchoingItem):
        return item
    weather_fields = {field: (float, ...) for field in schema.weather_fields}
    return create_model(
        name,
        __base__=item,
        __doc__=item.__doc__,
        **weather_fields,
        weather_sources=(dict[str, dict[str, str]], ...),
    )


# /predict 的 item 即動態視界預報任務的 item，名稱沿用既有 OpenAPI 契約。
PredictionItem = _prediction_item(_ItemSchema.of(_served_task()), "PredictionItem")


class PredictionResponse(BaseModel):
    status: str = "success"
    horizon_hours: int
    subject: str = Field(description="Prediction subject whose load is forecast")
    mode: str = "normal"
    predictions: list[PredictionItem]


class TaskPredictionEnvelope(BaseModel):
    """Fields every task prediction shares; ``predictions`` follows the task type."""

    status: str = "success"
    task_id: str
    subject: str = Field(description="Prediction subject of the task")
    mode: str = Field(description="Weather quality behind the predictions: normal or degraded")


@cache
def _task_prediction_response(task_id: str, schema: _ItemSchema) -> type[TaskPredictionEnvelope]:
    """Response model of one task, told apart from the others by its ``task_id`` constant."""
    name = "".join(part.title() for part in task_id.split("_"))
    return create_model(
        f"{name}TaskPredictionResponse",
        __base__=TaskPredictionEnvelope,
        __doc__=f"Prediction of task {task_id}; items follow its task type and weather fields.",
        task_id=(Literal[task_id], ...),
        task_type=(Literal[schema.task_type], ...),
        predictions=(list[_prediction_item(schema, f"{name}PredictionItem")], ...),
    )


def _response_model(task: TaskDefinition) -> type[TaskPredictionEnvelope]:
    return _task_prediction_response(task.task_id, _ItemSchema.of(task))


# 僅供 OpenAPI 描述；各任務的回應模型建構時即已驗證，端點不再以聯集重驗。
TaskPredictionResponse = reduce(
    operator.or_, (_response_model(task) for _, task in sorted(deployed_tasks().items()))
)


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Check API and per-task model health status."""
    tasks = {
        task_id: TaskModelHealth(
            task_type=task.task_type, model_loaded=task_id in model_store.models
        )
        for task_id, task in deployed_tasks().items()
    }
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.ENVIRONMENT,
        model_loaded=DYNAMIC_HORIZON_FORECAST in model_store.models,
        tasks=tasks,
        data_explorer_enabled=is_data_explorer_enabled(),
    )


@app.get("/ready", response_model=ReadyResponse)
def readiness_check() -> ReadyResponse:
    """Report whether a model and full normal/degraded weather horizon are available."""
    return _readiness(_served_task())


@app.get("/tasks/{task_id}/ready", response_model=ReadyResponse)
def task_readiness_check(task_id: str) -> ReadyResponse:
    """Report whether one task can serve a full-horizon prediction now."""
    return _readiness(_deployed_task_or_404(task_id))


@app.post("/predict", response_model=PredictionResponse)
def predict_dynamic_horizon(request: PredictionRequest) -> PredictionResponse:
    """Predict dynamic horizon future power loads from persisted weather and load data."""
    outcome = _predict(_served_task(), horizon_hours=request.horizon_hours)
    rows = _prediction_rows(outcome)
    return PredictionResponse(
        status="success",
        horizon_hours=len(rows),
        subject=outcome.subject,
        mode=outcome.mode,
        predictions=rows,
    )


@app.post(
    "/tasks/{task_id}/predict",
    response_model=None,
    responses={200: {"model": TaskPredictionResponse}},
)
def predict_for_task(task_id: str, request: TaskPredictionRequest) -> TaskPredictionEnvelope:
    """Predict with one task; the prediction item schema depends on the task."""
    task = _deployed_task_or_404(task_id)
    outcome = _predict(task, horizon_hours=request.horizon_hours)
    return _response_model(task)(
        status="success",
        task_id=task.task_id,
        task_type=task.task_type,
        subject=outcome.subject,
        mode=outcome.mode,
        predictions=_prediction_rows(outcome),
    )


def _deployed_task_or_404(task_id: str) -> TaskDefinition:
    try:
        return deployed_task(task_id)
    except UnknownTaskError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _readiness(task: TaskDefinition) -> ReadyResponse:
    model = model_store.models.get(task.task_id)
    try:
        readiness = check_task_ready(task, model, _runtime(), as_of=request_clock())
    except Exception as error:
        readiness = Readiness(ready=False, reason=str(error))
    if not readiness.ready:
        response = ReadyResponse(
            status="not_ready", model_loaded=model is not None, reason=readiness.reason
        )
        return JSONResponse(status_code=503, content=response.model_dump())
    return ReadyResponse(status="ready", mode=readiness.mode, model_loaded=True)


def _predict(task: TaskDefinition, *, horizon_hours: int) -> PredictionOutcome:
    """Run the task's prediction, mapping missing models and unavailable inputs to HTTP 503."""
    model = model_store.models.get(task.task_id)
    if model is None:
        raise HTTPException(status_code=503, detail=MODEL_NOT_LOADED_REASON)
    try:
        return predict_task(
            task, model, _runtime(), as_of=request_clock(), horizon_hours=horizon_hours
        )
    except (TaskUnavailableError, TaskNotReady) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Persistence unavailable: {error}") from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Prediction error: {error}") from error


def _prediction_rows(outcome: PredictionOutcome) -> list[dict[str, object]]:
    """Merge each prediction row with the weather row and sources at the same position.

    The response model validates the rows against the task's item; fields it lacks are ignored.
    """
    rows = zip(
        outcome.predictions.to_dict("records"),
        outcome.weather.to_dict("records"),
        outcome.weather_sources,
        strict=True,
    )
    return [
        {
            **weather,
            **prediction,
            DATETIME_COL: str(prediction[DATETIME_COL]),
            WEATHER_SOURCES_FIELD: sources,
        }
        for prediction, weather, sources in rows
    ]


def _runtime() -> TaskRuntime:
    """Runner resources for this process, allowing tests to inject an isolated store."""
    return TaskRuntime(repository=repository_store or TimeSeriesRepository())
