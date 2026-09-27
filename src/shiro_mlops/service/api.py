"""FastAPI dynamic on-demand load forecasting service."""

import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from shiro_mlops import __version__
from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_HORIZON_HOURS,
    MAX_HORIZON_HOURS,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.router import router as data_explorer_router
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.model_store import load_model
from shiro_mlops.tasks.runner import (
    Readiness,
    TaskRuntime,
    TaskUnavailableError,
    check_task_ready,
    predict_task,
)
from shiro_mlops.tasks.types.base import TaskModel
from shiro_mlops.tasks.types.recursive_regression import PREDICTION_COL


# In-memory cached model of the task /predict serves
class ModelStore:
    model: TaskModel | None = None


def _taiwan_now() -> pd.Timestamp:
    """Return the current instant as Taiwan-local naive time, matching persisted load time."""
    return pd.Timestamp.now(tz=TAIWAN_TZ).tz_localize(None)


model_store = ModelStore()
repository_store: TimeSeriesRepository | None = None
request_clock: Callable[[], pd.Timestamp] = _taiwan_now
logger = logging.getLogger(__name__)


def _served_task() -> TaskDefinition:
    """/predict is the alias of the dynamic horizon forecast task (ADR-0009)."""
    return deployed_task(DYNAMIC_HORIZON_FORECAST)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Ensure DB schema, fail fast on invalid task definitions, and load the served model."""
    if settings.ENVIRONMENT != "test":
        try:
            from shiro_mlops.core.database import init_db

            init_db()
        except Exception:
            logger.exception("Database initialization failed; readiness will remain unavailable.")

    task = _served_task()
    try:
        model = load_model(settings.models_dir, task)
    except Exception:
        logger.exception("Could not load the %s model from %s.", task.task_id, settings.models_dir)
        model = None
    if model is not None:
        model_store.model = model
    yield


app = FastAPI(
    title="shiro-mlops Dynamic Horizon Load Forecasting API",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(data_explorer_router)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str
    model_loaded: bool
    data_explorer_enabled: bool


class ReadyResponse(BaseModel):
    status: str
    mode: str | None = None
    model_loaded: bool
    reason: str | None = None


class PredictionItem(BaseModel):
    datetime: str
    predicted_load_mw: float
    temperature: float
    relative_humidity: float
    weather_sources: dict[str, dict[str, str]]


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


class PredictionResponse(BaseModel):
    status: str = "success"
    horizon_hours: int
    subject: str = Field(description="Prediction subject whose load is forecast")
    mode: str = "normal"
    predictions: list[PredictionItem]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Check API and model health status."""
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.ENVIRONMENT,
        model_loaded=model_store.model is not None,
        data_explorer_enabled=is_data_explorer_enabled(),
    )


def _runtime() -> TaskRuntime:
    """Runner resources for this process, allowing tests to inject an isolated store."""
    return TaskRuntime(repository=repository_store or TimeSeriesRepository())


@app.get("/ready", response_model=ReadyResponse)
def readiness_check() -> ReadyResponse:
    """Report whether a model and full normal/degraded weather horizon are available."""
    model = model_store.model
    try:
        readiness = check_task_ready(_served_task(), model, _runtime(), as_of=request_clock())
    except Exception as error:
        readiness = Readiness(ready=False, reason=str(error))
    if not readiness.ready:
        response = ReadyResponse(
            status="not_ready", model_loaded=model is not None, reason=readiness.reason
        )
        return JSONResponse(status_code=503, content=response.model_dump())
    return ReadyResponse(status="ready", mode=readiness.mode, model_loaded=True)


@app.post("/predict", response_model=PredictionResponse)
def predict_dynamic_horizon(request: PredictionRequest) -> PredictionResponse:
    """Predict dynamic horizon future power loads from persisted weather and load data."""
    model = model_store.model
    if model is None:
        raise HTTPException(status_code=503, detail="Model is not loaded or trained yet.")

    try:
        outcome = predict_task(
            _served_task(),
            model,
            _runtime(),
            as_of=request_clock(),
            horizon_hours=request.horizon_hours,
        )
    except TaskUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Persistence unavailable: {error}") from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}") from e

    items = [
        PredictionItem(
            datetime=str(prediction[DATETIME_COL]),
            predicted_load_mw=float(prediction[PREDICTION_COL]),
            temperature=float(weather[TEMPERATURE_COL]),
            relative_humidity=float(weather[RELATIVE_HUMIDITY_COL]),
            weather_sources=sources,
        )
        for (_, prediction), (_, weather), sources in zip(
            outcome.predictions.iterrows(),
            outcome.weather.iterrows(),
            outcome.weather_sources,
            strict=True,
        )
    ]
    return PredictionResponse(
        status="success",
        horizon_hours=len(items),
        subject=outcome.subject,
        mode=outcome.mode,
        predictions=items,
    )
