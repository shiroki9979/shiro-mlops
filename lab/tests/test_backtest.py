"""Offline unit tests for lab.backtest (public seam: rolling_origin_backtest, BacktestReport)."""

from dataclasses import replace
from datetime import datetime

import pandas as pd
import pytest
from lab.backtest import (
    BacktestReport,
    eligible_origins,
    origin_runs,
    rolling_origin_backtest,
    split_search_and_eval_origins,
    target_hours,
    training_row_count,
    verify_non_overlapping_target_windows,
)
from pydantic import BaseModel
from shiro_mlops.features.transformers import merge_weather_features
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.prediction_inputs import (
    InsufficientLoadHistoryError,
    WeatherUnavailableError,
)
from shiro_mlops.tasks.runner import fit_task
from shiro_mlops.tasks.types.base import PredictionData, TrainingData
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
    assert f"first missing: {missing_lookback_hour.isoformat()}" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, InsufficientLoadHistoryError)


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
    assert f"target hour {(ORIGIN_2 + pd.Timedelta(hours=3)).isoformat()}" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, WeatherUnavailableError)


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


def test_rolling_origin_backtest_predictions_ignore_load_from_first_target_hour_onward(
    fast_task: TaskDefinition,
) -> None:
    """Seam: extreme load from origin + 1h onward and weather beyond the horizon leave the forecast unchanged.

    Horizon weather stays clean because observed horizon weather is a legitimate forecast input
    under the observed-weather conditional backtest.
    """
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    clean_report = rolling_origin_backtest(
        fast_task,
        _training_data(load, weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )
    first_target_hour = ORIGIN_1 + pd.Timedelta(hours=1)
    horizon_end = ORIGIN_1 + pd.Timedelta(hours=HORIZON_HOURS)
    corrupted_load = load.copy()
    corrupted_load.loc[corrupted_load["datetime"] >= first_target_hour, "load_mw"] = 9_999_999.0
    corrupted_weather = weather.copy()
    corrupted_weather.loc[
        corrupted_weather["datetime"] > horizon_end, ["temperature", "relative_humidity"]
    ] = [99.0, 1.0]

    corrupted_report = rolling_origin_backtest(
        fast_task,
        _training_data(corrupted_load, corrupted_weather),
        origins=[ORIGIN_1],
        horizon_hours=HORIZON_HOURS,
    )

    assert len(clean_report.predictions[ORIGIN_1]) == HORIZON_HOURS
    assert corrupted_report.predictions[ORIGIN_1] == pytest.approx(
        clean_report.predictions[ORIGIN_1], abs=1e-9
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

    assert shifted_origin_report.predictions[ORIGIN_1][0] != pytest.approx(
        clean_report.predictions[ORIGIN_1][0], abs=1.0
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
        predictions={origin: (28_000.0, 28_100.0) for origin in origins},
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


def test_verify_non_overlapping_target_windows_rejects_shared_target_hour() -> None:
    """Seam: an eval origin whose first target hour is a search origin's last target hour is rejected."""
    search_origins = (pd.Timestamp("2026-10-28 18:00:00"),)
    eval_origins = (pd.Timestamp("2026-10-29 17:00:00"),)

    with pytest.raises(ValueError, match="2026-10-29T18:00:00"):
        verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours=24)


def test_verify_non_overlapping_target_windows_rejects_eval_origin_before_search_origins() -> None:
    """Seam: eval origins must be strictly later than every search origin even without overlap."""
    search_origins = (pd.Timestamp("2026-10-28 18:00:00"),)
    eval_origins = (pd.Timestamp("2026-10-26 18:00:00"),)

    with pytest.raises(ValueError, match="strictly later"):
        verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours=24)


def test_verify_non_overlapping_target_windows_accepts_later_disjoint_windows() -> None:
    """Seam: the study's split (last search 10-28 18:00, first eval 10-29 18:00, H=24) is accepted."""
    search_origins = (pd.Timestamp("2026-10-27 18:00:00"), pd.Timestamp("2026-10-28 18:00:00"))
    eval_origins = (pd.Timestamp("2026-10-29 18:00:00"), pd.Timestamp("2026-10-29 22:00:00"))

    verify_non_overlapping_target_windows(search_origins, eval_origins, horizon_hours=24)


def test_eligible_origins_span_every_hour_that_passes_the_backtest_checks(
    fast_task: TaskDefinition,
) -> None:
    """Seam: eligible_origins lists each hourly origin rolling_origin_backtest accepts, and no other."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    times = load["datetime"]
    gap_hour = times.iloc[250]
    data = _training_data(load[times != gap_hour], weather)

    eligible = eligible_origins(fast_task, data, HORIZON_HOURS)

    # min_training_hours = 216 首次於 index 215 達成；index 244..249 的目標時段含缺口，
    # index 250 之後的 168 小時回看皆含缺口，直到資料結束。
    expected = tuple(pd.date_range(times.iloc[215], times.iloc[243], freq="h"))
    assert eligible == expected
    assert origin_runs(eligible) == [(times.iloc[215], times.iloc[243])]
    rolling_origin_backtest(fast_task, data, origins=[eligible[-1]], horizon_hours=HORIZON_HOURS)
    with pytest.raises(ValueError, match="horizon load"):
        rolling_origin_backtest(
            fast_task, data, origins=[times.iloc[244]], horizon_hours=HORIZON_HOURS
        )


def test_eligible_origins_respect_an_explicit_min_history_override(
    fast_task: TaskDefinition,
) -> None:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    data = _training_data(load, weather)

    eligible = eligible_origins(fast_task, data, HORIZON_HOURS, min_history_hours=168)

    assert eligible[0] == pd.Timestamp(load["datetime"].iloc[167])


def test_origin_runs_group_consecutive_hours() -> None:
    origins = (
        pd.Timestamp("2026-10-01 00:00"),
        pd.Timestamp("2026-10-01 01:00"),
        pd.Timestamp("2026-10-01 05:00"),
    )

    assert origin_runs(origins) == [
        (pd.Timestamp("2026-10-01 00:00"), pd.Timestamp("2026-10-01 01:00")),
        (pd.Timestamp("2026-10-01 05:00"), pd.Timestamp("2026-10-01 05:00")),
    ]
    assert origin_runs(()) == []


def test_split_takes_the_last_calendar_days_for_evaluation_and_earlier_disjoint_search() -> None:
    eligible = tuple(pd.date_range("2026-10-01 00:00", "2026-10-12 23:00", freq="h"))

    split = split_search_and_eval_origins(
        eligible, horizon_hours=24, eval_calendar_days=7, hour_step=6
    )

    assert split.eval_origins[0] == pd.Timestamp("2026-10-06 00:00")
    assert split.eval_origins[-1] == pd.Timestamp("2026-10-12 18:00")
    assert split.eval_calendar_days == 7
    assert split.search_origins[0] == pd.Timestamp("2026-10-01 00:00")
    assert split.search_origins[-1] == pd.Timestamp("2026-10-05 00:00")
    assert all(origin.hour % 6 == 0 for origin in (*split.search_origins, *split.eval_origins))
    verify_non_overlapping_target_windows(split.search_origins, split.eval_origins, 24)


def test_split_without_room_for_search_origins_is_rejected() -> None:
    eligible = tuple(pd.date_range("2026-10-01 00:00", "2026-10-05 23:00", freq="h"))

    with pytest.raises(ValueError, match="search origins"):
        split_search_and_eval_origins(eligible, horizon_hours=24, eval_calendar_days=7, hour_step=6)


def test_training_row_count_grows_with_the_origin_and_drops_rows_without_weather(
    fast_task: TaskDefinition,
) -> None:
    """Seam: training_row_count counts the rows fit_task trains on for history up to the origin."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    origin = pd.Timestamp(load["datetime"].iloc[260])
    complete = _training_data(load, weather)
    gap = weather["datetime"].between(load["datetime"].iloc[230], load["datetime"].iloc[235])
    gapped = _training_data(load, weather[~gap])

    count = training_row_count(fast_task, complete, origin)

    assert training_row_count(fast_task, complete, origin + pd.Timedelta(hours=1)) == count + 1
    assert training_row_count(fast_task, gapped, origin) < count


def test_eligible_origins_characterize_load_and_weather_gaps(
    fast_task: TaskDefinition,
) -> None:
    """Seam: eligible_origins on a snapshot with load and weather gaps.

    The set is a characterization: the prediction input gate must accept exactly the
    origins the backtest's own checks accepted. Index 60 (missing row) and 270 (NaN load)
    break the lookback; 240..242 leave 242 beyond the 2-hour weather alignment; 250 and
    the NaN humidity at 255 are filled per field from the hour before.
    """
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    times = load["datetime"]
    load = load[times != times.iloc[60]].reset_index(drop=True)
    load.loc[load["datetime"] == times.iloc[270], "load_mw"] = float("nan")
    beyond_tolerance = times.iloc[[240, 241, 242]]
    weather = weather[~weather["datetime"].isin([*beyond_tolerance, times.iloc[250]])]
    weather = weather.reset_index(drop=True)
    weather.loc[weather["datetime"] == times.iloc[255], "relative_humidity"] = float("nan")

    eligible = eligible_origins(
        fast_task, _training_data(load, weather), HORIZON_HOURS, min_history_hours=168
    )

    assert origin_runs(eligible) == [
        (pd.Timestamp("2026-09-18 12:00"), pd.Timestamp("2026-09-18 19:00")),
        (pd.Timestamp("2026-09-19 02:00"), pd.Timestamp("2026-09-19 23:00")),
    ]


def test_rolling_origin_backtest_predicts_as_if_given_all_load_before_the_origin(
    fast_task: TaskDefinition,
) -> None:
    """Seam: trimming load_history to the lookback leaves the forecast equal to one fed all prior load."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    data = _training_data(load, weather)
    report = rolling_origin_backtest(
        fast_task, data, origins=[ORIGIN_1], horizon_hours=HORIZON_HOURS
    )
    prior_load = load[load["datetime"] <= ORIGIN_1].reset_index(drop=True)
    trained = fit_task(
        fast_task,
        TrainingData(
            load=prior_load[["datetime", "subject", "load_mw"]],
            weather=data.weather[data.weather["datetime"] <= ORIGIN_1].reset_index(drop=True),
            validation_start=ORIGIN_1 + pd.Timedelta(hours=1),
        ),
    )
    horizon_weather = data.weather[
        data.weather["datetime"].isin(target_hours(ORIGIN_1, HORIZON_HOURS))
    ].reset_index(drop=True)

    untrimmed = trained.model.predict(
        PredictionData(
            anchor=ORIGIN_1,
            load_history=prior_load[["datetime", "subject", "load_mw"]],
            weather=horizon_weather,
            horizon_hours=HORIZON_HOURS,
        )
    )

    assert report.predictions[ORIGIN_1] == pytest.approx(
        tuple(untrimmed["predicted_load_mw"]), abs=1e-9
    )


# --- inputs that would silently skew a study -------------------------------------------------


def test_rolling_origin_backtest_rejects_a_repeated_origin(fast_task: TaskDefinition) -> None:
    """A repeated origin is weighted twice in every metric while its forecast is kept once."""
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)

    with pytest.raises(ValueError, match=f"listed more than once.*{ORIGIN_1.isoformat()}"):
        rolling_origin_backtest(
            fast_task,
            _training_data(load, weather),
            origins=[ORIGIN_1, ORIGIN_1.isoformat(), ORIGIN_2],
            horizon_hours=HORIZON_HOURS,
        )


@pytest.mark.parametrize("horizon_hours", [0, -1])
def test_rolling_origin_backtest_rejects_a_horizon_shorter_than_one_hour(
    fast_task: TaskDefinition, horizon_hours: int
) -> None:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)

    with pytest.raises(ValueError, match="horizon_hours"):
        rolling_origin_backtest(
            fast_task,
            _training_data(load, weather),
            origins=[ORIGIN_1],
            horizon_hours=horizon_hours,
        )


def test_rolling_origin_backtest_rejects_no_origins(fast_task: TaskDefinition) -> None:
    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)

    with pytest.raises(ValueError, match="origins must not be empty"):
        rolling_origin_backtest(
            fast_task, _training_data(load, weather), origins=[], horizon_hours=HORIZON_HOURS
        )


@pytest.mark.parametrize("hour_step", [0, -6, 25])
def test_split_rejects_an_hour_step_outside_one_to_twenty_four(hour_step: int) -> None:
    eligible = tuple(pd.date_range("2026-10-01 00:00", "2026-10-12 23:00", freq="h"))

    with pytest.raises(ValueError, match="hour_step"):
        split_search_and_eval_origins(
            eligible, horizon_hours=24, eval_calendar_days=7, hour_step=hour_step
        )


@pytest.mark.parametrize("eval_calendar_days", [0, -1])
def test_split_rejects_fewer_than_one_evaluation_day(eval_calendar_days: int) -> None:
    """`dates[-0:]` is every date and `dates[--1:]` drops only the first, so neither failed."""
    eligible = tuple(pd.date_range("2026-10-01 00:00", "2026-10-12 23:00", freq="h"))

    with pytest.raises(ValueError, match="eval_calendar_days"):
        split_search_and_eval_origins(
            eligible, horizon_hours=24, eval_calendar_days=eval_calendar_days, hour_step=6
        )


def test_split_rejects_a_horizon_shorter_than_one_hour() -> None:
    eligible = tuple(pd.date_range("2026-10-01 00:00", "2026-10-12 23:00", freq="h"))

    with pytest.raises(ValueError, match="horizon_hours"):
        split_search_and_eval_origins(eligible, horizon_hours=0, eval_calendar_days=7, hour_step=6)


def test_split_of_no_eligible_origins_is_rejected() -> None:
    with pytest.raises(ValueError, match="no eligible origins"):
        split_search_and_eval_origins((), horizon_hours=24, eval_calendar_days=7, hour_step=6)


def test_target_hour_weather_does_not_depend_on_the_origin_that_asks_for_it(
    fast_task: TaskDefinition,
) -> None:
    """Each hour takes the latest observation within two hours before it, whatever the origin;
    aligning the whole snapshot once must give every origin the weather it used to get."""
    from lab.backtest import _build_context

    load, weather = hourly_load_with_weather(HOURS, LAST_HOUR)
    weather = weather.drop(index=[40, 41, 42, 100, 200, 201]).reset_index(drop=True)
    weather.loc[150, "relative_humidity"] = float("nan")
    context = _build_context(fast_task, _training_data(load, weather), HORIZON_HOURS, 24)

    def aligned_one_origin_at_a_time(horizon: pd.DatetimeIndex) -> pd.DataFrame:
        grid = pd.DataFrame({"datetime": horizon})
        upto = context.weather[context.weather["datetime"] <= horizon[-1]]
        aligned = merge_weather_features(grid, upto)
        return aligned[["datetime", *context.weather_fields]].sort_values(
            "datetime", ignore_index=True
        )

    first, last = load["datetime"].iloc[0], load["datetime"].iloc[-1]
    origins = [
        *pd.date_range(first, last, freq="7h"),
        first - pd.Timedelta(hours=3),
        last,
        last + pd.Timedelta(hours=1),
        last + pd.Timedelta(hours=30),
    ]
    for origin in origins:
        horizon = target_hours(origin, HORIZON_HOURS)
        pd.testing.assert_frame_equal(
            context.aligned_horizon_weather(horizon), aligned_one_origin_at_a_time(horizon)
        )
