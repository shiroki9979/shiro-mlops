"""FastAPI dynamic on-demand load forecasting service."""

import logging
import operator
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache, reduce
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, create_model
from starlette.responses import JSONResponse

from shiro_mlops import __version__
from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import DATETIME_COL, DEFAULT_HORIZON_HOURS, MAX_HORIZON_HOURS
from shiro_mlops.core.datetime_utils import taiwan_now
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import ForecastMode
from shiro_mlops.service.data_explorer import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.router import router as data_explorer_router
from shiro_mlops.service.served_tasks import (
    ServedTasks,
    ServingFailedError,
    ServingUnavailableError,
)
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import (
    DYNAMIC_HORIZON_FORECAST,
    UnknownTaskError,
    deployed_task,
    deployed_tasks,
)
from shiro_mlops.tasks.runner import PredictionOutcome, TaskRuntime
from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import WeatherEchoingItem

logger = logging.getLogger(__name__)
WEATHER_SOURCES_FIELD = "weather_sources"
FORECAST_MODE_DESCRIPTION = (
    "Forecast operating mode: normal, or degraded when any weather value was filled "
    "by an observation substitute"
)


def _served_task() -> TaskDefinition:
    """/predict is the alias of the dynamic horizon forecast task (ADR-0009)."""
    return deployed_task(DYNAMIC_HORIZON_FORECAST)


def get_served_tasks(request: Request) -> ServedTasks:
    return request.app.state.served_tasks


Served = Annotated[ServedTasks, Depends(get_served_tasks)]
routes = APIRouter()


class TaskModelHealth(BaseModel):
    task_type: str
    model_loaded: bool
    model_sha256: str | None = Field(
        description="sha256 of the model directory version being served; null without a model"
    )
    reason: str | None = Field(
        description="Why no model serves: untrained or the load failure; null when loaded"
    )


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
    mode: ForecastMode | None = Field(
        default=None,
        description=f"{FORECAST_MODE_DESCRIPTION}, of a prediction made now; null when not ready",
    )
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
        # 天氣欄位 → 氣象代表點別名 → 來源（ADR-0012）。
        weather_sources=(dict[str, dict[str, dict[str, str]]], ...),
    )


# /predict 的 item 即動態視界預報任務的 item，名稱沿用既有 OpenAPI 契約。
PredictionItem = _prediction_item(_ItemSchema.of(_served_task()), "PredictionItem")


class PredictionResponse(BaseModel):
    status: str = "success"
    horizon_hours: int
    subject: str = Field(description="Prediction subject whose load is forecast")
    mode: ForecastMode = Field(description=FORECAST_MODE_DESCRIPTION)
    predictions: list[PredictionItem]


class TaskPredictionEnvelope(BaseModel):
    """Fields every task prediction shares; ``predictions`` follows the task type."""

    status: str = "success"
    task_id: str
    subject: str = Field(description="Prediction subject of the task")
    mode: ForecastMode = Field(description=FORECAST_MODE_DESCRIPTION)


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


@routes.get("/health", response_model=HealthResponse)
def health_check(served: Served) -> HealthResponse:
    """Check API and per-task model health status."""
    statuses = served.model_status()
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.ENVIRONMENT,
        model_loaded=statuses[DYNAMIC_HORIZON_FORECAST].model_loaded,
        tasks={
            task_id: TaskModelHealth(
                task_type=status.task_type,
                model_loaded=status.model_loaded,
                model_sha256=status.model_sha256,
                reason=status.reason,
            )
            for task_id, status in statuses.items()
        },
        data_explorer_enabled=is_data_explorer_enabled(),
    )


@routes.get("/ready", response_model=ReadyResponse)
def readiness_check(served: Served) -> ReadyResponse:
    """Report whether a model and full normal/degraded weather horizon are available."""
    return _readiness(served, DYNAMIC_HORIZON_FORECAST)


@routes.get("/tasks/{task_id}/ready", response_model=ReadyResponse)
def task_readiness_check(task_id: str, served: Served) -> ReadyResponse:
    """Report whether one task can serve a full-horizon prediction now."""
    return _readiness(served, _task_or_404(served, task_id).task_id)


@routes.post("/predict", response_model=PredictionResponse)
def predict_dynamic_horizon(request: PredictionRequest, served: Served) -> PredictionResponse:
    """Predict dynamic horizon future power loads from persisted weather and load data."""
    outcome = _predict(served, DYNAMIC_HORIZON_FORECAST, horizon_hours=request.horizon_hours)
    rows = _prediction_rows(outcome)
    return PredictionResponse(
        status="success",
        horizon_hours=len(rows),
        subject=outcome.subject,
        mode=outcome.mode,
        predictions=rows,
    )


@routes.post(
    "/tasks/{task_id}/predict",
    response_model=None,
    responses={200: {"model": TaskPredictionResponse}},
)
def predict_for_task(
    task_id: str, request: TaskPredictionRequest, served: Served
) -> TaskPredictionEnvelope:
    """Predict with one task; the prediction item schema depends on the task."""
    task = _task_or_404(served, task_id)
    outcome = _predict(served, task.task_id, horizon_hours=request.horizon_hours)
    return _response_model(task)(
        status="success",
        task_id=task.task_id,
        task_type=task.task_type,
        subject=outcome.subject,
        mode=outcome.mode,
        predictions=_prediction_rows(outcome),
    )


def _task_or_404(served: ServedTasks, task_id: str) -> TaskDefinition:
    try:
        return served.task(task_id)
    except UnknownTaskError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _readiness(served: ServedTasks, task_id: str) -> ReadyResponse:
    readiness = served.readiness(task_id)
    if not readiness.ready:
        return _not_ready(model_loaded=readiness.model_loaded, reason=readiness.reason)
    return ReadyResponse(status="ready", mode=readiness.mode, model_loaded=True)


def _not_ready(*, model_loaded: bool, reason: str | None) -> JSONResponse:
    response = ReadyResponse(status="not_ready", model_loaded=model_loaded, reason=reason)
    return JSONResponse(status_code=503, content=response.model_dump())


def _predict(served: ServedTasks, task_id: str, *, horizon_hours: int) -> PredictionOutcome:
    """Map an unavailable task to HTTP 503 and an unexpected failure to HTTP 500."""
    try:
        return served.predict(task_id, horizon_hours=horizon_hours)
    except ServingUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ServingFailedError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


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


def create_app(
    *, repository: TimeSeriesRepository | None = None, served_tasks: ServedTasks | None = None
) -> FastAPI:
    """Build the API; whatever is not injected is set up at startup from settings.

    ``repository`` is the composition root: the Data Explorer reads its engine
    and served tasks built at startup read its two task stores. Inject it
    together with ``served_tasks``: injected alone, ``served_tasks`` reads
    through its own stores while the Data Explorer gets the root startup
    builds. Invalid task definitions fail startup.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        root = repository or _startup_repository()
        app.state.repository = root
        app.state.served_tasks = served_tasks or ServedTasks.load(
            deployed_tasks(),
            settings.models_dir,
            runtime=TaskRuntime(
                hourly_actual_load=root.hourly_actual_load_store,
                cwa_weather=root.cwa_weather_store,
            ),
            clock=taiwan_now,
        )
        yield

    app = FastAPI(
        title="shiro-mlops Dynamic Horizon Load Forecasting API",
        version=__version__,
        lifespan=lifespan,
    )
    # WHY-NOT(repository): 注入的 repository 與 served_tasks 都在建構時放入 app.state，不等 lifespan。
    # 未進入 lifespan 的 TestClient 也會呼叫端點；改等 lifespan 時，get_served_tasks
    # 與營運資料檢視器的 _engine 讀 app.state 會拋 AttributeError。
    if repository is not None:
        app.state.repository = repository
    if served_tasks is not None:
        app.state.served_tasks = served_tasks
    app.include_router(routes)
    app.include_router(data_explorer_router)
    return app


def _startup_repository() -> TimeSeriesRepository:
    """The schema is ensured once here, so requests do not rerun its DDL."""
    if settings.ENVIRONMENT != "test":
        try:
            from shiro_mlops.core.database import init_db

            init_db()
        except Exception:
            logger.exception("Database initialization failed; readiness will remain unavailable.")
    return TimeSeriesRepository(auto_init=False)


app = create_app()
