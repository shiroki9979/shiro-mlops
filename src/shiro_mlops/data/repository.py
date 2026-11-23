"""Time-series database repository: one engine and schema init, handing out the data stores."""

from sqlalchemy.engine import Engine

from shiro_mlops.core.database import ensure_timescale_hypertables, get_timescale_engine
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore
from shiro_mlops.data.forecast_track_record import ForecastTrackRecordStore
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore
from shiro_mlops.data.issued_forecast_repository import IssuedForecastRepository
from shiro_mlops.data.taipower_regional_supply_demand_repository import (
    TaipowerRegionalSupplyDemandRepository,
)
from shiro_mlops.data.taipower_supply_demand_repository import (
    TaipowerSupplyDemandRepository,
)
from shiro_mlops.data.taipower_unit_generation_repository import (
    TaipowerUnitGenerationRepository,
)


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

        self.supply_demand_store = TaipowerSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.regional_supply_demand_store = TaipowerRegionalSupplyDemandRepository(
            engine=self.engine, auto_init=False
        )
        self.unit_generation_store = TaipowerUnitGenerationRepository(
            engine=self.engine, auto_init=False
        )
        self.issued_forecast_store = IssuedForecastRepository(engine=self.engine, auto_init=False)
        self.hourly_actual_load_store = HourlyActualLoadStore(self.engine)
        self.cwa_weather_store = CWAWeatherStore(self.engine)
        self.forecast_track_record_store = ForecastTrackRecordStore(self.engine)


__all__ = [
    "TimeSeriesRepository",
    "IssuedForecastRepository",
    "TaipowerSupplyDemandRepository",
    "TaipowerRegionalSupplyDemandRepository",
    "TaipowerUnitGenerationRepository",
]
