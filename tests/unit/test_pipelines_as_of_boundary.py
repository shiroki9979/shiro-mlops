"""#287: Dagster definitions under pipelines/ get their as_of only from the execution origin module.

Outside ``execution_origin.py``, no module under ``pipelines/`` may take the current time
itself, read the schedule tick, or read the schedule-name or re-execution tags. A new
scheduled asset with an as_of therefore declares ``WithoutTick`` and calls ``run_as_of``
instead of growing its own tick config field and parser.
"""

import ast

import pytest

from tests.source_scan import REPO_ROOT, SRC_DIR, scan_sources

PIPELINES_DIR = SRC_DIR / "shiro_mlops" / "pipelines"
EXECUTION_ORIGIN = "src/shiro_mlops/pipelines/execution_origin.py"
# 唯一例外：smoke check 是操作人員在容器內執行的 CLI，不在 Dagster run 裡，沒有 run 標籤
# 或 run 建立時刻可解析；它以現在時刻當作 tick 評估各排程，檢查此刻部署會不會發起 run。
EXCEPTIONS = {"src/shiro_mlops/pipelines/smoke_check.py"}

# 現在時刻的來源：專案的 taiwan_now 與 datetime、date、pandas Timestamp 的同義寫法。
NOW_FUNCTIONS = frozenset({"taiwan_now"})
NOW_METHODS = {
    "datetime": frozenset({"now", "utcnow", "today"}),
    "date": frozenset({"today"}),
    "Timestamp": frozenset({"now", "utcnow", "today"}),
}
# Dagster 的排程 tick 與 run 的 parent / root run id 屬性。
TICK_AND_LINEAGE_ATTRIBUTES = frozenset(
    {"scheduled_execution_time", "parent_run_id", "root_run_id"}
)
# 排程名稱、run key、重新執行與 tick 標籤：字串本身，以及 Dagster 與執行來源 module 的常數名。
RUN_TAG_VALUES = frozenset(
    {
        "dagster/schedule_name",
        "dagster/run_key",
        "dagster/parent_run_id",
        "dagster/root_run_id",
        ".dagster/scheduled_execution_time",
        "shiro_mlops/scheduled_tick",
    }
)
RUN_TAG_CONSTANTS = frozenset(
    {
        "SCHEDULE_NAME_TAG",
        "RUN_KEY_TAG",
        "PARENT_RUN_ID_TAG",
        "ROOT_RUN_ID_TAG",
        "SCHEDULED_EXECUTION_TIME_TAG",
        "SCHEDULED_TICK_TAG",
        "REEXECUTION_TAGS",
    }
)


def _is_now_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id in NOW_FUNCTIONS
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in NOW_FUNCTIONS:
        return True
    owner = func.value
    owner_name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
    return func.attr in NOW_METHODS.get(owner_name, frozenset())


def _as_of_violations(source: str) -> list[str]:
    """Return ``line: what`` for each place that takes now or reads the tick or run tags."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and _is_now_call(node.func):
            found.append((node.lineno, f"takes the current time: {ast.unparse(node.func)}()"))
        elif isinstance(node, ast.Attribute) and node.attr in TICK_AND_LINEAGE_ATTRIBUTES:
            found.append((node.lineno, f"reads {node.attr}"))
        elif isinstance(node, ast.Attribute) and node.attr in RUN_TAG_CONSTANTS:
            found.append((node.lineno, f"reads run tag {node.attr}"))
        elif isinstance(node, ast.keyword) and node.arg in TICK_AND_LINEAGE_ATTRIBUTES:
            found.append((node.value.lineno, f"passes {node.arg}"))
        elif isinstance(node, ast.Constant) and node.value in RUN_TAG_VALUES:
            found.append((node.lineno, f"reads run tag {node.value}"))
        elif isinstance(node, ast.Name) and node.id in RUN_TAG_CONSTANTS:
            found.append((node.lineno, f"reads run tag {node.id}"))
        elif isinstance(node, ast.alias) and node.name.split(".")[-1] in RUN_TAG_CONSTANTS:
            found.append((node.lineno, f"imports run tag {node.name}"))
    return [f"{line}: {what}" for line, what in sorted(found)]


def _pipelines_violations() -> dict[str, list[str]]:
    return scan_sources(PIPELINES_DIR, lambda path, source: _as_of_violations(source))


def test_pipelines_take_now_and_the_tick_only_through_the_execution_origin_module() -> None:
    offenders = {
        path: violations
        for path, violations in _pipelines_violations().items()
        if path != EXECUTION_ORIGIN and path not in EXCEPTIONS
    }

    assert offenders == {}


def test_every_listed_exception_still_takes_now_or_reads_the_tick() -> None:
    """An exception that no longer needs it is removed, not left to hide a future violation."""
    assert all((REPO_ROOT / path).is_file() for path in EXCEPTIONS | {EXECUTION_ORIGIN})
    assert EXCEPTIONS <= _pipelines_violations().keys()


@pytest.mark.parametrize(
    "source",
    [
        "from shiro_mlops.core.datetime_utils import taiwan_now\nas_of = taiwan_now()",
        "from shiro_mlops.core import datetime_utils\nas_of = datetime_utils.taiwan_now()",
        "from datetime import datetime\nas_of = datetime.now()",
        "import datetime\nas_of = datetime.datetime.now(tz=None)",
        "from datetime import datetime\nas_of = datetime.utcnow()",
        "from datetime import date\nday = date.today()",
        "import pandas as pd\nas_of = pd.Timestamp.now()",
        "def tick(context):\n    return context.scheduled_execution_time",
        "context = build_schedule_context(scheduled_execution_time=tick)",
        "def origin(context):\n    return context.run.parent_run_id",
        "def scheduled(context):\n    return 'dagster/schedule_name' in context.run.tags",
        "def rerun(tags):\n    return tags.get('dagster/root_run_id')",
        "def tick(tags):\n    return tags['shiro_mlops/scheduled_tick']",
        "from dagster._core.storage.tags import SCHEDULE_NAME_TAG",
        "from shiro_mlops.pipelines.execution_origin import SCHEDULED_TICK_TAG",
        "from shiro_mlops.pipelines import execution_origin\n"
        "rerun = execution_origin.REEXECUTION_TAGS",
    ],
)
def test_scan_flags_taking_now_or_reading_the_tick_and_run_tags(source: str) -> None:
    assert _as_of_violations(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from shiro_mlops.pipelines.execution_origin import WithoutTick, run_as_of\n"
        "def asset(context):\n"
        "    return run_as_of(context, without_tick=WithoutTick.FALL_BACK_TO_NOW)",
        "from shiro_mlops.pipelines.execution_origin import tick_run_request\n"
        "def schedule(context):\n    return tick_run_request(context)",
        "from datetime import datetime, timedelta\n"
        "start = datetime(2026, 11, 20) - timedelta(hours=1)",
        "def running_schedule_names(instance):\n    return frozenset()",
        "note = 'the schedule tick'",
    ],
)
def test_scan_allows_the_module_api_and_plain_datetime_arithmetic(source: str) -> None:
    assert _as_of_violations(source) == []
