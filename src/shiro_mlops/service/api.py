"""FastAPI dynamic on-demand load forecasting service."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shiro_mlops import __version__
from shiro_mlops.core.config import settings
from shiro_mlops.core.constants import (
    DATETIME_COL,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_LOCATION,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.data.cwa_client import CWAClient
from shiro_mlops.data.taipower_client import TaipowerClient
from shiro_mlops.features.transformers import build_feature_pipeline
from shiro_mlops.models.forecaster import LightGBMRecursiveForecaster


# In-memory cached model instance
class ModelStore:
    forecaster: LightGBMRecursiveForecaster | None = None


model_store = ModelStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan event to ensure DB schema and load or initialize the LightGBM model."""
    try:
        from shiro_mlops.core.database import init_db

        init_db()
    except Exception:
        pass

    model_path = Path("data/model.joblib")

    if model_path.exists():
        try:
            model_store.forecaster = LightGBMRecursiveForecaster.load(model_path)
        except Exception:
            model_store.forecaster = None
    if model_store.forecaster is None:
        # Train a bootstrap model if not yet trained
        try:
            taipower_client = TaipowerClient()
            cwa_client = CWAClient(api_key=settings.CWA_API_KEY)
            load_df = taipower_client.fetch_load_data()
            weather_df = cwa_client.fetch_observations()
            feat_df = build_feature_pipeline(load_df, weather_df)
            forecaster = LightGBMRecursiveForecaster()
            forecaster.fit(feat_df)
            forecaster.save(model_path)
            model_store.forecaster = forecaster
        except Exception:
            # Safe dummy fallback for testing
            pass
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


class PredictionItem(BaseModel):
    datetime: str
    predicted_load_mw: float
    temperature: float
    relative_humidity: float


class PredictionRequest(BaseModel):
    horizon_hours: int = Field(
        default=DEFAULT_HORIZON_HOURS, ge=1, le=168, description="Forecast horizon in hours (1-168)"
    )
    location: str = Field(default=DEFAULT_LOCATION, description="Location region (e.g. Taipei)")


class PredictionResponse(BaseModel):
    status: str = "success"
    horizon_hours: int
    location: str
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
    """Predict dynamic horizon future power loads using latest available history and CWA weather forecasts."""
    if model_store.forecaster is None:
        raise HTTPException(status_code=503, detail="Model is not loaded or trained yet.")

    try:
        taipower_client = TaipowerClient()
        cwa_client = CWAClient(api_key=settings.CWA_API_KEY)

        # 1. Fetch recent historical load data
        history_df = taipower_client.fetch_load_data()

        # 2. Fetch dynamic horizon future weather forecast
        forecast_weather_df = cwa_client.fetch_forecast(
            location=request.location, horizon_hours=request.horizon_hours
        )

        if forecast_weather_df.empty:
            # Generate synthetic future timestamps with fallback weather if API returns empty
            last_dt = pd.to_datetime(history_df[DATETIME_COL].max())
            future_dts = [
                last_dt + pd.Timedelta(hours=i) for i in range(1, request.horizon_hours + 1)
            ]
            forecast_weather_df = pd.DataFrame(
                {
                    DATETIME_COL: future_dts,
                    TEMPERATURE_COL: 28.0,
                    RELATIVE_HUMIDITY_COL: 75.0,
                }
            )

        # 3. Perform recursive multi-step forecasting
        pred_df = model_store.forecaster.predict_recursive(
            history_df=history_df,
            future_weather_df=forecast_weather_df,
            horizon_hours=request.horizon_hours,
        )

        items = [
            PredictionItem(
                datetime=str(row[DATETIME_COL]),
                predicted_load_mw=float(row["predicted_load_mw"]),
                temperature=float(row[TEMPERATURE_COL]),
                relative_humidity=float(row[RELATIVE_HUMIDITY_COL]),
            )
            for _, row in pred_df.iterrows()
        ]

        return PredictionResponse(
            status="success",
            horizon_hours=len(items),
            location=request.location,
            predictions=items,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction error: {e}") from e
