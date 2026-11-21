"""CWA audit status timelines: batch and version counts per status on the series seam."""

from __future__ import annotations

from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec
from shiro_mlops.service.data_explorer.weather import (
    forecast_audit_filters,
    observation_audit_filters,
)

AUDIT_COUNT_UNIT = "count"

OBSERVATION_AUDIT_SERIES = SeriesSpec(
    dataset="cwa_observation_audits",
    table="raw_cwa_observation_batch",
    time_column="fetched_at",
    fields={"batch_count": SeriesField(sql="1", unit=AUDIT_COUNT_UNIT)},
    group_columns=("status",),
    filter_keys=frozenset({"status", "missing_station_id"}),
    filters=observation_audit_filters,
    gap_fill=False,
    count_rows=True,
)

FORECAST_AUDIT_SERIES = SeriesSpec(
    dataset="cwa_forecast_audits",
    table="raw_cwa_forecast_release",
    time_column="issued_at",
    fields={"version_count": SeriesField(sql="1", unit=AUDIT_COUNT_UNIT)},
    group_columns=("status",),
    filter_keys=frozenset({"dataset_id", "status", "missing_geocode"}),
    filters=forecast_audit_filters,
    gap_fill=False,
    count_rows=True,
)
