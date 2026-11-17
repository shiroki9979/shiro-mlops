# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # `dynamic_horizon_forecast` 加權天氣與放假日採用研究 (TICKET-303)
#
# 比較四個候選在相同起點上的滾動起點回測（GitHub #98）：
#
# | 候選 | 天氣 | 放假日 | 快照 |
# | :--- | :--- | :--- | :--- |
# | `baseline` | 臺北 | 關 | 基線快照 |
# | `day_off` | 臺北 | 開 | 基線快照 |
# | `three_point` | 臺北／臺中／高雄加權 | 關 | `three-point` variant |
# | `three_point_day_off` | 臺北／臺中／高雄加權 | 開 | `three-point` variant |
#
# 起點取兩份快照合格起點的交集，評估起點為最後 7 個日曆日，搜尋起點為更早且目標時段不重疊者。
# 在搜尋起點上選出最佳候選，只有評估起點涵蓋至少 7 個日曆日、且最佳候選在評估起點贏過基線時才採用。
# 不足 7 日時改以一半的日曆日作為評估起點，只產出探索結果。
#
# 執行前先依 `docs/how-to/run-lab-study.md` 推算權重並凍結兩份快照，再執行：
#
# ```bash
# uv run --package lab python lab/2026-11-17-dhf-weather-calendar/study.py --as-of <as_of> --weights <w_taipei> <w_taichung> <w_kaohsiung>
# ```

# %%
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import mlflow
import pandas as pd
from mlflow.exceptions import MlflowException
from shiro_mlops.core.config import settings
from shiro_mlops.pipelines.tracking import flatten_params
from shiro_mlops.tasks.definition import TaskDefinition, build_weather_spec
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.types.base import TrainingData

# `lab` is a non-packaged uv workspace member, so it is importable only when the repo root is
# on sys.path. `python -m lab.snapshot` gets that from the cwd, but a script inside a dated topic
# folder (or its paired notebook, whose kernel starts in this folder) does not.
_SEARCH_START = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
_REPO_ROOT = next(
    path
    for path in (_SEARCH_START, *_SEARCH_START.parents)
    if (path / "lab" / "__init__.py").is_file()
)
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lab.backtest import (  # noqa: E402
    BacktestReport,
    OriginSplit,
    eligible_origins,
    rolling_origin_backtest,
    split_search_and_eval_origins,
    training_row_count,
)
from lab.snapshot import DEFAULT_SNAPSHOTS_DIR, read_snapshot, snapshot_path  # noqa: E402

logger = logging.getLogger(__name__)

# %% [markdown]
# ## 1. 實驗常數

# %%
HORIZON_HOURS = 24
# 採用判定要求評估起點至少涵蓋 7 個日曆日（GitHub #92、#98）。
MIN_EVAL_CALENDAR_DAYS = 7
# 起點每 6 小時取一個整點，與 2026-11-08 研究一致。
HOUR_STEP = 6
THREE_POINTS = ("Taipei", "Taichung", "Kaohsiung")
VARIANT = "three-point"
MLFLOW_EXPERIMENT_NAME = "lab/dhf-weather-calendar"
REPORT_DECIMALS = 4
BASELINE = "baseline"


# %% [markdown]
# ## 2. 候選與快照


# %%
@dataclass(frozen=True)
class Candidate:
    """One task variant and the snapshot it is backtested on."""

    name: str
    task: TaskDefinition
    data: TrainingData
    snapshot: Path
    snapshot_sha256: str


def _with_day_off(task: TaskDefinition) -> TaskDefinition:
    return replace(task, params=task.params.model_copy(update={"day_off": True}))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candidates(as_of: str, weights: Sequence[float], snapshots_dir: Path) -> list[Candidate]:
    """Build the four candidates; day-off candidates share their weather's snapshot."""
    base_task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    weighted_task = replace(
        base_task,
        weather=build_weather_spec(
            THREE_POINTS, weights, base_task.weather.fields, settings.cwa_locations
        ),
    )
    candidates = []
    for task, variant, names in (
        (base_task, None, (BASELINE, "day_off")),
        (weighted_task, VARIANT, ("three_point", "three_point_day_off")),
    ):
        path = snapshot_path(task, as_of, variant=variant, snapshots_dir=snapshots_dir)
        data = read_snapshot(task, as_of, variant=variant, snapshots_dir=snapshots_dir)
        sha256 = _sha256(path)
        plain, day_off = names
        candidates.append(Candidate(plain, task, data, path, sha256))
        candidates.append(Candidate(day_off, _with_day_off(task), data, path, sha256))
    return candidates


# %% [markdown]
# ## 3. 共同起點與搜尋／評估切分


# %%
def common_split(candidates: Sequence[Candidate]) -> tuple[OriginSplit, bool]:
    """Split the origins every candidate accepts; the flag is False for an exploratory split."""
    shared: set[pd.Timestamp] | None = None
    for candidate in candidates:
        accepted = set(eligible_origins(candidate.task, candidate.data, HORIZON_HOURS))
        shared = accepted if shared is None else shared & accepted
    eligible = tuple(sorted(shared or ()))
    try:
        split = split_search_and_eval_origins(
            eligible,
            horizon_hours=HORIZON_HOURS,
            eval_calendar_days=MIN_EVAL_CALENDAR_DAYS,
            hour_step=HOUR_STEP,
        )
    except ValueError as error:
        calendar_days = len({origin.date() for origin in eligible})
        logger.warning("Not enough origins for adoption (%s); running an exploratory split", error)
        split = split_search_and_eval_origins(
            eligible,
            horizon_hours=HORIZON_HOURS,
            eval_calendar_days=max(1, calendar_days // 2),
            hour_step=HOUR_STEP,
        )
    return split, split.eval_calendar_days >= MIN_EVAL_CALENDAR_DAYS


# %% [markdown]
# ## 4. MLflow 紀錄


# %%
def _report_metrics(prefix: str, report: BacktestReport) -> dict[str, float]:
    metrics = {f"{prefix}_overall_mape": float(report.overall_mape)}
    for step, mape in report.mape_by_horizon.items():
        metrics[f"{prefix}_mape_h{step:02d}"] = float(mape)
    return metrics


def log_lab_run(
    run_name: str,
    task: TaskDefinition,
    metrics: Mapping[str, float],
    extra_params: Mapping[str, object],
) -> None:
    """Record a lab run in MLflow without touching the Model Registry; warn and continue on failure."""
    try:
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
        with mlflow.start_run(run_name=run_name):
            mlflow.log_params({**flatten_params(task), **extra_params})
            mlflow.log_metrics({key: float(value) for key, value in metrics.items()})
    # An unreachable tracking server surfaces as MlflowException (MLflow wraps HTTP errors);
    # local file-store failures are OSError. Anything else is a programming error and must raise.
    except (MlflowException, OSError) as exc:
        logger.warning("MLflow unavailable when logging run %s; continuing: %s", run_name, exc)


# %% [markdown]
# ## 5. 回測、選擇與採用判定


# %%
@dataclass(frozen=True)
class CandidateResult:
    candidate: Candidate
    search: BacktestReport
    eval: BacktestReport
    training_rows: int


def evaluate(candidate: Candidate, split: OriginSplit, as_of: str) -> CandidateResult:
    search = rolling_origin_backtest(
        candidate.task, candidate.data, origins=split.search_origins, horizon_hours=HORIZON_HOURS
    )
    eval_report = rolling_origin_backtest(
        candidate.task, candidate.data, origins=split.eval_origins, horizon_hours=HORIZON_HOURS
    )
    # 訓練列數取最後一個評估起點，揭露三點嚴格缺值造成的訓練列損失。
    rows = training_row_count(candidate.task, candidate.data, split.eval_origins[-1])
    log_lab_run(
        run_name=candidate.name,
        task=candidate.task,
        metrics={
            **_report_metrics("search", search),
            **_report_metrics("eval", eval_report),
            "training_rows": rows,
        },
        extra_params={
            "candidate": candidate.name,
            "as_of": as_of,
            "snapshot_sha256": candidate.snapshot_sha256,
            "horizon_hours": HORIZON_HOURS,
        },
    )
    return CandidateResult(candidate, search, eval_report, rows)


def _round(value: float) -> float:
    return round(float(value), REPORT_DECIMALS)


def _summarize(result: CandidateResult) -> dict[str, object]:
    task = result.candidate.task
    return {
        "weather": [[p.location.alias, p.weight] for p in task.weather.reference_points],
        "day_off": task.params.day_off,
        "snapshot": str(result.candidate.snapshot),
        "snapshot_sha256": result.candidate.snapshot_sha256,
        "training_rows": result.training_rows,
        "search_overall_mape": _round(result.search.overall_mape),
        "eval_overall_mape": _round(result.eval.overall_mape),
        "search_mape_by_horizon": {k: _round(v) for k, v in result.search.mape_by_horizon.items()},
        "eval_mape_by_horizon": {k: _round(v) for k, v in result.eval.mape_by_horizon.items()},
    }


def run_study(
    as_of: str, weights: Sequence[float], snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR
) -> dict[str, object]:
    candidates = load_candidates(as_of, weights, snapshots_dir)
    split, adoption_eligible = common_split(candidates)
    results = {candidate.name: evaluate(candidate, split, as_of) for candidate in candidates}
    baseline = results[BASELINE]
    best = min(
        (result for name, result in results.items() if name != BASELINE),
        key=lambda result: result.search.overall_mape,
    )
    beats = best.eval.beats(baseline.eval)
    return {
        "as_of": as_of,
        "weights": dict(zip(THREE_POINTS, weights, strict=True)),
        "horizon_hours": HORIZON_HOURS,
        "search_origins": [origin.isoformat() for origin in split.search_origins],
        "eval_origins": [origin.isoformat() for origin in split.eval_origins],
        "eval_calendar_days": split.eval_calendar_days,
        "adoption_eligible": adoption_eligible,
        "candidates": {name: _summarize(result) for name, result in results.items()},
        "best_candidate_on_search": best.candidate.name,
        "best_beats_baseline_on_eval": beats,
        "adopt": adoption_eligible and beats,
    }


# %% [markdown]
# ## 6. 執行入口


# %%
def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, dest="as_of", help="Snapshot as_of (ISO).")
    parser.add_argument(
        "--weights",
        nargs=len(THREE_POINTS),
        type=float,
        required=True,
        help="Weights for Taipei, Taichung and Kaohsiung (from lab.regional_weights).",
    )
    parser.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    parser.add_argument("--output", type=Path, help="Also write the JSON summary to this path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv)
    summary = run_study(args.as_of, args.weights, args.snapshots_dir)
    text = json.dumps(summary, ensure_ascii=False, indent=2)
    print(text)
    if args.output is not None:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
