"""Repository for issued forecasts: insert once per issue time, never update (ADR-0013)."""

import logging
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.storage_time import from_storage_time, to_storage_time
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep

logger = logging.getLogger(__name__)

_INSERT_HEADER = text(
    """
    INSERT INTO issued_forecast (
        issued_at, load_anchor, status, model_sha256, mlflow_model_version
    ) VALUES (
        :issued_at, :load_anchor, :status, :model_sha256, :mlflow_model_version
    )
    ON CONFLICT (issued_at) DO NOTHING
    """
)
_INSERT_STEP = text(
    """
    INSERT INTO issued_forecast_step (issued_at, target_hour, predicted_load_mw)
    VALUES (:issued_at, :target_hour, :predicted_load_mw)
    """
)
_SELECT_HEADER = text(
    """
    SELECT issued_at, load_anchor, status, model_sha256, mlflow_model_version
    FROM issued_forecast
    WHERE issued_at = :issued_at
    """
)
_SELECT_LATEST_ISSUED_AT = text(
    """
    SELECT issued_at
    FROM issued_forecast
    ORDER BY issued_at DESC
    LIMIT 1
    """
)
_SELECT_STEPS = text(
    """
    SELECT target_hour, predicted_load_mw
    FROM issued_forecast_step
    WHERE issued_at = :issued_at
    ORDER BY target_hour
    """
)


class IssuedForecastRepository:
    """Persist issued forecasts as a header keyed by issue time plus its steps.

    There is deliberately no update path: an issue time is written at most once.
    """

    def __init__(self, engine: Engine | None = None, auto_init: bool = True) -> None:
        self.engine = engine if engine is not None else get_timescale_engine()
        if auto_init:
            ensure_timescale_hypertables(self.engine)

    def insert(self, forecast: IssuedForecast) -> bool:
        """Write the header and steps in one transaction.

        Returns ``False`` without touching anything when the issue time already
        exists, so a retried or concurrent run never overwrites the first record.
        """
        issued_at = to_storage_time(forecast.issued_at)
        header = {
            "issued_at": issued_at,
            "load_anchor": to_storage_time(forecast.load_anchor),
            "status": forecast.status,
            "model_sha256": forecast.model_sha256,
            "mlflow_model_version": forecast.mlflow_model_version,
        }
        steps = [
            {
                "issued_at": issued_at,
                "target_hour": to_storage_time(step.target_hour),
                "predicted_load_mw": float(step.predicted_load_mw),
            }
            for step in forecast.steps
        ]
        with self.engine.begin() as conn:
            if conn.execute(_INSERT_HEADER, header).rowcount == 0:
                logger.info("Forecast already issued at %s", forecast.issued_at.isoformat())
                return False
            if steps:
                conn.execute(_INSERT_STEP, steps)
        logger.info(
            "Issued forecast at %s with %d steps", forecast.issued_at.isoformat(), len(steps)
        )
        return True

    def fetch(self, issued_at: datetime) -> IssuedForecast | None:
        """Read the forecast issued at a Taiwan-local issue time, or ``None``."""
        params = {"issued_at": to_storage_time(issued_at)}
        with self.engine.connect() as conn:
            header = conn.execute(_SELECT_HEADER, params).mappings().first()
            if header is None:
                return None
            steps = conn.execute(_SELECT_STEPS, params).mappings().all()
        return IssuedForecast(
            issued_at=from_storage_time(header["issued_at"], column="issued_at"),
            load_anchor=from_storage_time(header["load_anchor"], column="load_anchor"),
            status=header["status"],
            model_sha256=header["model_sha256"],
            mlflow_model_version=header["mlflow_model_version"],
            steps=tuple(
                IssuedForecastStep(
                    target_hour=from_storage_time(step["target_hour"], column="target_hour"),
                    predicted_load_mw=float(step["predicted_load_mw"]),
                )
                for step in steps
            ),
        )

    def fetch_latest(self) -> IssuedForecast | None:
        """Read the forecast with the latest issue time, or ``None`` before the first issue."""
        with self.engine.connect() as conn:
            latest = conn.execute(_SELECT_LATEST_ISSUED_AT).scalar()
        if latest is None:
            return None
        return self.fetch(from_storage_time(latest, column="issued_at"))
