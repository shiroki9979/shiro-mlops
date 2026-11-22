"""Public-interface tests for the prediction input gate, fed with in-memory frames."""

from dataclasses import replace

import pandas as pd
import pytest

from shiro_mlops.tasks.prediction_inputs import (
    InsufficientLoadHistoryError,
    WeatherUnavailableError,
    admit_prediction_inputs,
)
from shiro_mlops.tasks.types.base import HistoryCoverage, InputRequirements, WeatherInput

ANCHOR = pd.Timestamp("2026-11-20 12:00")
LOOKBACK_HOURS = 6
HORIZON_HOURS = 3
FIELDS = ("temperature", "relative_humidity")
FORECAST_COMPLETE = InputRequirements(
    weather=WeatherInput.FORECAST,
    lookback_hours=LOOKBACK_HOURS,
    history_coverage=HistoryCoverage.complete(LOOKBACK_HOURS),
)


def _load(hours: int = LOOKBACK_HOURS + 4) -> pd.DataFrame:
    """Hourly nationwide load for the ``hours`` ending at the anchor."""
    times = pd.date_range(end=ANCHOR, periods=hours, freq="h")
    return pd.DataFrame(
        {"datetime": times, "subject": "nationwide", "load_mw": 30_000.0 + pd.RangeIndex(hours)}
    )


def _forecast_weather(hours: int = HORIZON_HOURS) -> pd.DataFrame:
    times = pd.date_range(ANCHOR + pd.Timedelta(hours=1), periods=hours, freq="h")
    return pd.DataFrame(
        {"datetime": times, "temperature": 25.0, "relative_humidity": 70.0, "extra": 1.0}
    )


def _admit(requirements: InputRequirements = FORECAST_COMPLETE, **overrides):
    inputs = {
        "anchor": ANCHOR,
        "load": _load(),
        "weather": _forecast_weather(),
        "weather_fields": FIELDS,
        "horizon_hours": HORIZON_HOURS,
        "subject": "nationwide",
    }
    return admit_prediction_inputs(requirements, **(inputs | overrides))


def test_complete_inputs_are_admitted_with_load_history_cropped_to_the_lookback() -> None:
    data = _admit()

    assert data.anchor == ANCHOR
    assert data.horizon_hours == HORIZON_HOURS
    # (anchor - 6h, anchor]：06:00 與更早的列不交給任務類型。
    assert list(data.load_history["datetime"]) == list(
        pd.date_range("2026-11-20 07:00", "2026-11-20 12:00", freq="h")
    )
    assert list(data.weather.columns) == ["datetime", *FIELDS]
    assert len(data.weather) == HORIZON_HOURS


@pytest.mark.parametrize(
    "missing",
    [pd.Timestamp("2026-11-20 07:00"), pd.Timestamp("2026-11-20 12:00")],
    ids=["earliest-lookback-hour", "anchor-hour"],
)
@pytest.mark.parametrize("gap", ["absent-row", "nan-load"])
def test_a_missing_load_hour_in_the_lookback_is_refused(missing: pd.Timestamp, gap: str) -> None:
    load = _load()
    if gap == "absent-row":
        load = load[load["datetime"] != missing]
    else:
        load.loc[load["datetime"] == missing, "load_mw"] = float("nan")

    with pytest.raises(
        InsufficientLoadHistoryError,
        match=r"Only 5 nationwide load hours in the 6-hour window ending at anchor "
        r"2026-11-20T12:00:00; 6 required\.",
    ):
        _admit(load=load)


def test_missing_load_before_the_lookback_is_admitted() -> None:
    load = _load()
    load.loc[load["datetime"] == pd.Timestamp("2026-11-20 06:00"), "load_mw"] = float("nan")

    data = _admit(load=load.drop(index=0))

    assert data.load_history["load_mw"].notna().all()


def test_no_history_coverage_skips_the_load_completeness_check() -> None:
    lenient = replace(FORECAST_COMPLETE, history_coverage=None)
    load = _load()
    load.loc[load["datetime"] == pd.Timestamp("2026-11-20 09:00"), "load_mw"] = float("nan")

    data = _admit(lenient, load=load)

    assert data.load_history["load_mw"].isna().sum() == 1


def test_load_completeness_also_applies_to_observed_weather_tasks() -> None:
    observed = replace(FORECAST_COMPLETE, weather=WeatherInput.OBSERVED)
    load = _load()

    with pytest.raises(InsufficientLoadHistoryError):
        _admit(observed, load=load[load["datetime"] != pd.Timestamp("2026-11-20 10:00")])


@pytest.mark.parametrize(
    ("gap", "missing"),
    [("absent-row", "temperature, relative_humidity"), ("nan-field", "relative_humidity")],
)
def test_forecast_weather_missing_a_target_hour_is_refused_naming_the_first_one(
    gap: str, missing: str
) -> None:
    weather = _forecast_weather()
    gaps = weather["datetime"] >= pd.Timestamp("2026-11-20 14:00")
    if gap == "absent-row":
        weather = weather[~gaps]
    else:
        weather.loc[gaps, "relative_humidity"] = float("nan")

    with pytest.raises(
        WeatherUnavailableError,
        match=r"Weather does not cover nationwide target hour 2026-11-20T14:00:00 of the "
        rf"3-hour horizon after anchor 2026-11-20T12:00:00: missing {missing}\.",
    ):
        _admit(weather=weather)


def test_forecast_weather_beyond_the_horizon_is_not_required() -> None:
    data = _admit(horizon_hours=2)

    assert data.horizon_hours == 2


def test_observed_weather_tasks_skip_the_weather_check() -> None:
    observed = replace(FORECAST_COMPLETE, weather=WeatherInput.OBSERVED)
    sparse = pd.DataFrame(
        {"datetime": [pd.Timestamp("2026-11-20 08:00")], "temperature": [24.0]}
    ).assign(relative_humidity=float("nan"))

    data = _admit(observed, weather=sparse, horizon_hours=None)

    assert len(data.weather) == 1
