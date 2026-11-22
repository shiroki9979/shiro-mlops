"""Compose dataset availability, freshness, and completeness for Data Explorer status."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.hourly_actual_load import (
    REGIONAL_SNAPSHOT_SUM_SOURCE,
    recent_completed_hours,
)
from shiro_mlops.data.weather_resolution import forecast_is_stale
from shiro_mlops.service.data_explorer.completeness import (
    audit_missing_identifiers,
    hourly_gaps,
    missing_regional_identifiers,
    regional_slot_map,
    ten_minute_gaps,
)
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError
from shiro_mlops.service.data_explorer.query import TimeWindow
from shiro_mlops.service.data_explorer.schemas import DatasetStatus, StatusResponse
from shiro_mlops.service.data_explorer.specs import DATASET_SPECS
from shiro_mlops.service.data_explorer.status import derive_overall, evaluate_freshness
from shiro_mlops.service.data_explorer.timefmt import format_taiwan_time, now_taiwan
from shiro_mlops.service.data_explorer.values import json_list, row_time


def compose_dataset_status(
    dataset_id: str,
    as_of: datetime,
    latest: dict[str, Any] | None,
    missing: list[str],
) -> DatasetStatus:
    """Compose independent status dimensions for one dataset without changing the contract."""
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
    source_at = row_time(latest, "source_at")
    ingested_at = row_time(latest, "ingested_at")
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


class DatasetStatusCatalog:
    """Aggregate per-dataset status collaborators for GET /data/status."""

    def __init__(self, engine: Engine) -> None:
        self.db = ExplorerDb(engine)

    def status(self, as_of: datetime | None = None) -> StatusResponse:
        """Compute independent status dimensions for every v1 dataset."""
        clock = as_of or now_taiwan()
        try:
            forecasts, forecast_audits = self._forecast_statuses(clock)
            return StatusResponse(
                datasets=[
                    self._hourly_load(clock),
                    self._national(clock),
                    self._regional(clock),
                    self._units(clock),
                    self._observations(clock),
                    forecasts,
                    self._observation_audits(clock),
                    forecast_audits,
                ]
            )
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(str(exc)) from exc

    def _hourly_load(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT time AS source_at, created_at AS ingested_at FROM raw_taipower_load "
            "WHERE source = :source ORDER BY time DESC LIMIT 1",
            {"source": REGIONAL_SNAPSHOT_SUM_SOURCE},
        )
        completed = recent_completed_hours(as_of, 24)
        window = TimeWindow(completed.start, completed.end - timedelta(hours=1))
        missing = hourly_gaps(self.db, window, None) if latest else []
        return compose_dataset_status("hourly_load", as_of, latest, missing)

    def _national(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            latest_source = row_time(latest, "source_at")
            clauses, params = self.db.time_window(
                "observed_at", TimeWindow(latest_source - timedelta(hours=24), latest_source)
            )
            earliest = self.db.fetch_one(
                "SELECT MIN(observed_at) AS source_at "
                f"FROM raw_taipower_supply_demand_snapshot WHERE {' AND '.join(clauses)}",
                params,
            )
            if earliest and earliest["source_at"] is not None:
                window = TimeWindow(row_time(earliest, "source_at"), latest_source)
                missing = ten_minute_gaps(self.db, window)
        return compose_dataset_status("national_supply_demand", as_of, latest, missing)

    def _regional(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_regional_supply_demand_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        missing: list[str] = []
        if latest:
            slot = row_time(latest, "source_at")
            present = regional_slot_map(self.db, TimeWindow(slot, slot)).get(slot, set())
            missing = missing_regional_identifiers(present)
        status = compose_dataset_status("regional_supply_demand", as_of, latest, missing)
        if missing:
            status.href = "/data/power/regional?completeness=incomplete"
        return status

    def _units(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_taipower_unit_generation_snapshot ORDER BY observed_at DESC LIMIT 1"
        )
        count = self.db.scalar(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot "
            "WHERE observed_at = (SELECT MAX(observed_at) FROM raw_taipower_unit_generation_snapshot)"
        )
        status = compose_dataset_status("unit_generation", as_of, latest, [])
        status.record_count = int(count or 0) if latest else 0
        if latest:
            status.completeness = "complete"
            status.overall = derive_overall(status.availability, status.freshness, "complete")
        return status

    def _observations(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT observed_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_station_observation ORDER BY observed_at DESC LIMIT 1"
        )
        missing = audit_missing_identifiers(
            self._latest_observation_audit(),
            "missing_station_ids",
            incomplete_placeholder="incomplete_batch",
        )
        return compose_dataset_status("cwa_observations", as_of, latest, missing)

    def _forecast_statuses(self, as_of: datetime) -> tuple[DatasetStatus, DatasetStatus]:
        latest = self.db.fetch_one(
            "SELECT issued_at AS source_at, fetched_at AS ingested_at, status, missing_geocodes "
            "FROM raw_cwa_forecast_release ORDER BY issued_at DESC, source_updated_at DESC LIMIT 1"
        )
        if latest:
            latest["missing_geocodes"] = json_list(latest["missing_geocodes"])
        missing = audit_missing_identifiers(
            latest,
            "missing_geocodes",
            incomplete_placeholder="incomplete_release",
        )
        forecasts = compose_dataset_status("cwa_forecasts", as_of, latest, missing)
        audits = compose_dataset_status("cwa_forecast_audits", as_of, latest, missing)
        if latest:
            source_at = row_time(latest, "source_at")
            # Dataset-level hint only; per-request degradation is judged per supplied value.
            forecasts.latest_release_stale = forecast_is_stale(source_at, as_of)
        return forecasts, audits

    def _observation_audits(self, as_of: datetime) -> DatasetStatus:
        latest = self.db.fetch_one(
            "SELECT fetched_at AS source_at, created_at AS ingested_at "
            "FROM raw_cwa_observation_batch ORDER BY fetched_at DESC LIMIT 1"
        )
        missing = audit_missing_identifiers(
            self._latest_observation_audit(),
            "missing_station_ids",
            incomplete_placeholder="incomplete_batch",
        )
        return compose_dataset_status("cwa_observation_audits", as_of, latest, missing)

    def _latest_observation_audit(self) -> dict[str, Any] | None:
        row = self.db.fetch_one(
            "SELECT fetched_at, status, missing_station_ids FROM raw_cwa_observation_batch "
            "ORDER BY fetched_at DESC LIMIT 1"
        )
        if row is None:
            return None
        return {
            "fetched_at": row_time(row, "fetched_at"),
            "status": row["status"],
            "missing_station_ids": [str(item) for item in json_list(row["missing_station_ids"])],
        }
