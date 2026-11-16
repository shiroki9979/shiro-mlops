"""Weighted weather (GLOSSARY, ADR-0012): one value per field from every weather reference point.

The runner owns weighting as a shared component (ADR-0009), so task types keep
receiving a single ``datetime`` + weather fields frame. Each value is the weighted
sum over all reference points at the same hour; an hour any point lacks has no
weighted value, and a point with no forecast nor fallback makes the whole
resolution unavailable rather than being dropped and the rest reweighted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL
from shiro_mlops.data.weather_resolution import WeatherResolution, WeatherResolutionMode

# 每個預報小時：天氣欄位 → 氣象代表點別名 → 該點該欄位的來源。
PointSources = Mapping[str, Mapping[str, Mapping[str, str]]]


@dataclass(frozen=True)
class WeightedWeather:
    """Hourly weighted weather, each field's source at every reference point, and the mode."""

    dataframe: pd.DataFrame
    sources: tuple[PointSources, ...]
    mode: WeatherResolutionMode
    reason: str | None = None


@dataclass(frozen=True)
class PointWeather:
    """One reference point's contribution: its alias, weight and resolved or observed weather."""

    alias: str
    weight: float
    weather: pd.DataFrame


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
    points: Sequence[tuple[str, float, WeatherResolution]], fields: Sequence[str]
) -> WeightedWeather:
    """Combine per-point forecast resolutions over the same hours into weighted weather.

    Degraded at any point degrades the whole result; a point that cannot cover
    the horizon makes it unavailable, naming that point.
    """
    for alias, _, resolution in points:
        if resolution.mode == "unavailable" or resolution.dataframe.empty:
            reason = resolution.reason or "Weather coverage is unavailable."
            return WeightedWeather(pd.DataFrame(), (), "unavailable", f"{alias}: {reason}")
    first = points[0][2].dataframe
    combined = pd.DataFrame({DATETIME_COL: first[DATETIME_COL].to_numpy()})
    for field in fields:
        combined[field] = sum(
            weight * resolution.dataframe[field].astype(float).to_numpy()
            for _, weight, resolution in points
        )
    sources = tuple(
        {
            field: {alias: resolution.sources[hour][field] for alias, _, resolution in points}
            for field in fields
        }
        for hour in range(len(combined))
    )
    degraded = any(resolution.mode == "degraded" for _, _, resolution in points)
    return WeightedWeather(combined, sources, "degraded" if degraded else "normal")
