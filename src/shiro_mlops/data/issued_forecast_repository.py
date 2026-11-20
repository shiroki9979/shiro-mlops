"""Repository for issued forecasts: insert once per issue time, never update (ADR-0013)."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import MAX_HORIZON_HOURS
from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.data.forecast_track_record import TrackRecordWindow
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep, IssuedStep
from shiro_mlops.data.repository_utils import taiwan_instant_to_utc, utc_instant_to_taiwan

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
_SELECT_STEPS = text(
    """
    SELECT target_hour, predicted_load_mw
    FROM issued_forecast_step
    WHERE issued_at = :issued_at
    ORDER BY target_hour
    """
)

# 步數最遠落在負載起點後 168 小時，而負載起點早於發布時刻，
# 所以目標小時不早於窗起點的步數，其發布時刻必晚於窗起點 − 168h。
# 以此限定 hypertable 的分區欄位，查詢不必掃過整段歷史。
_SELECT_STEPS_AFTER_ISSUE = text(
    """
    SELECT issued_at, target_hour, predicted_load_mw
    FROM issued_forecast_step
    WHERE issued_at > :earliest_issued_at
      AND issued_at < :window_end
      AND target_hour >= :window_start
      AND target_hour < :window_end
      AND target_hour > issued_at
    ORDER BY target_hour, issued_at
    """
)
_HORIZON = timedelta(hours=MAX_HORIZON_HOURS)


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
        issued_at = taiwan_instant_to_utc(forecast.issued_at)
        header = {
            "issued_at": issued_at,
            "load_anchor": taiwan_instant_to_utc(forecast.load_anchor),
            "status": forecast.status,
            "model_sha256": forecast.model_sha256,
            "mlflow_model_version": forecast.mlflow_model_version,
        }
        steps = [
            {
                "issued_at": issued_at,
                "target_hour": taiwan_instant_to_utc(step.target_hour),
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
        params = {"issued_at": taiwan_instant_to_utc(issued_at)}
        with self.engine.connect() as conn:
            header = conn.execute(_SELECT_HEADER, params).mappings().first()
            if header is None:
                return None
            steps = conn.execute(_SELECT_STEPS, params).mappings().all()
        return IssuedForecast(
            issued_at=utc_instant_to_taiwan(header["issued_at"]),
            load_anchor=utc_instant_to_taiwan(header["load_anchor"]),
            status=header["status"],
            model_sha256=header["model_sha256"],
            mlflow_model_version=header["mlflow_model_version"],
            steps=tuple(
                IssuedForecastStep(
                    target_hour=utc_instant_to_taiwan(step["target_hour"]),
                    predicted_load_mw=float(step["predicted_load_mw"]),
                )
                for step in steps
            ),
        )

    def fetch_steps_after_issue(self, window: TrackRecordWindow) -> tuple[IssuedStep, ...]:
        """Steps targeting the window whose target hour is after their issue time.

        Each step comes with its Taiwan-local issue time, ordered by target hour
        then issue time.
        """
        params = {
            "earliest_issued_at": taiwan_instant_to_utc(window.start - _HORIZON),
            "window_start": taiwan_instant_to_utc(window.start),
            "window_end": taiwan_instant_to_utc(window.end),
        }
        with self.engine.connect() as conn:
            rows = conn.execute(_SELECT_STEPS_AFTER_ISSUE, params).mappings().all()
        return tuple(
            IssuedStep(
                issued_at=utc_instant_to_taiwan(row["issued_at"]),
                step=IssuedForecastStep(
                    target_hour=utc_instant_to_taiwan(row["target_hour"]),
                    predicted_load_mw=float(row["predicted_load_mw"]),
                ),
            )
            for row in rows
        )
