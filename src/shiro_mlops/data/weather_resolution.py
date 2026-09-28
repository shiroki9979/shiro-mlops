"""Point-in-time CWA forecast projection and degraded weather resolution."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

from shiro_mlops.core.constants import (
    DATETIME_COL,
    LOCATION_COL,
    RELATIVE_HUMIDITY_COL,
    TEMPERATURE_COL,
)
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.cwa_client import CWALocation

FORECAST_FIELDS = {
    TEMPERATURE_COL: "temperature_c",
    RELATIVE_HUMIDITY_COL: "relative_humidity_pct",
    "dew_point": "dew_point_c",
    "apparent_temperature": "apparent_temperature_c",
    "probability_of_precipitation": "probability_of_precipitation_pct",
    "wind_speed": "wind_speed_m_s",
    "wind_direction": "wind_direction",
}
DEFAULT_RESOLUTION_FIELDS = (TEMPERATURE_COL, RELATIVE_HUMIDITY_COL)
NON_INTERPOLATED_FORECAST_FIELDS = {"wind_direction"}
WeatherResolutionMode = Literal["normal", "degraded", "unavailable"]


@dataclass(frozen=True)
class WeatherResolution:
    """Hourly weather values and their per-field provenance."""

    dataframe: pd.DataFrame
    sources: tuple[dict[str, dict[str, str]], ...]
    mode: WeatherResolutionMode
    reason: str | None = None


def _as_timestamp(value: datetime | str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(TAIWAN_TZ).tz_localize(None)
    return timestamp


def _row_covers(row: pd.Series, moment: pd.Timestamp) -> bool:
    start = _as_timestamp(row["valid_from"])
    end = _as_timestamp(row["valid_to"])
    return start == end and moment == start or start <= moment < end


def _latest_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    for column in ("issued_at", "source_updated_at", "valid_from", "valid_to"):
        result[column] = result[column].map(_as_timestamp)
    keys = ["dataset_id", "valid_from", "valid_to", "geocode"]
    return (
        result.sort_values([*keys, "issued_at", "source_updated_at"])
        .drop_duplicates(keys, keep="last")
        .reset_index(drop=True)
    )


def _point_value(
    frame: pd.DataFrame, moment: pd.Timestamp, column: str
) -> tuple[object, pd.Series | None]:
    if frame.empty or column not in frame.columns:
        return None, None
    points = frame[frame["valid_from"] == frame["valid_to"]].sort_values("valid_from")
    if points.empty:
        return None, None
    exact = points[points["valid_from"] == moment]
    if not exact.empty:
        row = exact.iloc[-1]
        return (row[column], row) if pd.notna(row[column]) else (None, None)
    if column in NON_INTERPOLATED_FORECAST_FIELDS:
        return None, None
    before = points[points["valid_from"] < moment].tail(1)
    after = points[points["valid_from"] > moment].head(1)
    if before.empty or after.empty:
        return None, None
    left, right = before.iloc[0], after.iloc[0]
    if pd.isna(left[column]) or pd.isna(right[column]):
        return None, None
    span = (right["valid_from"] - left["valid_from"]).total_seconds()
    ratio = (moment - left["valid_from"]).total_seconds() / span
    return float(left[column]) + (float(right[column]) - float(left[column])) * ratio, right


def _interval_value(
    frame: pd.DataFrame, moment: pd.Timestamp, column: str
) -> tuple[object, pd.Series | None]:
    if frame.empty or column not in frame.columns:
        return None, None
    candidates = frame[frame.apply(lambda row: _row_covers(row, moment), axis=1)]
    candidates = candidates[candidates[column].notna()]
    if candidates.empty:
        return None, None
    return candidates.iloc[-1][column], candidates.iloc[-1]


def _source(row: pd.Series | None, source: str) -> dict[str, str]:
    result = {"source": source}
    if row is not None:
        result.update(
            {
                "dataset_id": str(row["dataset_id"]),
                "issued_at": _as_timestamp(row["issued_at"]).isoformat(),
                "source_updated_at": _as_timestamp(row["source_updated_at"]).isoformat(),
            }
        )
    return result


def _fallback_from_observations(
    observations: pd.DataFrame, moment: pd.Timestamp, column: str
) -> tuple[object, str | None]:
    if observations.empty:
        return None, None
    work = observations.copy()
    if "observed_at" not in work.columns and "datetime" in work.columns:
        work = work.rename(columns={"datetime": "observed_at"})
    if column not in work.columns:
        column = {"temperature_c": "temperature", "relative_humidity_pct": "relative_humidity"}.get(
            column, column
        )
    if "observed_at" not in work.columns or column not in work.columns:
        return None, None
    work["observed_at"] = work["observed_at"].map(_as_timestamp)
    previous = work[work["observed_at"] == moment - timedelta(days=1)]
    if not previous.empty and pd.notna(previous.iloc[-1].get(column)):
        return previous.iloc[-1][column], "previous_day_observation"
    same = work[
        (work["observed_at"].dt.month == moment.month)
        & (work["observed_at"].dt.hour == moment.hour)
    ]
    same = same[same[column].notna()]
    if same["observed_at"].dt.date.nunique() < 7:
        return None, None
    return float(same[column].mean()), "climatology"


def resolve_weather(
    repository: object,
    *,
    reference_point: CWALocation,
    start_time: datetime | str | pd.Timestamp,
    horizon_hours: int,
    as_of: datetime | str | pd.Timestamp | None = None,
    fields: tuple[str, ...] = DEFAULT_RESOLUTION_FIELDS,
) -> WeatherResolution:
    """Resolve forecast and degraded weather of one weather reference point for a horizon.

    The township forecast area and fallback station both come from the reference
    point, so the prediction subject never decides where weather is read.
    """
    start = _as_timestamp(start_time)
    cutoff = _as_timestamp(as_of or start)
    moments = [start + timedelta(hours=index) for index in range(horizon_hours)]
    end = moments[-1] if moments else start
    forecasts = _latest_rows(
        repository.fetch_cwa_forecast_rows(
            geocode=reference_point.geocode,
            issued_before=cutoff,
            source_updated_before=cutoff,
            valid_start=start,
            valid_end=end,
            include_adjacent_points=True,
        )
    )
    observations = repository.fetch_cwa_station_observations(
        start_time=start - timedelta(days=366),
        end_time=cutoff,
        station_id=reference_point.station_id,
    )
    issued = forecasts["issued_at"].max() if not forecasts.empty else None
    stale = issued is None or cutoff - issued > timedelta(hours=7)
    datasets = {
        dataset_id: (
            forecasts[forecasts["dataset_id"] == dataset_id]
            if "dataset_id" in forecasts.columns
            else pd.DataFrame()
        )
        for dataset_id in ("F-D0047-089", "F-D0047-091")
    }
    rows: list[dict[str, object]] = []
    sources: list[dict[str, dict[str, str]]] = []
    degraded = False
    for moment in moments:
        output: dict[str, object] = {DATETIME_COL: moment, LOCATION_COL: reference_point.alias}
        point_sources: dict[str, dict[str, str]] = {}
        for output_name in fields:
            source_column = FORECAST_FIELDS[output_name]
            value: object = None
            source_row: pd.Series | None = None
            source_kind: str | None = None
            if not stale:
                value, source_row = _point_value(datasets["F-D0047-089"], moment, source_column)
                if value is not None:
                    source_kind = "three_day"
                else:
                    value, source_row = _interval_value(
                        datasets["F-D0047-091"], moment, source_column
                    )
                    if value is not None:
                        source_kind = "weekly"
            if value is None:
                value, fallback_kind = _fallback_from_observations(
                    observations,
                    moment,
                    source_column,
                )
                source_kind = fallback_kind
                degraded = True
            if value is None:
                return WeatherResolution(
                    dataframe=pd.DataFrame(),
                    sources=tuple(sources),
                    mode="unavailable",
                    reason=f"No weather coverage for {moment.isoformat()} {output_name}",
                )
            output[output_name] = value
            point_sources[output_name] = _source(source_row, source_kind or "unknown")
        rows.append(output)
        sources.append(point_sources)
    return WeatherResolution(
        pd.DataFrame(rows), tuple(sources), "degraded" if degraded else "normal"
    )
