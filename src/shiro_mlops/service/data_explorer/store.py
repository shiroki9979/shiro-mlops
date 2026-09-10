"""Read persisted canonical datasets for Data Explorer without raw payloads."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.service.data_explorer.completeness import (
    NATIONAL_SNAPSHOT_TABLE,
    hourly_gaps,
    missing_regional_identifiers,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.schemas import DatasetStatus, ListEnvelope, StatusResponse
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan, to_sql_utc
from shiro_mlops.service.data_explorer.values import json_list, to_taiwan
from shiro_mlops.service.data_explorer.weather import (
    ForecastAuditReader,
    ForecastReader,
    ObservationAuditReader,
    ObservationReader,
)

FORECAST_SERVING_STALE = timedelta(hours=7)


class DataExplorerStore:
    """Query TimescaleDB canonical tables for the Data Explorer HTTP surface."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._db = ExplorerDb(engine)

    def list_hourly_load(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted hourly load rows newest first."""
        return HourlyLoadReader(self.engine).list(params)

    def list_national_supply_demand(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted national supply-demand snapshots newest first."""
        return NationalSupplyDemandReader(self.engine).list(params)

    def list_regional_supply_demand(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted regional snapshots newest first."""
        return RegionalSupplyDemandReader(self.engine).list(params)

    def list_unit_generation(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted unit-generation snapshots newest first."""
        return UnitGenerationReader(self.engine).list(params)

    def list_observations(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted CWA station observations newest first."""
        return ObservationReader(self.engine).list(params)

    def list_forecasts(self, params: dict[str, Any]) -> ListEnvelope:
        """List persisted CWA township forecasts newest first."""
        return ForecastReader(self.engine).list(params)

    def list_observation_audits(self, params: dict[str, Any]) -> ListEnvelope:
        """List CWA observation batch audit headers without raw payloads."""
        return ObservationAuditReader(self.engine).list(params)

    def list_forecast_audits(self, params: dict[str, Any]) -> ListEnvelope:
        """List CWA forecast release audit headers without raw payloads."""
        return ForecastAuditReader(self.engine).list(params)

    def status(self, as_of: datetime | None = None) -> StatusResponse:
        """Compute independent status dimensions for every v1 dataset."""
        clock = as_of or now_taiwan()
        try:
            return self._status(clock)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def _status(self, clock: datetime) -> StatusResponse:
        builders = (
            self._status_hourly_load,
            self._status_national,
            self._status_regional,
            self._status_units,
            self._status_observations,
            self._status_forecasts,
            self._status_observation_audits,
            self._status_forecast_audits,
        )
        return StatusResponse(datasets=[builder(clock) for builder in builders])

    def _status_hourly_load(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT time AS source_at, created_at AS ingested_at FROM raw_taipower_load "
            "ORDER BY time DESC LIMIT 1"
        )
        window = TimeWindow(as_of - timedelta(hours=24), as_of)
        missing = hourly_gaps(self._db, window, None) if latest else []
        return self._build_status("hourly_load", as_of, latest, missing)

    def _status_national(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            latest_source = to_taiwan(latest["source_at"])
            earliest = self._latest_row(
                "SELECT MIN(observed_at) AS source_at "
                "FROM raw_taipower_supply_demand_snapshot "
                "WHERE observed_at >= :start_time AND observed_at <= :end_time",
                {
                    "start_time": to_sql_utc(latest_source - timedelta(hours=24)),
                    "end_time": to_sql_utc(latest_source),
                },
            )
            if earliest and earliest["source_at"] is not None:
                window = TimeWindow(to_taiwan(earliest["source_at"]), latest_source)
                missing = ten_minute_gaps(self._db, NATIONAL_SNAPSHOT_TABLE, window)
        return self._build_status("national_supply_demand", as_of, latest, missing)

    def _status_regional(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_regional_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            slot = to_taiwan(latest["source_at"])
            present = regional_slot_map(self._db, TimeWindow(slot, slot)).get(slot, set())
            missing = missing_regional_identifiers(present)
        status = self._build_status("regional_supply_demand", as_of, latest, missing)
        if missing:
            status.href = "/data/power/regional?completeness=incomplete"
        return status

    def _status_units(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_unit_generation_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        count = self._scalar(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot "
            "WHERE observed_at = (SELECT MAX(observed_at) FROM raw_taipower_unit_generation_snapshot)"
        )
        status = self._build_status("unit_generation", as_of, latest, [])
        status.record_count = int(count or 0) if latest else 0
        if latest:
            status.completeness = "complete"
            status.overall = derive_overall(status.availability, status.freshness, "complete")
        return status

    def _status_observations(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_station_observation ORDER BY observed_at DESC LIMIT 1"
        )
        audit = self._latest_observation_audit()
        missing = list(audit["missing_station_ids"]) if audit else []
        if audit and audit["status"] == "incomplete" and not missing:
            missing = ["incomplete_batch"]
        status = self._build_status("cwa_observations", as_of, latest, missing)
        return status

    def _status_forecasts(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT issued_at AS source_at, fetched_at AS ingested_at "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        audit = self._latest_forecast_audit()
        missing = list(audit["missing_geocodes"]) if audit else []
        if audit and audit["status"] == "incomplete" and not missing:
            missing = ["incomplete_release"]
        status = self._build_status("cwa_forecasts", as_of, latest, missing)
        if latest:
            source_at = to_taiwan(latest["source_at"])
            status.serving_stale = (as_of - source_at) > FORECAST_SERVING_STALE
        return status

    def _status_observation_audits(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT fetched_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_observation_batch ORDER BY fetched_at DESC LIMIT 1"
        )
        audit = self._latest_observation_audit()
        missing = list(audit["missing_station_ids"]) if audit else []
        return self._build_status("cwa_observation_audits", as_of, latest, missing)

    def _status_forecast_audits(self, as_of: datetime) -> DatasetStatus:
        latest = self._latest_row(
            "SELECT issued_at AS source_at, fetched_at AS ingested_at "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        audit = self._latest_forecast_audit()
        missing = list(audit["missing_geocodes"]) if audit else []
        return self._build_status("cwa_forecast_audits", as_of, latest, missing)

    def _build_status(
        self,
        dataset_id: str,
        as_of: datetime,
        latest: dict[str, Any] | None,
        missing: list[str],
    ) -> DatasetStatus:
        spec = DATASET_SPECS[dataset_id]
        if latest is None:
            freshness = evaluate_freshness(
                cadence_seconds=spec["cadence"],
                as_of=as_of,
                latest_source_at=None,
                latest_ingested_at=None,
            )
            return DatasetStatus(
                id=dataset_id,
                label=spec["label"],
                availability="empty",
                freshness=freshness.state,
                completeness="unknown",
                overall=derive_overall("empty", freshness.state, "unknown"),
                href=spec["href"],
            )
        source_at = to_taiwan(latest["source_at"])
        ingested_at = to_taiwan(latest["ingested_at"])
        freshness = evaluate_freshness(
            cadence_seconds=spec["cadence"],
            as_of=as_of,
            latest_source_at=source_at,
            latest_ingested_at=ingested_at,
        )
        completeness = "incomplete" if missing else "complete"
        return DatasetStatus(
            id=dataset_id,
            label=spec["label"],
            availability="available",
            freshness=freshness.state,
            completeness=completeness,
            overall=derive_overall("available", freshness.state, completeness),
            latest_source_at=format_taiwan_time(source_at),
            latest_ingested_at=format_taiwan_time(ingested_at),
            ingestion_age_seconds=freshness.ingestion_age_seconds,
            source_age_seconds=freshness.source_age_seconds,
            missing_identifiers=missing,
            missing_slot_count=len(missing),
            href=spec["href"],
        )

    def _latest_observation_audit(self) -> dict[str, Any] | None:
        row = self._latest_row(
            "SELECT fetched_at, status, missing_station_ids FROM raw_cwa_observation_batch "
            "ORDER BY fetched_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            "fetched_at": to_taiwan(row["fetched_at"]),
            "status": row["status"],
            "missing_station_ids": [str(item) for item in json_list(row["missing_station_ids"])],
        }

    def _latest_forecast_audit(self) -> dict[str, Any] | None:
        row = self._latest_row(
            "SELECT dataset_id, issued_at, fetched_at, status, missing_geocodes "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            "status": row["status"],
            "missing_geocodes": [str(item) for item in json_list(row["missing_geocodes"])],
        }

    def _fetch(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self._db.fetch(query, params)

    def _latest_row(
        self, query: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return self._db.latest_row(query, params)

    def _scalar(self, query: str) -> Any:
        return self._db.scalar(query)
