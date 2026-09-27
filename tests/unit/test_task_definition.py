"""Task definition loading: tomllib + two-stage Pydantic validation, failing at load time."""

from pathlib import Path

import pytest

from shiro_mlops.data.cwa_client import DEFAULT_CWA_LOCATIONS
from shiro_mlops.tasks.definition import (
    TaskDefinitionError,
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
    assert task.weather.reference_point == DEFAULT_CWA_LOCATIONS["Taipei"]
    assert task.weather.fields == ("temperature", "relative_humidity")
    assert task.policies.min_training_hours == 672
    assert task.policies.stale_anchor_max_lag_hours == 3
    assert task.params.lags == [1, 2, 24, 48, 168]
    assert task.params.rolling_windows == [6, 24]
    assert task.schedule.training == "0 0 * * *"
    assert task.schedule.monitoring == "0 * * * *"
    assert task.health.max_mape == 10.0


def test_shipped_definition_describes_the_high_load_alert() -> None:
    """門檻為錨點前 28 日的 P90；每筆標籤前都需完整門檻窗，故最低累積為兩倍門檻窗。"""
    task = load_task_definitions(TASK_DEFINITIONS_DIR, DEFAULT_CWA_LOCATIONS)["high_load_alert"]

    assert task.task_type == "direct_classification"
    assert task.subject == "nationwide"
    assert task.weather.reference_point == DEFAULT_CWA_LOCATIONS["Taipei"]
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
    """各任務訓練都讀完整歷史，同一時刻啟動會互搶資料庫與 CPU。"""
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
    """預測 item 的天氣欄位跟隨 weather.fields，任務類型不強制特定天氣欄位。"""
    only_temperature = _definition().replace(
        'fields = ["temperature", "relative_humidity"]', 'fields = ["temperature"]'
    )
    path = _write(tmp_path, only_temperature)

    task = load_task_definition(path, DEFAULT_CWA_LOCATIONS)

    assert task.weather.fields == ("temperature",)


def test_unknown_task_type_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition().replace("recursive_regression", "time_travel"))

    with pytest.raises(TaskDefinitionError, match="task_type.*time_travel"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_unknown_weather_reference_point_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition(reference_points='["Atlantis"]'))

    with pytest.raises(TaskDefinitionError, match="weather.reference_points.*Atlantis"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_more_than_one_weather_reference_point_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition(reference_points='["Taipei", "Kaohsiung"]'))

    with pytest.raises(TaskDefinitionError, match="weather.reference_points.*not supported yet"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_task_id_must_match_the_file_name(tmp_path: Path) -> None:
    path = _write(tmp_path, _definition(task_id="other_task"))

    with pytest.raises(TaskDefinitionError, match="task_id.*sample_task"):
        load_task_definition(path, DEFAULT_CWA_LOCATIONS)


def test_non_positive_stale_anchor_lag_is_rejected(tmp_path: Path) -> None:
    """零或負值會讓每個起點都過舊，服務將無聲地永久拒絕預報。"""
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
