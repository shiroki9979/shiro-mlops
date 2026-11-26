"""CWA audit datasets: observation batch and forecast release headers, without raw payloads.

Each audit dataset reads its header table through a derived relation whose `status` is
judged from the header's missing list by the CWA ingestion rule's SQL form, so list
items, the `status` filter and the series grouping agree with `GET /data/status` and
never read a stored status.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from shiro_mlops.core.database import CWA_FORECAST_RELEASE_TABLE, CWA_OBSERVATION_BATCH_TABLE
from shiro_mlops.data.cwa_client import CWA_INGESTION_STATUSES, cwa_ingestion_status_sql
from shiro_mlops.service.data_explorer.datasets.definition import (
    AuditHeader,
    Dataset,
    Exact,
    FreshnessSource,
    JsonContains,
    LatestAudit,
    OneOf,
    Row,
    each,
)
from shiro_mlops.service.data_explorer.series import SeriesField, SeriesOptions
from shiro_mlops.service.data_explorer.values import format_row_time, json_list

AUDIT_STATUS_COLUMN = "status"
AUDIT_COUNT_UNIT = "count"
HOURLY = timedelta(hours=1)
FORECAST_RELEASE_ORDER = ("issued_at", "source_updated_at", "dataset_id")
FORECAST_RELEASE_INTERVAL = timedelta(hours=6)
"""How often CWA releases a township forecast version: a guess from the seven-hour stale rule.

The repository records no published release schedule; replace it once one is confirmed.
"""

OBSERVATION_BATCH_AUDIT = AuditHeader(
    table=CWA_OBSERVATION_BATCH_TABLE,
    order=("fetched_at",),
    ids_column="missing_station_ids",
)
FORECAST_RELEASE_AUDIT = AuditHeader(
    table=CWA_FORECAST_RELEASE_TABLE,
    order=FORECAST_RELEASE_ORDER,
    ids_column="missing_geocodes",
)
OBSERVATION_AUDIT_COLUMNS = ("fetched_at", AUDIT_STATUS_COLUMN, "missing_station_ids", "created_at")
FORECAST_AUDIT_COLUMNS = (
    "dataset_id",
    "issued_at",
    "source_updated_at",
    "fetched_at",
    AUDIT_STATUS_COLUMN,
    "missing_geocodes",
    "created_at",
)


def _judged_headers(header: AuditHeader, list_columns: tuple[str, ...], alias: str) -> str:
    """The header table's stored `list_columns`, with `status` judged from its missing list."""
    stored = ", ".join(column for column in list_columns if column != AUDIT_STATUS_COLUMN)
    status = cwa_ingestion_status_sql(header.ids_column)
    return f"(SELECT {stored}, {status} AS {AUDIT_STATUS_COLUMN} FROM {header.table}) AS {alias}"


OBSERVATION_BATCHES = _judged_headers(
    OBSERVATION_BATCH_AUDIT, OBSERVATION_AUDIT_COLUMNS, "observation_batches"
)
FORECAST_RELEASE_HEADERS = _judged_headers(
    FORECAST_RELEASE_AUDIT, FORECAST_AUDIT_COLUMNS, "forecast_releases"
)
FORECAST_RELEASES = FreshnessSource(
    relation=CWA_FORECAST_RELEASE_TABLE,
    source_column="issued_at",
    ingested_column="fetched_at",
    order=FORECAST_RELEASE_ORDER,
)


OBSERVATION_AUDIT_SERIES = SeriesOptions(
    fields={"batch_count": SeriesField(sql="1", unit=AUDIT_COUNT_UNIT)},
    group_columns=(AUDIT_STATUS_COLUMN,),
    gap_fill=False,
    count_rows=True,
)

FORECAST_AUDIT_SERIES = SeriesOptions(
    fields={"version_count": SeriesField(sql="1", unit=AUDIT_COUNT_UNIT)},
    group_columns=(AUDIT_STATUS_COLUMN,),
    gap_fill=False,
    count_rows=True,
)


def _observation_audit_item(row: Row) -> dict[str, Any]:
    return {
        "fetched_at": format_row_time(row, "fetched_at"),
        "status": row["status"],
        "missing_station_ids": [str(item) for item in json_list(row["missing_station_ids"])],
        "ingested_at": format_row_time(row, "created_at"),
    }


CWA_OBSERVATION_AUDITS = Dataset(
    id="cwa_observation_audits",
    label="CWA 觀測批次審計",
    href="/data/audits?type=observations",
    cadence=HOURLY,
    max_days=31,
    relation=OBSERVATION_BATCHES,
    time_column="fetched_at",
    sort=("fetched_at",),
    instant_columns=frozenset({"fetched_at"}),
    list_columns=OBSERVATION_AUDIT_COLUMNS,
    project=each(_observation_audit_item),
    status_policy=LatestAudit(OBSERVATION_BATCH_AUDIT),
    filters=(
        OneOf(name=AUDIT_STATUS_COLUMN, values=CWA_INGESTION_STATUSES),
        JsonContains(name="missing_station_id", column="missing_station_ids"),
    ),
    series=OBSERVATION_AUDIT_SERIES,
)


def _forecast_audit_item(row: Row) -> dict[str, Any]:
    return {
        "dataset_id": row["dataset_id"],
        "issued_at": format_row_time(row, "issued_at"),
        "source_updated_at": format_row_time(row, "source_updated_at"),
        "fetched_at": format_row_time(row, "fetched_at"),
        "status": row["status"],
        "missing_geocodes": [str(item) for item in json_list(row["missing_geocodes"])],
        "ingested_at": format_row_time(row, "created_at"),
    }


CWA_FORECAST_AUDITS = Dataset(
    id="cwa_forecast_audits",
    label="CWA 預報版本審計",
    href="/data/audits?type=forecasts",
    cadence=HOURLY,
    max_days=31,
    relation=FORECAST_RELEASE_HEADERS,
    time_column="issued_at",
    sort=FORECAST_RELEASE_ORDER,
    instant_columns=frozenset({"issued_at", "source_updated_at"}),
    list_columns=FORECAST_AUDIT_COLUMNS,
    project=each(_forecast_audit_item),
    status_policy=LatestAudit(FORECAST_RELEASE_AUDIT),
    freshness=FORECAST_RELEASES,
    update_interval=FORECAST_RELEASE_INTERVAL,
    filters=(
        Exact(name="dataset_id"),
        OneOf(name=AUDIT_STATUS_COLUMN, values=CWA_INGESTION_STATUSES),
        JsonContains(name="missing_geocode", column="missing_geocodes"),
    ),
    series=FORECAST_AUDIT_SERIES,
)
