"""Prediction input gate: the one place that decides whether a load anchor's inputs can predict.

Serving (the runner) and the rolling-origin backtest (``lab``) each acquire their
own frames, then hand them here; the gate returns the ``PredictionData`` a task
type may trust or refuses with a typed reason. It reads no database and does
not know the request time, so the stale load anchor rule stays with whoever
picks the anchor (docs/reference/ml-tasks.md §2).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import pandas as pd

from shiro_mlops.core.constants import DATETIME_COL, LOAD_MW_COL
from shiro_mlops.tasks.types.base import (
    InputRequirements,
    PredictionData,
    WeatherInput,
)


class TaskUnavailableError(RuntimeError):
    """The inputs at a load anchor cannot support a prediction.

    Serving answers 503 for the request time; the rolling-origin backtest wraps it
    as a ``ValueError`` naming the origin (docs/reference/lab.md §2).
    """


class InsufficientLoadHistoryError(TaskUnavailableError):
    """Too few actual load hours before the anchor for the task type's history window.

    ``first_missing`` is the earliest window hour without actual load; it stays out
    of the message because the message is serving's 503 text.
    """

    def __init__(self, message: str, *, first_missing: pd.Timestamp | None = None) -> None:
        super().__init__(message)
        self.first_missing = first_missing


class WeatherUnavailableError(TaskUnavailableError):
    """Neither forecasts nor degraded fallbacks cover the requested horizon.

    For observed-weather tasks: no station observation exists in the lookback.
    """


def admit_prediction_inputs(
    requirements: InputRequirements,
    *,
    anchor: pd.Timestamp,
    load: pd.DataFrame,
    weather: pd.DataFrame,
    weather_fields: Sequence[str],
    horizon_hours: int | None,
    subject: str,
) -> PredictionData:
    """Admit inputs for a prediction from ``anchor`` or raise ``TaskUnavailableError``.

    ``load`` covers at least ``(anchor - lookback_hours, anchor]`` and may hold NaN
    or earlier rows; ``weather`` holds the target hours for ``FORECAST`` tasks and
    the observations in the lookback for ``OBSERVED`` ones. ``subject`` only
    names the series in refusal messages. Every rule applies here, including
    ``require_load_coverage``, so a caller that checked load earlier loses nothing.

    A ``FORECAST`` task with ``horizon_hours=None`` raises a plain ``ValueError``:
    that is a caller contract error, not inputs the gate can refuse.
    """
    require_load_coverage(requirements, anchor=anchor, load=load, subject=subject)
    if requirements.weather is WeatherInput.FORECAST:
        _require_target_weather(weather, weather_fields, anchor, horizon_hours, subject)
    return PredictionData(
        anchor=anchor,
        load_history=_window(load, anchor, requirements.lookback_hours),
        weather=weather[[DATETIME_COL, *weather_fields]],
        horizon_hours=horizon_hours,
    )


def require_load_coverage(
    requirements: InputRequirements,
    *,
    anchor: pd.Timestamp,
    load: pd.DataFrame,
    subject: str,
) -> None:
    """Raise ``InsufficientLoadHistoryError`` when the lookback lacks the declared load hours.

    The load rule alone, so serving can refuse a load shortfall before it spends
    a weather query; ``history_coverage=None`` checks nothing.
    """
    coverage = requirements.history_coverage
    if coverage is None:
        return
    window = _window(load, anchor, coverage.window_hours)
    valid = pd.DatetimeIndex(pd.to_datetime(window.loc[window[LOAD_MW_COL].notna(), DATETIME_COL]))
    valid_hours = valid.nunique()
    if valid_hours < coverage.min_valid_hours:
        hours = pd.date_range(end=anchor, periods=coverage.window_hours, freq="h")
        raise InsufficientLoadHistoryError(
            f"Only {valid_hours} {subject} load hours in the {coverage.window_hours}-hour "
            f"window ending at anchor {anchor.isoformat()}; {coverage.min_valid_hours} required.",
            first_missing=hours.difference(valid).min(),
        )


def _window(load: pd.DataFrame, anchor: pd.Timestamp, hours: int) -> pd.DataFrame:
    """Rows in ``(anchor - hours, anchor]``."""
    times = pd.to_datetime(load[DATETIME_COL])
    inside = (times > anchor - timedelta(hours=hours)) & (times <= anchor)
    return load.loc[inside].reset_index(drop=True)


def _require_target_weather(
    weather: pd.DataFrame,
    fields: Sequence[str],
    anchor: pd.Timestamp,
    horizon_hours: int | None,
    subject: str,
) -> None:
    """Every target hour needs every weather field; a forecast task has no hour to skip."""
    if horizon_hours is None:
        raise ValueError("Forecast-weather prediction needs an explicit horizon_hours")
    targets = pd.date_range(anchor + timedelta(hours=1), periods=horizon_hours, freq="h")
    by_hour = weather.assign(**{DATETIME_COL: pd.to_datetime(weather[DATETIME_COL])})
    by_hour = by_hour.groupby(DATETIME_COL)[list(fields)].first().reindex(targets)
    for hour in targets:
        values = by_hour.loc[hour]
        missing = [field for field in fields if pd.isna(values[field])]
        if missing:
            raise WeatherUnavailableError(
                f"Weather does not cover {subject} target hour {hour.isoformat()} of the "
                f"{horizon_hours}-hour horizon after anchor {anchor.isoformat()}: "
                f"missing {', '.join(missing)}."
            )
