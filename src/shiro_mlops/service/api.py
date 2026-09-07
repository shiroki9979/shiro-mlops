"""FastAPI dynamic on-demand load forecasting service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from shiro_mlops import __version__
from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_LOCATION,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.data.weather_resolution import WeatherResolution, resolve_weather
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster


# In-memory cached model instance
class ModelStore:
    forecaster: LightGBMRecursiveForecaster | None = None


model_store = ModelStore()
repository_store: TimeSeriesRepository | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event to ensure DB schema and load or initialize the LightGBM model."""
    try:
        from shiro_mlops.core.database import init_db

        init_db()
    except Exception:
        pass

    model_path = settings.DATA_DIR / "model.joblib"

    if model_path.exists():
        try:
            model_store.forecaster = LightGBMRecursiveForecaster.load(model_path)
        except Exception:
            model_store.forecaster = None
    yield


app = FastAPI(
    title="shiro-mlops Dynamic Horizon Load Forecasting API",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    environment: str
    model_loaded: bool


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
        default=DEFAULT_HORIZON_HOURS, ge=1, le=168, description="Forecast horizon in hours (1-168)"
    )
    location: str = Field(default=DEFAULT_LOCATION, description="Location region (e.g. Taipei)")


class PredictionResponse(BaseModel):
    status: str = "success"
    horizon_hours: int
    location: str
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
    )


def _get_repository() -> TimeSeriesRepository:
    """Return the process repository, allowing tests to inject an isolated store."""
    return repository_store or TimeSeriesRepository()


def _load_history(repository: TimeSeriesRepository) -> pd.DataFrame:
    """Load persisted Taipei load history in the model's feature-column contract."""
    history = repository.fetch_load_range(location=DEFAULT_LOCATION)
    if history.empty:
        return history
    if DATETIME_COL not in history.columns and "time" in history.columns:
        history = history.rename(columns={"time": DATETIME_COL})
    return history


def _resolve_prediction_weather(
    repository: TimeSeriesRepository, history: pd.DataFrame, horizon_hours: int
) -> WeatherResolution:
    """Resolve future weather from canonical storage for a prediction request."""
    last_time = pd.Timestamp(history[DATETIME_COL].max())
    return resolve_weather(
        repository,
        start_time=last_time + pd.Timedelta(hours=1),
        horizon_hours=horizon_hours,
        as_of=last_time,
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
        repository = _get_repository()
        history = _load_history(repository)
        if history.empty:
            raise RuntimeError("No persisted Taipei load history is available.")
        weather = _resolve_prediction_weather(repository, history, 168)
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


@app.get("/features/latest")
def get_latest_features(limit: int = 24) -> list[dict]:
    """Retrieve latest available raw load and weather snapshots."""
    try:
        taipower_client = TaipowerClient()
        df = taipower_client.fetch_load_data()
        latest = df.tail(limit).to_dict(orient="records")
        # Format datetimes
        for item in latest:
            if isinstance(item.get(DATETIME_COL), pd.Timestamp):
                item[DATETIME_COL] = item[DATETIME_COL].isoformat()
        return latest
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch latest features: {e}") from e


@app.post("/predict", response_model=PredictionResponse)
def predict_dynamic_horizon(request: PredictionRequest) -> PredictionResponse:
    """Predict dynamic horizon future power loads from persisted weather and load data."""
    if model_store.forecaster is None:
        raise HTTPException(status_code=503, detail="Model is not loaded or trained yet.")

    if request.location != DEFAULT_LOCATION:
        raise HTTPException(status_code=400, detail="Only Taipei is supported in this model phase.")

    try:
        repository = _get_repository()
        history_df = _load_history(repository)
        if history_df.empty:
            raise HTTPException(
                status_code=503, detail="No persisted Taipei load history available."
            )
        weather = _resolve_prediction_weather(repository, history_df, request.horizon_hours)
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
            location=request.location,
            mode=weather.mode,
            predictions=items,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail=f"Persistence unavailable: {error}") from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}") from e
