"""Public-interface tests for the unsupervised_reconstruction task type (shallow AutoEncoder)."""

from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.neural_network import MLPRegressor

from shiro_mlops.tasks.types import get_task_type
from shiro_mlops.tasks.types.base import (
    HealthStatus,
    PredictionData,
    TrainingData,
    WeatherInput,
)
from shiro_mlops.tasks.types.unsupervised_reconstruction import (
    SYNTHETIC_ANOMALIES,
    NumpyMLP,
    UnsupervisedReconstructionParams,
    _Scaler,
)

LAST_HOUR = datetime(2026, 9, 20, 23, 0)
ANCHOR = pd.Timestamp(LAST_HOUR)
TRAINING_HOURS = 24 * 28
WINDOW_HOURS = 24
PARAMS = UnsupervisedReconstructionParams.model_validate(
    {
        "window_hours": WINDOW_HOURS,
        "threshold_quantile": 0.99,
        "model": {
            "hidden_layer_sizes": [32, 8, 32],
            "alpha": 0.0001,
            "learning_rate_init": 0.001,
            "max_iter": 300,
        },
    }
)
task_type = get_task_type("unsupervised_reconstruction")
THRESHOLDS = {"min_recall": 0.8, "max_false_positive_rate": 0.05}


def _load_with_weather(hours: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily and weekly load shape driven by temperature, with seeded measurement noise."""
    rng = np.random.default_rng(7)
    times = pd.date_range(end=LAST_HOUR, periods=hours, freq="h")
    daily = np.sin(2 * np.pi * (times.hour - 6) / 24.0)
    temperature = 28.0 + 4.0 * daily + rng.normal(0.0, 0.5, hours)
    weekend = np.asarray(times.dayofweek >= 5, dtype=float)
    load_mw = (
        30000.0
        + 3000.0 * daily
        - 2500.0 * weekend
        + 300.0 * (temperature - 28.0)
        + rng.normal(0.0, 150.0, hours)
    )
    load = pd.DataFrame({"datetime": times, "subject": "nationwide", "load_mw": load_mw})
    weather = pd.DataFrame(
        {
            "datetime": times,
            "temperature": temperature,
            "relative_humidity": 75.0 - 5.0 * daily + rng.normal(0.0, 1.0, hours),
        }
    )
    return load, weather


def _training_data(validation_start: pd.Timestamp | None = None) -> TrainingData:
    load, weather = _load_with_weather(TRAINING_HOURS)
    split = validation_start or load["datetime"].iloc[int(len(load) * 0.8)]
    return TrainingData(load=load, weather=weather, validation_start=split)


def _prediction_data(horizon_hours: int | None) -> PredictionData:
    load, weather = _load_with_weather(TRAINING_HOURS)
    lookback_start = ANCHOR - pd.Timedelta(hours=PARAMS.lookback_hours)
    return PredictionData(
        anchor=ANCHOR,
        load_history=load[load["datetime"] >= lookback_start].reset_index(drop=True),
        weather=weather[weather["datetime"] >= lookback_start].reset_index(drop=True),
        horizon_hours=horizon_hours,
    )


def _hours_before_anchor(*hours: int) -> list[pd.Timestamp]:
    return [ANCHOR - pd.Timedelta(hours=hour) for hour in hours]


@pytest.fixture(scope="module")
def trained():
    return task_type.train(PARAMS, _training_data())


# --- numpy forward pass (ADR-0010) ---------------------------------------------------------


@pytest.mark.filterwarnings("ignore::sklearn.exceptions.ConvergenceWarning")
def test_numpy_forward_pass_matches_mlp_regressor_predict() -> None:
    inputs = np.random.default_rng(0).normal(size=(64, 12))
    regressor = MLPRegressor(hidden_layer_sizes=(8, 3, 8), max_iter=500, random_state=0)
    regressor.fit(inputs, inputs)

    reconstructed = NumpyMLP.from_regressor(regressor).predict(inputs)

    np.testing.assert_allclose(reconstructed, regressor.predict(inputs), rtol=1e-9, atol=1e-9)


def test_numpy_forward_pass_refuses_activations_it_does_not_implement() -> None:
    inputs = np.random.default_rng(0).normal(size=(16, 4))
    regressor = MLPRegressor(hidden_layer_sizes=(3,), activation="tanh", max_iter=20)
    with pytest.warns(Warning):
        regressor.fit(inputs, inputs)

    with pytest.raises(ValueError, match="relu"):
        NumpyMLP.from_regressor(regressor)


# --- Task type -----------------------------------------------------------------------------


def test_requirements_ask_for_observed_weather_covering_every_scorable_window() -> None:
    requirements = task_type.requirements(PARAMS)

    assert requirements.weather is WeatherInput.OBSERVED
    assert requirements.lookback_hours == WINDOW_HOURS + 168


def test_training_records_synthetic_anomaly_recall_and_clean_false_positive_rate(
    trained,
) -> None:
    metrics = trained.metrics

    assert {
        "threshold",
        "false_positive_rate",
        "recall",
        "recall_sudden_drop",
        "recall_pattern_swap",
        "recall_level_shift",
    } <= set(metrics)
    assert metrics["threshold"] > 0.0
    # 門檻取校準日驗證窗的 P99；乾淨的保留日誤報率應在健康上限內。
    assert metrics["false_positive_rate"] <= 0.05
    for kind in ("sudden_drop", "pattern_swap", "level_shift"):
        assert metrics[f"recall_{kind}"] >= 0.8, kind
    assert metrics["recall"] == pytest.approx(
        np.mean([metrics[f"recall_{k}"] for k in ("sudden_drop", "pattern_swap", "level_shift")])
    )


def _holdout_days(validation_start: pd.Timestamp) -> list[pd.Timestamp]:
    """Alternate validation windows by end-hour date, reserving odd-indexed days for holdout."""
    days = pd.date_range(validation_start.normalize(), ANCHOR.normalize(), freq="D")
    return list(days[1::2])


def test_false_positive_rate_is_measured_on_days_the_threshold_never_saw(trained) -> None:
    """A holdout-day midnight drop affects only holdout windows and must change false positive rate, not threshold."""
    data = _training_data()
    holdout_midnights = data.load["datetime"].isin(_holdout_days(data.validation_start))
    spiked = data.load.assign(
        load_mw=data.load["load_mw"].where(~holdout_midnights, data.load["load_mw"] * 0.5)
    )

    result = task_type.train(PARAMS, replace(data, load=spiked))

    assert result.metrics["threshold"] == pytest.approx(trained.metrics["threshold"])
    assert result.metrics["false_positive_rate"] > 0.5


def test_validation_within_a_single_day_measures_nothing_so_health_warns() -> None:
    """Calibration days alone provide no holdout for false positive rate or recall; do not report healthy metrics."""
    thresholds = task_type.health_model.model_validate(THRESHOLDS)

    result = task_type.train(PARAMS, _training_data(validation_start=ANCHOR.normalize()))

    assert "false_positive_rate" not in result.metrics
    assert "recall" not in result.metrics
    assert result.metrics["validation_windows"] == 0.0
    assert task_type.assess_health(thresholds, result.metrics).status is HealthStatus.WARNING


def test_threshold_follows_the_configured_quantile_of_validation_errors(trained) -> None:
    median_params = PARAMS.model_copy(update={"threshold_quantile": 0.5})

    median = task_type.train(median_params, _training_data())

    assert median.metrics["threshold"] < trained.metrics["threshold"]
    assert median.metrics["false_positive_rate"] > trained.metrics["false_positive_rate"]


def test_predicts_the_latest_window_end_hours_up_to_the_anchor(trained) -> None:
    predictions = trained.model.predict(_prediction_data(horizon_hours=6))

    assert list(predictions.columns) == ["datetime", "anomaly_score", "is_anomaly", "threshold"]
    assert list(predictions["datetime"]) == _hours_before_anchor(5, 4, 3, 2, 1, 0)
    assert (predictions["threshold"] == trained.metrics["threshold"]).all()
    assert (
        predictions["is_anomaly"] == (predictions["anomaly_score"] > predictions["threshold"])
    ).all()


def test_without_a_horizon_every_window_in_the_history_is_scored(trained) -> None:
    predictions = trained.model.predict(_prediction_data(horizon_hours=None))

    assert len(predictions) == PARAMS.lookback_hours + 1 - (WINDOW_HOURS - 1)


def test_a_sudden_drop_ending_at_the_anchor_is_flagged(trained) -> None:
    data = _prediction_data(horizon_hours=1)
    history = data.load_history.copy()
    latest_hours = history["datetime"] > ANCHOR - pd.Timedelta(hours=6)
    history.loc[latest_hours, "load_mw"] *= 0.75

    clean = trained.model.predict(data)
    dropped = trained.model.predict(replace(data, load_history=history))

    assert not clean["is_anomaly"].iloc[0]
    assert dropped["is_anomaly"].iloc[0]
    assert dropped["anomaly_score"].iloc[0] > clean["anomaly_score"].iloc[0]


def test_windows_touching_a_weather_gap_beyond_two_hours_are_not_scored(trained) -> None:
    """Weather fills at most two past hours; windows touching a three-hour gap are not scored with constants."""
    data = _prediction_data(horizon_hours=12)
    gap = data.weather["datetime"].isin(_hours_before_anchor(10, 9, 8))

    predictions = trained.model.predict(replace(data, weather=data.weather[~gap]))

    assert list(predictions["datetime"]) == _hours_before_anchor(11, 10, 9)


def test_missing_weather_field_fails_instead_of_using_a_constant(trained) -> None:
    data = _prediction_data(horizon_hours=1)

    with pytest.raises(KeyError, match="relative_humidity"):
        trained.model.predict(replace(data, weather=data.weather.drop(columns="relative_humidity")))


def test_saved_model_reloads_without_pickle_and_predicts_identically(
    trained, tmp_path: Path
) -> None:
    data = _prediction_data(horizon_hours=24)
    directory = tmp_path / "model"

    trained.model.save(directory)
    reloaded = task_type.load(directory)

    pd.testing.assert_frame_equal(reloaded.predict(data), trained.model.predict(data))
    assert sorted(path.name for path in directory.iterdir()) == ["metadata.json", "model.npz"]
    with np.load(directory / "model.npz", allow_pickle=False) as arrays:
        assert all(arrays[name].dtype != object for name in arrays.files)


def test_loading_a_model_of_another_task_type_fails(trained, tmp_path: Path) -> None:
    directory = tmp_path / "model"
    trained.model.save(directory)
    metadata = directory / "metadata.json"
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace(
            '"unsupervised_reconstruction"', '"recursive_regression"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recursive_regression"):
        task_type.load(directory)


def test_too_few_validation_windows_refuses_to_train() -> None:
    after_last_row = ANCHOR + pd.Timedelta(hours=1)

    with pytest.raises(ValueError, match="validation windows"):
        task_type.train(PARAMS, _training_data(validation_start=after_last_row))


def test_no_training_windows_refuses_to_train() -> None:
    first_window_end = ANCHOR - pd.Timedelta(hours=TRAINING_HOURS - WINDOW_HOURS)

    with pytest.raises(ValueError, match="training windows"):
        task_type.train(PARAMS, _training_data(validation_start=first_window_end))


# --- Health --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recall", "false_positive_rate", "expected"),
    [
        (0.8, 0.05, HealthStatus.HEALTHY),
        (0.79, 0.01, HealthStatus.WARNING),
        (0.95, 0.06, HealthStatus.WARNING),
    ],
)
def test_health_requires_minimum_recall_and_maximum_false_positive_rate(
    recall: float, false_positive_rate: float, expected: HealthStatus
) -> None:
    thresholds = task_type.health_model.model_validate(THRESHOLDS)

    assessment = task_type.assess_health(
        thresholds, {"recall": recall, "false_positive_rate": false_positive_rate}
    )

    assert assessment.status is expected
    assert "min_recall" in assessment.reason
    assert "max_false_positive_rate" in assessment.reason


@pytest.mark.parametrize("missing", ["recall", "false_positive_rate"])
def test_health_without_a_required_metric_warns_instead_of_passing(missing: str) -> None:
    thresholds = task_type.health_model.model_validate(THRESHOLDS)
    metrics = {"recall": 0.9, "false_positive_rate": 0.01}
    del metrics[missing]

    assessment = task_type.assess_health(thresholds, metrics)

    assert assessment.status is HealthStatus.WARNING
    assert missing in assessment.reason


# --- boundary inputs -----------------------------------------------------------------------


@pytest.mark.parametrize("constant", [70.1, 0.1, 1e-9, 31234.567, 0.0])
def test_scaler_keeps_scale_one_for_a_constant_feature(constant: float) -> None:
    """The std of a repeated inexact float is round-off, not zero; it must not become the scale."""
    features = np.column_stack([np.full(537, constant), np.linspace(0.0, 1.0, 537)])

    scaler = _Scaler.fit(features)

    assert scaler.scale[0] == 1.0
    assert scaler.scale[1] == pytest.approx(features[:, 1].std())
    moved = scaler.transform(np.array([[constant + 0.1, 0.5]]))
    assert moved[0, 0] == pytest.approx(0.1)


def test_a_sensor_stuck_through_training_does_not_flag_every_later_reading(
    tmp_path: Path,
) -> None:
    data = _training_data()
    stuck = replace(data, weather=data.weather.assign(relative_humidity=70.1))
    model = task_type.train(PARAMS, stuck).model
    serving = _prediction_data(horizon_hours=24)
    weather = serving.weather.assign(relative_humidity=70.1)
    weather.loc[weather["datetime"] == ANCHOR, "relative_humidity"] = 70.2

    scored = model.predict(replace(serving, weather=weather))

    assert scored["anomaly_score"].max() < 100 * model.threshold
    assert not scored["is_anomaly"].all()


@pytest.mark.parametrize("window_hours", [6, 7, 12, 24, 36])
def test_pattern_swap_changes_the_window_whatever_its_length(window_hours: int) -> None:
    """A swap that returns the same window measures the false positive rate, not recall."""
    load = np.arange(window_hours, dtype=float).reshape(1, -1)
    features = np.hstack([load, np.full((1, 4), 9.0)])

    swapped = SYNTHETIC_ANOMALIES["pattern_swap"](features, window_hours)

    assert not np.array_equal(swapped[:, :window_hours], load)
    assert sorted(swapped[0, :window_hours]) == sorted(load[0])
    assert np.array_equal(swapped[:, window_hours:], features[:, window_hours:])


def test_pattern_swap_still_shifts_a_day_long_window_by_twelve_hours() -> None:
    load = np.arange(24, dtype=float).reshape(1, -1)

    swapped = SYNTHETIC_ANOMALIES["pattern_swap"](load, 24)

    assert np.array_equal(swapped, np.roll(load, 12, axis=1))
