"""Offline unit tests for lab.backtest (public seam: rolling_origin_backtest, BacktestReport)."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
from lab.backtest import BacktestReport, rolling_origin_backtest
from pydantic import BaseModel
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


def test_rolling_origin_backtest_rejects_origin_below_min_history(
    fast_task: TaskDefinition,
) -> None:
    """Seam: an origin with fewer valid load hours than min_history_hours is rejected by name."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    early_origin = pd.Timestamp(load["datetime"].iloc[180])

    with pytest.raises(ValueError, match=early_origin.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            _training_data(load, weather),
            origins=[early_origin, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )

    assert "min_history_hours" in str(exc_info.value)


def test_rolling_origin_backtest_records_explicit_min_history_override(
    fast_task: TaskDefinition,
) -> None:
    """Seam: an explicit min_history_hours admits an early origin and the report records the override."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    early_origin = pd.Timestamp(load["datetime"].iloc[180])

    report = rolling_origin_backtest(
        fast_task,
        _training_data(load, weather),
        origins=[early_origin],
        horizon_hours=HORIZON_HOURS,
        min_history_hours=180,
    )

    assert report.min_history_hours == 180
    assert report.min_history_overridden is True


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


def test_rolling_origin_backtest_rejects_origin_with_missing_horizon_load(
    fast_task: TaskDefinition,
) -> None:
    """Seam: a missing actual load hour inside the horizon rejects that origin by name."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    missing_horizon_hour = ORIGIN_2 + pd.Timedelta(hours=3)
    gapped_load = load[load["datetime"] != missing_horizon_hour].reset_index(drop=True)

    with pytest.raises(ValueError, match=ORIGIN_2.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            _training_data(gapped_load, weather),
            origins=[ORIGIN_1, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )

    assert "horizon" in str(exc_info.value).lower()


def test_rolling_origin_backtest_rejects_horizon_weather_gap_beyond_alignment_tolerance(
    fast_task: TaskDefinition,
) -> None:
    """Seam: 3 consecutive missing weather hours exceed the 2-hour backward alignment and reject the origin."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    three_hour_weather_gap = {ORIGIN_2 + pd.Timedelta(hours=step) for step in (1, 2, 3)}
    gapped_weather = weather[~weather["datetime"].isin(three_hour_weather_gap)].reset_index(
        drop=True
    )

    with pytest.raises(ValueError, match=ORIGIN_2.isoformat()) as exc_info:
        rolling_origin_backtest(
            fast_task,
            _training_data(load, gapped_weather),
            origins=[ORIGIN_1, ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )

    assert "weather" in str(exc_info.value).lower()


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


def test_rolling_origin_backtest_has_no_future_leakage(
    fast_task: TaskDefinition,
) -> None:
    """Seam: injecting extreme load/weather after origin does not alter step-1 accuracy for that origin."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    clean_report = rolling_origin_backtest(
        fast_task,
        _training_data(load, weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )
    corrupted_load = load.copy()
    corrupted_load.loc[
        corrupted_load["datetime"] >= ORIGIN_1 + pd.Timedelta(hours=2), "load_mw"
    ] = 9_999_999.0
    corrupted_weather = weather.copy()
    corrupted_weather.loc[
        corrupted_weather["datetime"] > ORIGIN_1 + pd.Timedelta(hours=HORIZON_HOURS),
        ["temperature", "relative_humidity"],
    ] = [99.0, 1.0]

    corrupted_report = rolling_origin_backtest(
        fast_task,
        _training_data(corrupted_load, corrupted_weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )

    assert corrupted_report.mape_by_horizon[1] == pytest.approx(
        clean_report.mape_by_horizon[1], abs=1e-12
    )


def test_rolling_origin_backtest_uses_origin_hour_as_latest_history(
    fast_task: TaskDefinition,
) -> None:
    """Seam: perturbing the load at the origin hour changes the step-1 forecast (origin is lag 1)."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    clean_report = rolling_origin_backtest(
        fast_task,
        _training_data(load, weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )
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


def test_rolling_origin_backtest_rejects_origin_missing_its_own_load_hour(
    fast_task: TaskDefinition,
) -> None:
    """Seam: an origin whose own hour has no actual load fails lookback completeness by name."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    without_origin_load = load[load["datetime"] != ORIGIN_1].reset_index(drop=True)

    with pytest.raises(ValueError, match=ORIGIN_1.isoformat()):
        rolling_origin_backtest(
            fast_task,
            _training_data(without_origin_load, weather),
            origins=[ORIGIN_1],
            horizon_hours=HORIZON_HOURS,
        )


def _report(
    overall_mape: float, origins: tuple[pd.Timestamp, ...], params: BaseModel
) -> BacktestReport:
    return BacktestReport(
        overall_mape=overall_mape,
        mape_by_horizon={1: overall_mape, 2: overall_mape},
        origins=origins,
        horizon_hours=2,
        min_history_hours=216,
        min_history_overridden=False,
        params=params,
    )


def test_backtest_report_lower_overall_mape_beats_baseline(
    fast_task: TaskDefinition,
) -> None:
    """Seam: on the same origins and horizon, strictly lower overall MAPE wins."""
    better = _report(1.85, (ORIGIN_1, ORIGIN_2), fast_task.params)
    worse = _report(2.40, (ORIGIN_1, ORIGIN_2), fast_task.params)

    assert better.beats(worse) is True
    assert worse.beats(better) is False
    assert better.beats(better) is False


def test_backtest_report_refuses_comparison_across_different_origins(
    fast_task: TaskDefinition,
) -> None:
    """Seam: reports built on different origin sets are not comparable."""
    candidate = _report(1.85, (ORIGIN_1, ORIGIN_2), fast_task.params)
    baseline = _report(2.40, (ORIGIN_1,), fast_task.params)

    with pytest.raises(ValueError, match="origins"):
        candidate.beats(baseline)
