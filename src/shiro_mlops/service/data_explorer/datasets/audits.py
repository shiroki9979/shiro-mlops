"""CWA audit datasets: observation batch and forecast release headers, without raw payloads.

Each audit dataset reads its header table through a derived relation whose `status` is
judged from the header's missing list, so list items, the `status` filter and the series
grouping agree with `GET /data/status` and never read a stored status.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from shiro_mlops.data.cwa_client import (
    CWA_INGESTION_COMPLETE,
    CWA_INGESTION_INCOMPLETE,
    CWA_INGESTION_STATUSES,
)
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
OBSERVATION_BATCH_TABLE = "raw_cwa_observation_batch"
FORECAST_RELEASE_TABLE = "raw_cwa_forecast_release"
FORECAST_RELEASE_ORDER = ("issued_at", "source_updated_at", "dataset_id")

OBSERVATION_BATCH_AUDIT = AuditHeader(
    table=OBSERVATION_BATCH_TABLE,
    order=("fetched_at",),
    ids_column="missing_station_ids",
)
FORECAST_RELEASE_AUDIT = AuditHeader(
    table=FORECAST_RELEASE_TABLE,
    order=FORECAST_RELEASE_ORDER,
    ids_column="missing_geocodes",
)


# WHY-NOT(_derived_status): an array-length function is `json_array_length` on SQLite but
# `jsonb_array_length` on PostgreSQL; both render an empty JSON array as the text `[]`.
def _derived_status(ids_column: str) -> str:
    return (
        f"CASE WHEN CAST({ids_column} AS TEXT) = '[]' "
        f"THEN '{CWA_INGESTION_COMPLETE}' ELSE '{CWA_INGESTION_INCOMPLETE}' END"
    )


def _judged_headers(header: AuditHeader, columns: tuple[str, ...], alias: str) -> str:
    """The header table's `columns` plus `status` judged from its missing list."""
    selected = ", ".join([*columns, header.ids_column])
    return (
        f"(SELECT {selected}, {_derived_status(header.ids_column)} AS {AUDIT_STATUS_COLUMN} "
        f"FROM {header.table}) AS {alias}"
    )


OBSERVATION_BATCHES = _judged_headers(
    OBSERVATION_BATCH_AUDIT, ("fetched_at", "created_at"), "observation_batches"
)
FORECAST_RELEASE_HEADERS = _judged_headers(
    FORECAST_RELEASE_AUDIT,
    ("dataset_id", "issued_at", "source_updated_at", "fetched_at", "created_at"),
    "forecast_releases",
)
FORECAST_RELEASES = FreshnessSource(
    table=FORECAST_RELEASE_TABLE,
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
    table=OBSERVATION_BATCHES,
    time_column="fetched_at",
    sort=("fetched_at",),
    instant_columns=frozenset({"fetched_at"}),
    list_columns=("fetched_at", "status", "missing_station_ids", "created_at"),
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
    table=FORECAST_RELEASE_HEADERS,
    time_column="issued_at",
    sort=FORECAST_RELEASE_ORDER,
    instant_columns=frozenset({"issued_at", "source_updated_at"}),
    list_columns=(
        "dataset_id",
        "issued_at",
        "source_updated_at",
        "fetched_at",
        "status",
        "missing_geocodes",
        "created_at",
    ),
    project=each(_forecast_audit_item),
    status_policy=LatestAudit(FORECAST_RELEASE_AUDIT),
    freshness=FORECAST_RELEASES,
    filters=(
        Exact(name="dataset_id"),
        OneOf(name=AUDIT_STATUS_COLUMN, values=CWA_INGESTION_STATUSES),
        JsonContains(name="missing_geocode", column="missing_geocodes"),
    ),
    series=FORECAST_AUDIT_SERIES,
)
