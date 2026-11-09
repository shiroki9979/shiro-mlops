"""Offline unit tests for lab.backtest (public seam: rolling_origin_backtest, BacktestReport)."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
from lab.backtest import BacktestReport, rolling_origin_backtest
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.types.base import TrainingData
from tests.helpers import hourly_load_with_weather

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
HOURS = 24 * 12
HORIZON_HOURS = 6
ORIGIN_1 = pd.Timestamp("2026-09-19 12:00:00")
ORIGIN_2 = pd.Timestamp("2026-09-20 12:00:00")


@pytest.fixture
def fast_task() -> TaskDefinition:
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    params = shipped.params.model_copy(
        update={"model": shipped.params.model.model_copy(update={"n_estimators": 15})}
    )
    policies = shipped.policies.model_copy(update={"min_training_hours": 24 * 9})
    return replace(shipped, params=params, policies=policies)


def _training_data(load: pd.DataFrame, weather: pd.DataFrame) -> TrainingData:
    return TrainingData(
        load=load[["datetime", "subject", "load_mw"]].reset_index(drop=True),
        weather=weather[["datetime", "temperature", "relative_humidity"]].reset_index(drop=True),
        validation_start=pd.Timestamp(load["datetime"].iloc[-24]),
    )


def test_rolling_origin_backtest_populates_all_horizon_buckets_and_zero_mape_on_constant_load(
    fast_task: TaskDefinition,
) -> None:
    """Seam: rolling_origin_backtest returns BacktestReport with 1..H keys and 0.0 MAPE on constant load."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    load["load_mw"] = 28500.0
    data = _training_data(load, weather)

    report = rolling_origin_backtest(
        fast_task,
        data,
        origins=[ORIGIN_1, ORIGIN_2],
        horizon_hours=HORIZON_HOURS,
    )

    assert isinstance(report, BacktestReport)
    assert report.origins == (ORIGIN_1, ORIGIN_2)
    assert report.horizon_hours == HORIZON_HOURS
    assert report.min_history_hours == fast_task.policies.min_training_hours
    assert report.min_history_overridden is False
    assert report.params == fast_task.params
    assert list(report.mape_by_horizon.keys()) == list(range(1, HORIZON_HOURS + 1))
    assert report.overall_mape == pytest.approx(0.0, abs=1e-6)
    for step in range(1, HORIZON_HOURS + 1):
        assert report.mape_by_horizon[step] == pytest.approx(0.0, abs=1e-6)


def test_rolling_origin_backtest_rejects_origin_below_min_history_and_allows_override(
    fast_task: TaskDefinition,
) -> None:
    """Seam: rolling_origin_backtest raises ValueError naming offending origin when history < min_history_hours."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    data = _training_data(load, weather)
    early_origin = pd.Timestamp(load["datetime"].iloc[180])

    with pytest.raises(ValueError, match=early_origin.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            data,
            origins=[early_origin, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )
    assert "min_history_hours" in str(exc_info.value)

    overridden_report = rolling_origin_backtest(
        fast_task,
        data,
        origins=[early_origin],
        horizon_hours=HORIZON_HOURS,
        min_history_hours=180,
    )
    assert overridden_report.min_history_hours == 180
    assert overridden_report.min_history_overridden is True


def test_rolling_origin_backtest_rejects_origin_with_missing_lookback_load(
    fast_task: TaskDefinition,
) -> None:
    """Seam: rolling_origin_backtest raises ValueError naming offending origin when lookback load has a gap."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    missing_lookback_hour = ORIGIN_2 - pd.Timedelta(hours=12)
    gapped_load = load[load["datetime"] != missing_lookback_hour].reset_index(drop=True)
    data = _training_data(gapped_load, weather)

    with pytest.raises(ValueError, match=ORIGIN_2.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            data,
            origins=[ORIGIN_1, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )
    assert "lookback" in str(exc_info.value).lower()


def test_rolling_origin_backtest_rejects_origin_with_missing_horizon_load_or_weather(
    fast_task: TaskDefinition,
) -> None:
    """Seam: rolling_origin_backtest raises ValueError naming offending origin when horizon load or weather is missing."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    missing_horizon_hour = ORIGIN_2 + pd.Timedelta(hours=3)
    gapped_load = load[load["datetime"] != missing_horizon_hour].reset_index(drop=True)
    load_gap_data = _training_data(gapped_load, weather)

    with pytest.raises(ValueError, match=ORIGIN_2.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            load_gap_data,
            origins=[ORIGIN_1, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )
    assert "horizon" in str(exc_info.value).lower()

    # 3 consecutive missing weather hours exceed the 2-hour backward fill tolerance
    three_hour_weather_gap = {
        ORIGIN_2 + pd.Timedelta(hours=1),
        ORIGIN_2 + pd.Timedelta(hours=2),
        ORIGIN_2 + pd.Timedelta(hours=3),
    }
    gapped_weather = weather[~weather["datetime"].isin(three_hour_weather_gap)].reset_index(
        drop=True
    )
    weather_gap_data = _training_data(load, gapped_weather)

    with pytest.raises(ValueError, match=ORIGIN_2.isoformat()) as wx_exc_info:
        rolling_origin_backtest(
            fast_task,
            weather_gap_data,
            origins=[ORIGIN_1, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )
    assert "weather" in str(wx_exc_info.value).lower()


def test_rolling_origin_backtest_fills_single_missing_weather_hour_in_horizon(
    fast_task: TaskDefinition,
) -> None:
    """Seam: a single missing hourly weather observation in the horizon is filled via 2h backward alignment."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    missing_weather_hour = ORIGIN_2 + pd.Timedelta(hours=2)
    gapped_weather = weather[weather["datetime"] != missing_weather_hour].reset_index(drop=True)
    data = _training_data(load, gapped_weather)

    report = rolling_origin_backtest(
        fast_task,
        data,
        origins=[ORIGIN_2],
        horizon_hours=HORIZON_HOURS,
    )

    assert list(report.mape_by_horizon.keys()) == list(range(1, HORIZON_HOURS + 1))
    assert all(pd.notna(val) for val in report.mape_by_horizon.values())


def test_rolling_origin_backtest_has_no_future_leakage_and_includes_origin_in_history(
    fast_task: TaskDefinition,
) -> None:
    """Seam: injecting extreme load/weather after origin does not alter origin predictions, and origin is in history."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    clean_data = _training_data(load, weather)
    clean_report = rolling_origin_backtest(
        fast_task,
        clean_data,
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )

    # Inject extreme load at ORIGIN_1 + 2h .. end (leaving ORIGIN_1 + 1h untouched so step-1 actual is identical)
    # and extreme weather after ORIGIN_1 + HORIZON_HOURS.
    corrupted_load = load.copy()
    corrupted_load.loc[
        corrupted_load["datetime"] >= ORIGIN_1 + pd.Timedelta(hours=2), "load_mw"
    ] = 9_999_999.0
    corrupted_weather = weather.copy()
    corrupted_weather.loc[
        corrupted_weather["datetime"] > ORIGIN_1 + pd.Timedelta(hours=HORIZON_HOURS),
        ["temperature", "relative_humidity"],
    ] = [99.0, 1.0]
    corrupted_data = _training_data(corrupted_load, corrupted_weather)

    corrupted_report = rolling_origin_backtest(
        fast_task,
        corrupted_data,
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )

    # Step 1 actual load was untouched, so identical step-1 MAPE proves the model and step-1 prediction
    # were completely unaffected by future load (ORIGIN_1 + 2h..) and future weather.
    assert corrupted_report.mape_by_horizon[1] == pytest.approx(
        clean_report.mape_by_horizon[1], abs=1e-12
    )

    # Conversely, perturbing load AT origin itself changes step-1 prediction (since origin is lag_1 for origin + 1h).
    shifted_origin_load = load.copy()
    shifted_origin_load.loc[shifted_origin_load["datetime"] == ORIGIN_1, "load_mw"] = 45_000.0
    shifted_origin_report = rolling_origin_backtest(
        fast_task,
        _training_data(shifted_origin_load, weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )
    assert shifted_origin_report.mape_by_horizon[1] != pytest.approx(
        clean_report.mape_by_horizon[1], abs=1e-4
    )

    # Removing the origin hour itself must fail lookback completeness naming the origin timestamp.
    without_origin_load = load[load["datetime"] != ORIGIN_1].reset_index(drop=True)
    with pytest.raises(ValueError, match=ORIGIN_1.isoformat()):
        rolling_origin_backtest(
            fast_task,
            _training_data(without_origin_load, weather),
            origins=[ORIGIN_1],
            horizon_hours=HORIZON_HOURS,
        )


def test_backtest_report_direct_comparison_lower_overall_mape_wins(
    fast_task: TaskDefinition,
) -> None:
    """Seam: two BacktestReport instances on the same origins and horizon compare directly by overall_mape."""
    better = BacktestReport(
        overall_mape=1.85,
        mape_by_horizon={1: 1.2, 2: 2.5},
        origins=(ORIGIN_1, ORIGIN_2),
        horizon_hours=2,
        min_history_hours=216,
        min_history_overridden=False,
        params=fast_task.params,
    )
    worse = BacktestReport(
        overall_mape=2.40,
        mape_by_horizon={1: 1.1, 2: 3.7},
        origins=(ORIGIN_1, ORIGIN_2),
        horizon_hours=2,
        min_history_hours=216,
        min_history_overridden=False,
        params=fast_task.params,
    )

    assert better.beats(worse) is True
    assert worse.beats(better) is False
    assert better.beats(better) is False

    mismatched_origins = replace(worse, origins=(ORIGIN_1,))
    with pytest.raises(ValueError, match="origins"):
        better.beats(mismatched_origins)
