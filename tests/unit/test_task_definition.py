"""Task definition loading: tomllib + two-stage Pydantic validation, failing at load time."""

from pathlib import Path

import pytest

from shiro_mlops.data.cwa_client import DEFAULT_CWA_LOCATIONS
from shiro_mlops.tasks.definition import (
    TaskDefinitionError,
    build_weather_spec,
    load_task_definition,
    load_task_definitions,
)
from shiro_mlops.tasks.deployed import TASK_DEFINITIONS_DIR

VALID_DEFINITION = """
task_id = "{task_id}"
task_type = "recursive_regression"
subject = "nationwide"
target = "hourly_actual_load"

[weather]
reference_points = {reference_points}
fields = ["temperature", "relative_humidity"]

[policies]
min_training_hours = 672
stale_anchor_max_lag_hours = {stale_lag}
validation_fraction = 0.2

[params]
lags = [1, 2, 24]
rolling_windows = [6]

[params.model]
n_estimators = 100
learning_rate = 0.05
num_leaves = 31

[schedule]
training = "{training_cron}"
monitoring = "0 * * * *"

[health]
max_mape = 10.0
"""


def _write(tmp_path: Path, text: str, name: str = "sample_task") -> Path:
    path = tmp_path / f"{name}.toml"
    path.write_text(text, encoding="utf-8")
    return path


def _definition(**overrides: str) -> str:
    values = {
        "task_id": "sample_task",
        "reference_points": '["Taipei"]',
        "stale_lag": "3",
        "training_cron": "0 0 * * *",
    }
    return VALID_DEFINITION.format(**(values | overrides))


def test_shipped_definition_describes_the_dynamic_horizon_forecast() -> None:
    tasks = load_task_definitions(TASK_DEFINITIONS_DIR, DEFAULT_CWA_LOCATIONS)
    task = tasks["dynamic_horizon_forecast"]

    assert task.task_type == "recursive_regression"
    assert task.subject == "nationwide"
    assert task.target == "hourly_actual_load"
    assert [point.location for point in task.weather.reference_points] == [
        DEFAULT_CWA_LOCATIONS["Taipei"]
    ]
    assert task.weather.fields == ("temperature", "relative_humidity")
    assert task.policies.min_training_hours == 672
    assert task.policies.stale_anchor_max_lag_hours == 3
    assert task.params.lags == [1, 2, 24, 48, 168]
    assert task.params.rolling_windows == [6, 24]
    assert task.schedule.training == "0 0 * * *"
    assert task.schedule.monitoring == "0 * * * *"
    assert task.health.max_mape == 10.0


def test_shipped_definition_describes_the_high_load_alert() -> None:
    """The P90 threshold needs a complete prior 28-day window for each label, so training needs twice that span."""
    task = load_task_definitions(TASK_DEFINITIONS_DIR, DEFAULT_CWA_LOCATIONS)["high_load_alert"]

    assert task.task_type == "direct_classification"
    assert task.subject == "nationwide"
    assert [point.location for point in task.weather.reference_points] == [
        DEFAULT_CWA_LOCATIONS["Taipei"]
    ]
    assert task.weather.fields == ("temperature", "relative_humidity")
    assert task.params.threshold.window_days == 28
    assert task.params.threshold.quantile == 0.9
    assert task.policies.min_training_hours == 1344
    assert task.policies.stale_anchor_max_lag_hours == 3
    assert task.params.lookback_hours >= 672 + max(task.params.lags)
    assert task.health.min_precision > 0.0
    assert task.health.min_recall > 0.0
    assert task.health.min_f1 > 0.0


def test_shipped_tasks_train_at_distinct_times() -> None:
    """Stagger task training because each run reads full history and competes for database and CPU capacity."""
    tasks = load_task_definitions(TASK_DEFINITIONS_DIR, DEFAULT_CWA_LOCATIONS)

    crons = {task_id: task.schedule.training for task_id, task in tasks.items()}

    assert len(set(crons.values())) == len(crons), crons
    assert crons["load_pattern_anomaly"] == "0 1 * * *"


def test_missing_required_field_names_file_and_field(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition().replace('subject = "nationwide"\n', ""))

    with pytest.raises(TaskDefinitionError, match="subject") as error:
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert error.value.path == path


def test_missing_task_type_param_names_the_params_field(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition().replace("rolling_windows = [6]\n", ""))

    with pytest.raises(TaskDefinitionError, match=r"params\.rolling_windows"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_a_task_may_declare_a_subset_of_the_weather_fields(tmp_path: Path) -> None:
    """Prediction weather fields follow weather.fields without a fixed task-type field set."""
    only_temperature = _definition().replace(
        'fields = ["temperature", "relative_humidity"]', 'fields = ["temperature"]'
    )
    path = _write(tmp_path, only_temperature)

    task = load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert task.weather.fields == ("temperature",)


def test_a_weather_field_listed_twice_is_rejected_at_load(tmp_path: Path) -> None:
    """A repeated field would otherwise surface as a shape error in the middle of training."""
    repeated = _definition().replace(
        'fields = ["temperature", "relative_humidity"]', 'fields = ["temperature", "temperature"]'
    )
    path = _write(tmp_path, repeated)

    with pytest.raises(TaskDefinitionError, match="weather.*field.*more than once"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_unknown_task_type_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition().replace("recursive_regression", "time_travel"))

    with pytest.raises(TaskDefinitionError, match="task_type.*time_travel"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_unknown_weather_reference_point_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition(reference_points='["Atlantis"]'))

    with pytest.raises(TaskDefinitionError, match="weather.reference_points.*Atlantis"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_weighted_reference_points_resolve_with_their_weights(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _definition(
            reference_points='["Taipei", "Taichung", "Kaohsiung"]\nweights = [0.5, 0.3, 0.2]'
        ),
    )

    task = load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert [(point.location.alias, point.weight) for point in task.weather.reference_points] == [
        ("Taipei", 0.5),
        ("Taichung", 0.3),
        ("Kaohsiung", 0.2),
    ]


@pytest.mark.parametrize("weather", ['["Taipei"]', '["Taipei"]\nweights = [1.0]'])
def test_single_reference_point_has_weight_one(tmp_path: Path, weather: str) -> None:
    path = _write(tmp_path, _definition(reference_points=weather))

    task = load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert [(point.location, point.weight) for point in task.weather.reference_points] == [
        (DEFAULT_CWA_LOCATIONS["Taipei"], 1.0)
    ]


@pytest.mark.parametrize(
    ("weather", "message"),
    [
        ('["Taipei", "Kaohsiung"]', "weights"),
        ('["Taipei", "Kaohsiung"]\nweights = [0.6, 0.6]', "sum to 1"),
        ('["Taipei", "Kaohsiung"]\nweights = [1.2, -0.2]', "greater than 0"),
        ('["Taipei", "Kaohsiung"]\nweights = [0.0, 1.0]', "greater than 0"),
        ('["Taipei", "Kaohsiung"]\nweights = [1.0]', "one weight per reference point"),
        ('["Taipei", "Taipei"]\nweights = [0.5, 0.5]', "more than once"),
    ],
)
def test_invalid_reference_point_weights_fail_at_load(
    tmp_path: Path, weather: str, message: str
) -> None:
    path = _write(tmp_path, _definition(reference_points=weather))

    with pytest.raises(TaskDefinitionError, match=f"weather.*{message}"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_weather_spec_built_outside_a_task_file_resolves_weights() -> None:
    weather = build_weather_spec(
        ["Taipei", "Taichung", "Kaohsiung"],
        [0.5, 0.3, 0.2],
        ["temperature"],
        DEFAULT_CWA_LOCATIONS,
    )

    assert [(point.location.alias, point.weight) for point in weather.reference_points] == [
        ("Taipei", 0.5),
        ("Taichung", 0.3),
        ("Kaohsiung", 0.2),
    ]
    assert weather.fields == ("temperature",)


@pytest.mark.parametrize(
    ("points", "weights", "message"),
    [
        (["Taipei", "Kaohsiung"], [0.6, 0.6], "sum to 1"),
        (["Taipei", "Kaohsiung"], None, "need weights"),
        (["Taipei", "Atlantis"], [0.5, 0.5], "Atlantis"),
    ],
)
def test_weather_spec_built_outside_a_task_file_uses_the_task_file_rules(
    points: list[str], weights: list[float] | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_weather_spec(points, weights, ["temperature"], DEFAULT_CWA_LOCATIONS)


def test_task_id_must_match_the_file_name(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition(task_id="other_task"))

    with pytest.raises(TaskDefinitionError, match="task_id.*sample_task"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_non_positive_stale_anchor_lag_is_rejected(tmp_path: Path) -> None:
    """A nonpositive stale-anchor lag would silently reject every forecast."""
    path = _write(tmp_path, _definition(stale_lag="0"))

    with pytest.raises(TaskDefinitionError, match="policies.stale_anchor_max_lag_hours"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_malformed_toml_names_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "task_id = ")

    with pytest.raises(TaskDefinitionError) as error:
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert error.value.path == path


def test_missing_schedule_section_is_rejected(tmp_path: Path) -> None:
    text = _definition().replace(
        '[schedule]\ntraining = "0 0 * * *"\nmonitoring = "0 * * * *"\n', ""
    )
    path = _write(tmp_path, text)

    with pytest.raises(TaskDefinitionError, match="schedule"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


@pytest.mark.parametrize("cron", ["0 24 * * *", "every day", "0 0 * *", "*/0 * * * *"])
def test_invalid_training_cron_names_the_schedule_field(tmp_path: Path, cron: str) -> None:
    path = _write(tmp_path, _definition(training_cron=cron))

    with pytest.raises(TaskDefinitionError, match=r"schedule\.training"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


@pytest.mark.parametrize("cron", ["*/15 8-18 * * 1-5", "0,30 0 1 1,6 *"])
def test_cron_lists_ranges_and_steps_are_accepted(tmp_path: Path, cron: str) -> None:
    task = load_task_definition(
        _write(tmp_path, _definition(training_cron=cron)), DEFAULT_CWA_LOCATIONS
    )

    assert task.schedule.training == cron


def test_missing_health_threshold_names_the_health_field(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition().replace("max_mape = 10.0\n", ""))

    with pytest.raises(TaskDefinitionError, match=r"health\.max_mape"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)
