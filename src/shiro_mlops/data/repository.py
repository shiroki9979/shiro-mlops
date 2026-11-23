"""Time-series database repository for issued forecasts and Taipower snapshots."""

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import MAX_HORIZON_HOURS, NATIONWIDE_SUBJECT
from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.core.storage_time import from_storage_time, half_open_window, to_storage_time
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.forecast_track_record import TrackRecordPair, TrackRecordWindow
from shiro_mlops.data.hourly_actual_load_store import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    HourlyActualLoadStore,
)
from shiro_mlops.data.issued_forecast import IssuedForecast
from shiro_mlops.data.issued_forecast_repository import IssuedForecastRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
)
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from shiro_mlops.data.taipower_supply_demand import TaipowerSupplyDemandSnapshot
from shiro_mlops.data.taipower_supply_demand_repository import (
    TaipowerSupplyDemandRepository,
)
from shiro_mlops.data.taipower_unit_generation import TaipowerUnitGenerationSnapshot
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)

_TRACK_RECORD_HORIZON = timedelta(hours=MAX_HORIZON_HOURS)


class TimeSeriesRepository:
    """Repository managing time-series persistence and queries for TimescaleDB."""

    def __init__(
        self,
        engine: Engine | None = None,
        uri: str | None = None,
        auto_init: bool = True,
    ) -> None:
        """Initialize repository with SQLAlchemy engine and ensure hypertables exist.

        Parameters
        ----------
        engine : Engine | None
            Optional pre-configured SQLAlchemy Engine.
        uri : str | None
            Optional database URI string.
        auto_init : bool
            Whether to ensure tables and hypertables exist on initialization. Defaults to True.
        """
        if engine is not None:
            self.engine = engine
        elif uri is not None:
            self.engine = get_timescale_engine(uri=uri)
        else:
            self.engine = get_timescale_engine()

        if auto_init:
            ensure_timescale_hypertables(self.engine)

        self.supply_demand_repo = TaipowerSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.regional_supply_demand_repo = TaipowerRegionalSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.unit_generation_repo = TaipowerUnitGenerationRepository(
            engine=self.engine, auto_init=False
        )
        self.issued_forecast_repo = IssuedForecastRepository(engine=self.engine, auto_init=False)
        self.hourly_actual_load_store = HourlyActualLoadStore(self.engine)
        self.cwa_weather_store = CWAWeatherStore(self.engine)

    def upsert_supply_demand_snapshot(self, snapshot: TaipowerSupplyDemandSnapshot) -> int:
        """Upsert a Taipower supply-demand snapshot keyed by observed_at."""
        return self.supply_demand_repo.upsert(snapshot)

    def fetch_supply_demand_snapshot(
        self, observed_at: datetime
    ) -> TaipowerSupplyDemandSnapshot | None:
        """Fetch a supply-demand snapshot by Taiwan-local observation slot."""
        return self.supply_demand_repo.fetch(observed_at)

    def upsert_regional_supply_demand_snapshots(
        self, snapshots: list[TaipowerRegionalSupplyDemandSnapshot]
    ) -> int:
        """Upsert regional supply-demand snapshots keyed by (observed_at, region)."""
        return self.regional_supply_demand_repo.upsert(snapshots)

    def fetch_regional_supply_demand_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots for a Taiwan-local observation slot."""
        return self.regional_supply_demand_repo.fetch(observed_at)

    def fetch_regional_supply_demand_snapshots_by_source_time(
        self, start_time: datetime, end_time: datetime
    ) -> list[TaipowerRegionalSupplyDemandSnapshot]:
        """Fetch regional snapshots whose Taiwan-local source_time is in [start, end)."""
        return self.regional_supply_demand_repo.fetch_by_source_time(start_time, end_time)

    def upsert_unit_generation_snapshots(
        self, snapshots: list[TaipowerUnitGenerationSnapshot]
    ) -> int:
        """Upsert unit net-generation snapshots keyed by identity and observed_at."""
        return self.unit_generation_repo.upsert(snapshots)

    def fetch_unit_generation_snapshots(
        self, observed_at: datetime
    ) -> list[TaipowerUnitGenerationSnapshot]:
        """Fetch unit net-generation snapshots for a Taiwan-local observation slot."""
        return self.unit_generation_repo.fetch(observed_at)

    def insert_issued_forecast(self, forecast: IssuedForecast) -> bool:
        """Write an issued forecast once; ``False`` when its issue time already exists."""
        return self.issued_forecast_repo.insert(forecast)

    def fetch_issued_forecast(self, issued_at: datetime) -> IssuedForecast | None:
        """Fetch the forecast issued at a Taiwan-local issue time."""
        return self.issued_forecast_repo.fetch(issued_at)

    def fetch_latest_issued_forecast(self) -> IssuedForecast | None:
        """Fetch the forecast with the latest issue time, or ``None`` before the first issue."""
        return self.issued_forecast_repo.fetch_latest()

    def fetch_track_record_pairs(self, window: TrackRecordWindow) -> tuple[TrackRecordPair, ...]:
        """Pair issued steps targeting the window with valid hourly observations.

        Only steps whose target hour is after their issue time count, and only
        target hours with a nationwide ``regional_snapshot_sum`` load row. One SQL
        join returns only the paired rows. Pairs are ordered by target hour, then
        issue time.

        Both hypertables are bounded on their partition column: a step lands at
        most 168 hours after its load anchor, which precedes its issue time, so a
        step targeting the window was issued after the window start minus 168 hours.
        """
        target_hour = half_open_window("step.target_hour", window.start, window.end)
        load_time = half_open_window("actual.time", window.start, window.end, param="load_time")
        params = {
            **target_hour.params,
            **load_time.params,
            "earliest_issued_at": to_storage_time(window.start - _TRACK_RECORD_HORIZON),
            "latest_issued_at": to_storage_time(window.end),
            "subject": NATIONWIDE_SUBJECT,
            "source": REGIONAL_SNAPSHOT_SUM_SOURCE,
        }
        query = text(
            f"""
            SELECT step.issued_at, step.target_hour, step.predicted_load_mw, actual.load_mw
            FROM issued_forecast_step AS step
            JOIN raw_taipower_load AS actual ON actual.time = step.target_hour
            WHERE step.issued_at > :earliest_issued_at
              AND step.issued_at < :latest_issued_at
              AND {target_hour.sql}
              AND step.target_hour > step.issued_at
              AND {load_time.sql}
              AND actual.subject = :subject
              AND actual.source = :source
            ORDER BY step.target_hour, step.issued_at
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(query, params).mappings().all()
        return tuple(
            TrackRecordPair(
                issued_at=from_storage_time(row["issued_at"], column="issued_at"),
                target_hour=from_storage_time(row["target_hour"], column="target_hour"),
                predicted_load_mw=float(row["predicted_load_mw"]),
                actual_load_mw=float(row["load_mw"]),
            )
            for row in rows
        )


__all__ = [
    "TimeSeriesRepository",
    "IssuedForecastRepository",
    "TaipowerSupplyDemandRepository",
    "TaipowerRegionalSupplyDemandRepository",
    "TaipowerUnitGenerationRepository",
]
