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
    DEFAULT_WEATHER_REFERENCE_POINT,
    MAX_HORIZON_HOURS,
    NATIONWIDE_SUBJECT,
    RELATIVE_HUMIDITY_COL,
    STORAGE_TIME_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.hourly_actual_load import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    is_stale_load_anchor,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.weather_resolution import WeatherResolution, resolve_weather
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster
from shiro_mlops.service.data_explorer import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.router import router as data_explorer_router


# In-memory cached model instance
class ModelStore:
    forecaster: LightGBMRecursiveForecaster | None = None


def _taiwan_now() -> pd.Timestamp:
    """Return the current instant as Taiwan-local naive time, matching persisted load time."""
    return pd.Timestamp.now(tz=TAIWAN_TZ).tz_localize(None)


model_store = ModelStore()
repository_store: TimeSeriesRepository | None = None
request_clock: Callable[[], pd.Timestamp] = _taiwan_now
logger = logging.getLogger(__name__)


class StaleLoadAnchorError(RuntimeError):
    """The latest actual load is too old to anchor a recursive forecast."""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event to ensure DB schema and load or initialize the LightGBM model."""
    if settings.ENVIRONMENT != "test":
        try:
            from shiro_mlops.core.database import init_db

            init_db()
        except Exception:
            logger.exception("Database initialization failed; readiness will remain unavailable.")

    model_path = settings.DATA_DIR / "model.joblib"

    if model_path.exists():
        try:
            model_store.forecaster = LightGBMRecursiveForecaster.load(model_path)
        except Exception:
            logger.exception("Could not load model artifact from %s.", model_path)
            model_store.forecaster = None
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
        model_loaded=model_store.forecaster is not None,
        data_explorer_enabled=is_data_explorer_enabled(),
    )


def _get_repository() -> TimeSeriesRepository:
    """Return the process repository, allowing tests to inject an isolated store."""
    return repository_store or TimeSeriesRepository()


def _load_history(repository: TimeSeriesRepository) -> pd.DataFrame:
    """Load persisted nationwide load history in the model's feature-column contract.

    Only derived rows are read: d015046-era rows (NULL source) use a different
    measurement basis and must never anchor or feed a recursive forecast (ADR-0008).
    """
    history = repository.fetch_load_range(
        subject=NATIONWIDE_SUBJECT, source=REGIONAL_SNAPSHOT_SUM_SOURCE
    )
    if history.empty:
        return history
    if DATETIME_COL not in history.columns and STORAGE_TIME_COL in history.columns:
        history = history.rename(columns={STORAGE_TIME_COL: DATETIME_COL})
    return history


def _load_anchor(history: pd.DataFrame) -> pd.Timestamp:
    """The newest actual load hour, from which the recursive forecast starts."""
    return pd.Timestamp(history[DATETIME_COL].max())


def _ensure_fresh_load_anchor(anchor: pd.Timestamp, request_time: pd.Timestamp) -> None:
    """Refuse rather than degrade: actual load has no substitute as the recursion origin."""
    max_lag_hours = settings.LOAD_ANCHOR_MAX_LAG_HOURS
    if is_stale_load_anchor(anchor, request_time, max_lag_hours):
        raise StaleLoadAnchorError(
            f"Stale load anchor: latest actual load at {anchor.isoformat()} lags request time "
            f"{request_time.isoformat()} by more than {max_lag_hours} hours."
        )


def _resolve_prediction_weather(
    repository: TimeSeriesRepository,
    anchor: pd.Timestamp,
    horizon_hours: int,
    request_time: pd.Timestamp,
) -> WeatherResolution:
    """Resolve future weather from canonical storage as it was known at request time."""
    return resolve_weather(
        repository,
        reference_point=settings.weather_reference_point(DEFAULT_WEATHER_REFERENCE_POINT),
        start_time=anchor + pd.Timedelta(hours=1),
        horizon_hours=horizon_hours,
        as_of=request_time,
    )


@app.get("/ready", response_model=ReadyResponse)
def readiness_check() -> ReadyResponse:
    """Report whether a model and full normal/degraded weather horizon are available."""
    if model_store.forecaster is None:
        response = ReadyResponse(
            status="not_ready", model_loaded=False, reason="Model is not loaded or trained yet."
        )
        return JSONResponse(status_code=503, content=response.model_dump())
    try:
        request_time = request_clock()
        repository = _get_repository()
        history = _load_history(repository)
        if history.empty:
            raise RuntimeError("No persisted nationwide load history is available.")
        anchor = _load_anchor(history)
        _ensure_fresh_load_anchor(anchor, request_time)
        weather = _resolve_prediction_weather(repository, anchor, MAX_HORIZON_HOURS, request_time)
        if weather.mode == "unavailable":
            raise RuntimeError(weather.reason or "Weather coverage is unavailable.")
        return ReadyResponse(
            status="ready",
            mode=weather.mode,
            model_loaded=True,
        )
    except Exception as error:
        response = ReadyResponse(status="not_ready", model_loaded=True, reason=str(error))
        return JSONResponse(status_code=503, content=response.model_dump())


@app.post("/predict", response_model=PredictionResponse)
def predict_dynamic_horizon(request: PredictionRequest) -> PredictionResponse:
    """Predict dynamic horizon future power loads from persisted weather and load data."""
    if model_store.forecaster is None:
        raise HTTPException(status_code=503, detail="Model is not loaded or trained yet.")

    try:
        request_time = request_clock()
        repository = _get_repository()
        history_df = _load_history(repository)
        if history_df.empty:
            raise HTTPException(
                status_code=503, detail="No persisted nationwide load history available."
            )
        anchor = _load_anchor(history_df)
        _ensure_fresh_load_anchor(anchor, request_time)
        weather = _resolve_prediction_weather(
            repository, anchor, request.horizon_hours, request_time
        )
        if weather.mode == "unavailable" or weather.dataframe.empty:
            raise HTTPException(
                status_code=503, detail=weather.reason or "Weather coverage unavailable."
            )
        pred_df = model_store.forecaster.predict_recursive(
            history_df=history_df,
            future_weather_df=weather.dataframe,
            horizon_hours=request.horizon_hours,
        )

        items = [
            PredictionItem(
                datetime=str(row[DATETIME_COL]),
                predicted_load_mw=float(row["predicted_load_mw"]),
                temperature=float(row[TEMPERATURE_COL]),
                relative_humidity=float(row[RELATIVE_HUMIDITY_COL]),
                weather_sources=weather.sources[index],
            )
            for index, (_, row) in enumerate(pred_df.iterrows())
        ]

        return PredictionResponse(
            status="success",
            horizon_hours=len(items),
            subject=NATIONWIDE_SUBJECT,
            mode=weather.mode,
            predictions=items,
        )
    except HTTPException:
        raise
    except StaleLoadAnchorError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Persistence unavailable: {error}") from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}") from e
