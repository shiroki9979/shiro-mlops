"""Weighted weather (GLOSSARY, ADR-0012): one value per field from every weather reference point.

The runner owns weighting as a shared component (ADR-0009), so task types keep
receiving a single ``datetime`` + weather fields frame. Each value is the weighted
sum over all reference points at the same hour; an hour any point lacks has no
weighted value. Forecast resolutions only exist complete: a point with no forecast
nor fallback is refused upstream, never dropped with the rest reweighted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL
from shiro_mlops.data.weather_resolution import (
    WeatherResolution,
    WeatherResolutionMode,
    WeatherValueSource,
)

PointSources = Mapping[str, Mapping[str, WeatherValueSource]]
SerializedPointSources = dict[str, dict[str, dict[str, str]]]


def serialize_point_sources(sources: PointSources) -> SerializedPointSources:
    """One hour's sources in the ``weather_sources`` JSON shape, field → alias → source."""
    return {
        field: {alias: source.as_dict() for alias, source in by_alias.items()}
        for field, by_alias in sources.items()
    }


@dataclass(frozen=True)
class WeightedWeather:
    """Hourly weighted weather, each field's source at every reference point, and the mode."""

    dataframe: pd.DataFrame
    sources: tuple[PointSources, ...]
    mode: WeatherResolutionMode


@dataclass(frozen=True)
class PointWeather:
    """One reference point's observations with its alias and weight."""

    alias: str
    weight: float
    weather: pd.DataFrame


@dataclass(frozen=True)
class PointResolution:
    """One reference point's forecast resolution with its alias and weight."""

    alias: str
    weight: float
    resolution: WeatherResolution


def weighted_observations(points: Sequence[PointWeather], fields: Sequence[str]) -> pd.DataFrame:
    """Weighted observations on the union of observed hours, as ``datetime`` + ``fields``.

    Points are matched on the exact observation hour; where any point lacks a
    field, that field has no weighted value, and task types apply their own
    rules for missing weather.
    """
    columns = list(fields)
    weighted: pd.DataFrame | None = None
    for point in points:
        values = (
            point.weather.drop_duplicates(DATETIME_COL, keep="last")
            .set_index(DATETIME_COL)[columns]
            .apply(pd.to_numeric, errors="coerce")
        )
        contribution = values * point.weight
        weighted = contribution if weighted is None else weighted + contribution
    if weighted is None or weighted.empty:
        return pd.DataFrame(columns=[DATETIME_COL, *columns])
    weighted = weighted.sort_index()
    weighted.index.name = DATETIME_COL
    return weighted.reset_index()


def weighted_resolution(
    points: Sequence[PointResolution], fields: Sequence[str]
) -> WeightedWeather:
    """Combine per-point forecast resolutions over the same hours into weighted weather.

    Degraded at any point degrades the whole result.
    """
    hours = pd.to_datetime(points[0].resolution.dataframe[DATETIME_COL]).to_numpy()
    for point in points[1:]:
        # 逐列相加前確認各點解析的是同一組小時，避免不同小時的值被靜默相加。
        if not (pd.to_datetime(point.resolution.dataframe[DATETIME_COL]).to_numpy() == hours).all():
            raise ValueError(f"{point.alias} resolved different hours than {points[0].alias}")
    combined = pd.DataFrame({DATETIME_COL: hours})
    for field in fields:
        combined[field] = sum(
            point.weight * point.resolution.dataframe[field].astype(float).to_numpy()
            for point in points
        )
    sources = tuple(
        {
            field: {point.alias: point.resolution.sources[hour][field] for point in points}
            for field in fields
        }
        for hour in range(len(combined))
    )
    degraded = any(point.resolution.mode == "degraded" for point in points)
    return WeightedWeather(combined, sources, "degraded" if degraded else "normal")
