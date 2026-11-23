"""Point-in-time CWA forecast projection, degraded weather resolution and the forecast mode.

This module owns the one rule for 預報運行狀態 (GLOSSARY): a forecast is degraded
exactly when some value it used is a substitute, so callers derive the mode from
the sources and never store or recompute it themselves.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import NamedTuple, Self, TypeAlias

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
FORECAST_STALE_AFTER = timedelta(hours=7)


def forecast_is_stale(issued_at: datetime, as_of: datetime) -> bool:
    """Whether a forecast version issued at ``issued_at`` is too old to serve at ``as_of``."""
    return as_of - issued_at > FORECAST_STALE_AFTER


class ForecastMode(StrEnum):
    """預報運行狀態 (GLOSSARY): normal, or degraded when any value is a substitute."""

    NORMAL = "normal"
    DEGRADED = "degraded"


class WeatherSourceKind(StrEnum):
    """Where one weather value came from; a closed set, each kind known to substitute or not."""

    THREE_DAY = "three_day"
    WEEKLY = "weekly"
    PREVIOUS_DAY_OBSERVATION = "previous_day_observation"
    CLIMATOLOGY = "climatology"
    STATION_OBSERVATION = "station_observation"

    @property
    def is_substitute(self) -> bool:
        """Whether the value stands in for a missing forecast (GLOSSARY 降級預報).

        Station observations feed observed-weather tasks as the real input, not a
        substitute, so they never degrade.
        """
        return _KIND_SHAPES[self].is_substitute

    @property
    def fields(self) -> tuple[str, ...]:
        """The provenance fields a source of this kind carries, and no others."""
        return _KIND_SHAPES[self].fields


class _KindShape(NamedTuple):
    fields: tuple[str, ...]
    is_substitute: bool


_VERSION_FIELDS = ("dataset_id", "issued_at", "source_updated_at")
_OBSERVATION_FIELDS = ("observed_at",)
_OPTIONAL_FIELDS = (*_VERSION_FIELDS, *_OBSERVATION_FIELDS)
_KIND_SHAPES = {
    WeatherSourceKind.THREE_DAY: _KindShape(_VERSION_FIELDS, is_substitute=False),
    WeatherSourceKind.WEEKLY: _KindShape(_VERSION_FIELDS, is_substitute=False),
    WeatherSourceKind.PREVIOUS_DAY_OBSERVATION: _KindShape((), is_substitute=True),
    WeatherSourceKind.CLIMATOLOGY: _KindShape((), is_substitute=True),
    WeatherSourceKind.STATION_OBSERVATION: _KindShape(_OBSERVATION_FIELDS, is_substitute=False),
}
FORECAST_DATASET_KINDS = {
    "F-D0047-089": WeatherSourceKind.THREE_DAY,
    "F-D0047-091": WeatherSourceKind.WEEKLY,
}


@dataclass(frozen=True)
class WeatherValueSource:
    """The provenance of one weather value; only the fields its kind defines are set.

    Forecast kinds carry the forecast version that supplied the value, a station
    observation carries when it was observed, and substitutes carry nothing.
    """

    kind: WeatherSourceKind
    dataset_id: str | None = None
    issued_at: pd.Timestamp | None = None
    source_updated_at: pd.Timestamp | None = None
    observed_at: pd.Timestamp | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WeatherSourceKind):
            raise ValueError(f"Weather source kind must be a WeatherSourceKind: {self.kind!r}")
        required = self.kind.fields
        present = [name for name in _OPTIONAL_FIELDS if getattr(self, name) is not None]
        if present != list(required):
            raise ValueError(
                f"A {self.kind.value} source carries exactly {list(required)}, got {present}"
            )

    @classmethod
    def forecast(cls, kind: WeatherSourceKind, row: pd.Series) -> Self:
        """The forecast version in ``row`` that supplied a value of ``kind``."""
        return cls(
            kind,
            dataset_id=str(row["dataset_id"]),
            issued_at=_as_timestamp(row["issued_at"]),
            source_updated_at=_as_timestamp(row["source_updated_at"]),
        )

    @classmethod
    def substitute(cls, kind: WeatherSourceKind) -> Self:
        """A substitute value standing in for a missing forecast."""
        if not kind.is_substitute:
            raise ValueError(f"A {kind.value} source is not a substitute")
        return cls(kind)

    @classmethod
    def observed(cls, observed_at: pd.Timestamp) -> Self:
        """A station observation made at ``observed_at``."""
        return cls(WeatherSourceKind.STATION_OBSERVATION, observed_at=observed_at)

    def as_dict(self) -> dict[str, str]:
        """The ``weather_sources`` JSON of this value: ``source`` plus the kind's own fields."""
        result = {"source": self.kind.value}
        for name in _OPTIONAL_FIELDS:
            value = getattr(self, name)
            if value is not None:
                result[name] = value if isinstance(value, str) else value.isoformat()
        return result


SourceTree: TypeAlias = "WeatherValueSource | Mapping[str, SourceTree] | Iterable[SourceTree]"


def _leaves(sources: SourceTree) -> Iterable[WeatherValueSource]:
    if isinstance(sources, WeatherValueSource):
        yield sources
        return
    for nested in sources.values() if isinstance(sources, Mapping) else sources:
        yield from _leaves(nested)


def forecast_mode(sources: SourceTree) -> ForecastMode:
    """Degraded when any value came from a substitute, otherwise normal.

    ``sources`` may nest sources in sequences and mappings, such as hour → field
    → source or hour → field → reference point → source; every source counts.
    """
    if any(source.kind.is_substitute for source in _leaves(sources)):
        return ForecastMode.DEGRADED
    return ForecastMode.NORMAL


class WeatherCoverageError(Exception):
    """A weather reference point has neither a fresh forecast nor a substitute for some value."""


@dataclass(frozen=True)
class WeatherResolution:
    """Every hour's value of every field and its source; only exists when nothing is missing."""

    dataframe: pd.DataFrame
    sources: tuple[dict[str, WeatherValueSource], ...]

    @property
    def mode(self) -> ForecastMode:
        """The forecast mode these sources imply."""
        return forecast_mode(self.sources)


def _as_timestamp(value: datetime | str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert(TAIWAN_TZ).tz_localize(None)
    return timestamp


def _row_covers(row: pd.Series, moment: pd.Timestamp) -> bool:
    start = _as_timestamp(row["valid_from"])
    end = _as_timestamp(row["valid_to"])
    return start == end and moment == start or start <= moment < end


def _fresh_rows(frame: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    """Rows whose own forecast version was issued no more than seven hours before the cutoff."""
    if frame.empty:
        return frame
    result = frame.copy()
    for column in ("issued_at", "source_updated_at", "valid_from", "valid_to"):
        result[column] = result[column].map(_as_timestamp)
    stale = result["issued_at"].map(lambda issued_at: forecast_is_stale(issued_at, cutoff))
    return result.loc[~stale].reset_index(drop=True)


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


def _fallback_from_observations(
    observations: pd.DataFrame, moment: pd.Timestamp, column: str
) -> tuple[object, WeatherSourceKind | None]:
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
        return previous.iloc[-1][column], WeatherSourceKind.PREVIOUS_DAY_OBSERVATION
    same = work[
        (work["observed_at"].dt.month == moment.month)
        & (work["observed_at"].dt.hour == moment.hour)
    ]
    same = same[same[column].notna()]
    if same["observed_at"].dt.date.nunique() < 7:
        return None, None
    return float(same[column].mean()), WeatherSourceKind.CLIMATOLOGY


def _resolve_value(
    datasets: dict[WeatherSourceKind, pd.DataFrame],
    observations: pd.DataFrame,
    moment: pd.Timestamp,
    column: str,
) -> tuple[object, WeatherValueSource | None]:
    """One hour's value of ``column`` and its source, or no source when nothing covers it."""
    value, row = _point_value(datasets[WeatherSourceKind.THREE_DAY], moment, column)
    if value is not None:
        return value, WeatherValueSource.forecast(WeatherSourceKind.THREE_DAY, row)
    value, row = _interval_value(datasets[WeatherSourceKind.WEEKLY], moment, column)
    if value is not None:
        return value, WeatherValueSource.forecast(WeatherSourceKind.WEEKLY, row)
    value, substitute = _fallback_from_observations(observations, moment, column)
    if substitute is None:
        return None, None
    return value, WeatherValueSource.substitute(substitute)


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
    point, so the prediction subject never decides where weather is read. Each
    hour and field takes, in order, a fresh three-day value, a fresh weekly value,
    the previous-day observation, then climatology; freshness is judged by the
    forecast version that supplies the value. Only observation fills degrade.

    Raises ``WeatherCoverageError`` naming the reference point at the first value
    none of these covers, and ``ValueError`` when ``horizon_hours`` is below one.
    """
    if horizon_hours < 1:
        raise ValueError(f"horizon_hours must be at least 1, got {horizon_hours}")
    start = _as_timestamp(start_time)
    cutoff = _as_timestamp(as_of or start)
    moments = [start + timedelta(hours=index) for index in range(horizon_hours)]
    end = moments[-1]
    forecasts = _fresh_rows(
        repository.fetch_cwa_forecast_rows(
            geocode=reference_point.geocode,
            issued_before=cutoff,
            source_updated_before=cutoff,
            valid_start=start,
            valid_end=end,
            include_adjacent_points=True,
        ),
        cutoff,
    )
    observations = repository.fetch_cwa_station_observations(
        start_time=start - timedelta(days=366),
        end_time=cutoff,
        station_id=reference_point.station_id,
    )
    datasets = {
        kind: (
            forecasts[forecasts["dataset_id"] == dataset_id]
            if "dataset_id" in forecasts.columns
            else pd.DataFrame()
        )
        for dataset_id, kind in FORECAST_DATASET_KINDS.items()
    }
    rows: list[dict[str, object]] = []
    sources: list[dict[str, WeatherValueSource]] = []
    for moment in moments:
        output: dict[str, object] = {DATETIME_COL: moment, LOCATION_COL: reference_point.alias}
        point_sources: dict[str, WeatherValueSource] = {}
        for output_name in fields:
            value, source = _resolve_value(
                datasets, observations, moment, FORECAST_FIELDS[output_name]
            )
            if source is None:
                raise WeatherCoverageError(
                    f"{reference_point.alias}: No weather coverage for "
                    f"{moment.isoformat()} {output_name}"
                )
            output[output_name] = value
            point_sources[output_name] = source
        rows.append(output)
        sources.append(point_sources)
    return WeatherResolution(pd.DataFrame(rows), tuple(sources))
