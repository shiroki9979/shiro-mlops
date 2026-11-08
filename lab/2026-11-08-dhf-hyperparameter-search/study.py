# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.4
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # `dynamic_horizon_forecast` 超參數與特徵配方研究 (TICKET-803)
#
# 本 Jupytext 研究腳本針對 `dynamic_horizon_forecast` 在凍結快照
# `data/lab/snapshots/dynamic_horizon_forecast/2026-11-08T22:00:00.parquet` 上：
#
# 1. 以 `SEARCH_ORIGINS`（9 個搜尋起點）執行 Optuna 滾動起點回測搜尋；
# 2. 以 `dataclasses.replace(task, params=...)` 覆寫候選特徵配方（`lags`、`rolling_windows`）與 LightGBM 超參數；
# 3. 將回測紀錄寫入 MLflow experiment `lab/dhf-hyperparameter-search`（不建立任何 registered model 或 model version；MLflow 不可用時記錄警告並繼續）；
# 4. 在預報目標時段與搜尋起點完全不重疊的 `EVAL_ORIGINS`（2 個評估起點）上比較最佳候選與基線，並檢核評估起點數量是否達正式採用門檻。

# %%
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import mlflow
import optuna
import pandas as pd
from shiro_mlops.core.config import settings
from shiro_mlops.pipelines.tracking import flatten_params
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.types.base import TrainingData
from shiro_mlops.tasks.types.lightgbm_common import LightGBMParams
from shiro_mlops.tasks.types.recursive_regression import RecursiveRegressionParams

_REPO_ROOT = Path(__file__).resolve().parents[2] if "__file__" in globals() else Path.cwd()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from lab.backtest import BacktestReport, rolling_origin_backtest  # noqa: E402
from lab.snapshot import DEFAULT_SNAPSHOTS_DIR, read_snapshot  # noqa: E402

logger = logging.getLogger(__name__)

# %% [markdown]
# ## 1. 實驗常數與搜尋空間定義

# %%
AS_OF = "2026-11-08T22:00:00"
HORIZON_HOURS = 24
STUDY_SEED = 42
N_TRIALS = 24
MLFLOW_EXPERIMENT_NAME = "lab/dhf-hyperparameter-search"

# 正式採用判定要求評估起點至少涵蓋 7 個不同日曆日（完整一週之平日與假日負載型態）。
MIN_EVAL_DISTINCT_DAYS = 7

SEARCH_ORIGINS: tuple[pd.Timestamp, ...] = (
    pd.Timestamp("2026-10-26 18:00:00"),
    pd.Timestamp("2026-10-27 00:00:00"),
    pd.Timestamp("2026-10-27 06:00:00"),
    pd.Timestamp("2026-10-27 12:00:00"),
    pd.Timestamp("2026-10-27 18:00:00"),
    pd.Timestamp("2026-10-28 00:00:00"),
    pd.Timestamp("2026-10-28 06:00:00"),
    pd.Timestamp("2026-10-28 12:00:00"),
    pd.Timestamp("2026-10-28 18:00:00"),
)

EVAL_ORIGINS: tuple[pd.Timestamp, ...] = (
    pd.Timestamp("2026-10-29 18:00:00"),
    pd.Timestamp("2026-10-29 22:00:00"),
)

# 所有候選特徵配方的最大滯後／視窗皆維持 <= 168 小時，確保與基線共用同一組有效起點。
LAG_RECIPES: dict[str, list[int]] = {
    "baseline_1_2_24_48_168": [1, 2, 24, 48, 168],
    "short_dense_1_2_3_6_24_48_168": [1, 2, 3, 6, 24, 48, 168],
    "daily_multi_1_2_24_48_72_168": [1, 2, 24, 48, 72, 168],
    "full_1_2_3_6_12_24_48_168": [1, 2, 3, 6, 12, 24, 48, 168],
    "compact_1_2_24_168": [1, 2, 24, 168],
}

ROLLING_WINDOW_RECIPES: dict[str, list[int]] = {
    "baseline_6_24": [6, 24],
    "short_3_6_24": [3, 6, 24],
    "extended_6_24_48": [6, 24, 48],
    "multi_scale_3_6_12_24_48": [3, 6, 12, 24, 48],
    "weekly_6_24_168": [6, 24, 168],
}


# %% [markdown]
# ## 2. 起點不重疊驗證與 MLflow 輔助函式


# %%
def verify_non_overlapping_target_windows(
    search_origins: tuple[pd.Timestamp, ...],
    eval_origins: tuple[pd.Timestamp, ...],
    horizon_hours: int,
) -> None:
    """Confirm that evaluation target windows are strictly later and never overlap search target windows."""
    search_targets = {
        ts
        for origin in search_origins
        for ts in pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon_hours, freq="h")
    }
    eval_targets = {
        ts
        for origin in eval_origins
        for ts in pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon_hours, freq="h")
    }
    overlap = search_targets & eval_targets
    if overlap:
        earliest = min(overlap).isoformat()
        raise ValueError(
            f"Evaluation target window overlaps with search target window (e.g. {earliest})."
        )
    if min(eval_origins) <= max(search_origins):
        raise ValueError("Evaluation origins must be strictly later than all search origins.")


def _report_metrics(prefix: str, report: BacktestReport) -> dict[str, float]:
    metrics = {f"{prefix}_overall_mape": float(report.overall_mape)}
    for step, mape in report.mape_by_horizon.items():
        metrics[f"{prefix}_mape_h{step:02d}"] = float(mape)
    return metrics


def log_lab_run(
    run_name: str,
    task: TaskDefinition,
    metrics: Mapping[str, float],
    extra_params: Mapping[str, object] | None = None,
) -> str | None:
    """Record a lab run in MLflow without touching the Model Registry; warn and continue on failure."""
    try:
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
        with mlflow.start_run(run_name=run_name) as run:
            params_payload = flatten_params(task)
            if extra_params:
                params_payload.update(extra_params)
            mlflow.log_params(params_payload)
            mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
            return str(run.info.run_id)
    except Exception as exc:
        logger.warning(
            "MLflow unavailable when logging run %s; continuing without MLflow: %s",
            run_name,
            exc,
        )
        return None


# %% [markdown]
# ## 3. 候選參數建構與 Optuna Objective


# %%
def build_candidate_task(
    base_task: TaskDefinition,
    *,
    lags_key: str,
    rolling_key: str,
    n_estimators: int,
    learning_rate: float,
    num_leaves: int,
) -> TaskDefinition:
    """Create a candidate TaskDefinition via dataclasses.replace without touching TOML files."""
    candidate_params = RecursiveRegressionParams(
        lags=LAG_RECIPES[lags_key],
        rolling_windows=ROLLING_WINDOW_RECIPES[rolling_key],
        model=LightGBMParams(
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
        ),
    )
    return replace(base_task, params=candidate_params)


def make_objective(
    base_task: TaskDefinition,
    data: TrainingData,
):
    """Build an Optuna objective that ONLY evaluates on SEARCH_ORIGINS."""

    def objective(trial: optuna.Trial) -> float:
        lags_key = trial.suggest_categorical("lags_key", list(LAG_RECIPES.keys()))
        rolling_key = trial.suggest_categorical("rolling_key", list(ROLLING_WINDOW_RECIPES.keys()))
        n_estimators = trial.suggest_int("n_estimators", 50, 250, step=25)
        learning_rate = trial.suggest_float("learning_rate", 0.01, 0.15, log=True)
        num_leaves = trial.suggest_int("num_leaves", 15, 63, step=8)

        candidate_task = build_candidate_task(
            base_task,
            lags_key=lags_key,
            rolling_key=rolling_key,
            n_estimators=n_estimators,
            learning_rate=learning_rate,
            num_leaves=num_leaves,
        )
        report = rolling_origin_backtest(
            candidate_task,
            data,
            origins=SEARCH_ORIGINS,
            horizon_hours=HORIZON_HOURS,
        )
        trial.set_user_attr("mape_by_horizon", report.mape_by_horizon)
        log_lab_run(
            run_name=f"trial_{trial.number:02d}",
            task=candidate_task,
            metrics=_report_metrics("search", report),
            extra_params={
                "trial_number": trial.number,
                "lags_key": lags_key,
                "rolling_key": rolling_key,
                "as_of": AS_OF,
                "horizon_hours": HORIZON_HOURS,
            },
        )
        return float(report.overall_mape)

    return objective


# %% [markdown]
# ## 4. 執行搜尋、評估比較與採用判定


# %%
def run_study(
    *,
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
    n_trials: int = N_TRIALS,
    seed: int = STUDY_SEED,
) -> dict[str, object]:
    """Execute the baseline comparison, Optuna search on SEARCH_ORIGINS, and evaluation on EVAL_ORIGINS."""
    verify_non_overlapping_target_windows(SEARCH_ORIGINS, EVAL_ORIGINS, HORIZON_HOURS)

    base_task = deployed_task(DYNAMIC_HORIZON_FORECAST)
    snapshot_file = Path(snapshots_dir) / base_task.task_id / f"{AS_OF}.parquet"
    snapshot_sha256 = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
    data = read_snapshot(base_task, AS_OF, snapshots_dir=snapshots_dir)

    baseline_search = rolling_origin_backtest(
        base_task, data, origins=SEARCH_ORIGINS, horizon_hours=HORIZON_HOURS
    )
    baseline_eval = rolling_origin_backtest(
        base_task, data, origins=EVAL_ORIGINS, horizon_hours=HORIZON_HOURS
    )
    log_lab_run(
        run_name="baseline",
        task=base_task,
        metrics={
            **_report_metrics("search", baseline_search),
            **_report_metrics("eval", baseline_eval),
        },
        extra_params={
            "role": "baseline",
            "as_of": AS_OF,
            "snapshot_sha256": snapshot_sha256,
            "horizon_hours": HORIZON_HOURS,
        },
    )

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(
        study_name="dhf-hyperparameter-search",
        direction="minimize",
        sampler=sampler,
    )
    study.optimize(make_objective(base_task, data), n_trials=n_trials)

    best_trial = study.best_trial
    best_task = build_candidate_task(
        base_task,
        lags_key=str(best_trial.params["lags_key"]),
        rolling_key=str(best_trial.params["rolling_key"]),
        n_estimators=int(best_trial.params["n_estimators"]),
        learning_rate=float(best_trial.params["learning_rate"]),
        num_leaves=int(best_trial.params["num_leaves"]),
    )

    candidate_search = rolling_origin_backtest(
        best_task, data, origins=SEARCH_ORIGINS, horizon_hours=HORIZON_HOURS
    )
    candidate_eval = rolling_origin_backtest(
        best_task, data, origins=EVAL_ORIGINS, horizon_hours=HORIZON_HOURS
    )
    log_lab_run(
        run_name=f"best_candidate_trial_{best_trial.number:02d}",
        task=best_task,
        metrics={
            **_report_metrics("search", candidate_search),
            **_report_metrics("eval", candidate_eval),
        },
        extra_params={
            "role": "best_candidate",
            "best_trial_number": best_trial.number,
            "lags_key": best_trial.params["lags_key"],
            "rolling_key": best_trial.params["rolling_key"],
            "as_of": AS_OF,
            "snapshot_sha256": snapshot_sha256,
            "horizon_hours": HORIZON_HOURS,
            "seed": seed,
            "n_trials": n_trials,
        },
    )

    eval_distinct_days = len({ts.date() for ts in EVAL_ORIGINS})
    eval_sample_sufficient = eval_distinct_days >= MIN_EVAL_DISTINCT_DAYS
    beats_baseline_on_eval = candidate_eval.beats(baseline_eval)
    adopted = bool(eval_sample_sufficient and beats_baseline_on_eval)

    top_trials = sorted(
        study.trials,
        key=lambda t: t.value if t.value is not None else float("inf"),
    )[:5]

    return {
        "as_of": AS_OF,
        "snapshot_sha256": snapshot_sha256,
        "horizon_hours": HORIZON_HOURS,
        "min_history_hours": baseline_search.min_history_hours,
        "min_history_overridden": baseline_search.min_history_overridden,
        "seed": seed,
        "n_trials": n_trials,
        "search_origins": [ts.isoformat() for ts in SEARCH_ORIGINS],
        "eval_origins": [ts.isoformat() for ts in EVAL_ORIGINS],
        "eval_distinct_days": eval_distinct_days,
        "min_eval_distinct_days": MIN_EVAL_DISTINCT_DAYS,
        "eval_sample_sufficient": eval_sample_sufficient,
        "baseline_params": base_task.params.model_dump(),
        "best_trial_number": best_trial.number,
        "best_trial_params": best_trial.params,
        "candidate_params": best_task.params.model_dump(),
        "baseline_search_overall_mape": round(baseline_search.overall_mape, 4),
        "candidate_search_overall_mape": round(candidate_search.overall_mape, 4),
        "baseline_eval_overall_mape": round(baseline_eval.overall_mape, 4),
        "candidate_eval_overall_mape": round(candidate_eval.overall_mape, 4),
        "beats_baseline_on_search": candidate_search.beats(baseline_search),
        "beats_baseline_on_eval": beats_baseline_on_eval,
        "adopted": adopted,
        "baseline_search_mape_by_horizon": {
            step: round(val, 4) for step, val in baseline_search.mape_by_horizon.items()
        },
        "candidate_search_mape_by_horizon": {
            step: round(val, 4) for step, val in candidate_search.mape_by_horizon.items()
        },
        "baseline_eval_mape_by_horizon": {
            step: round(val, 4) for step, val in baseline_eval.mape_by_horizon.items()
        },
        "candidate_eval_mape_by_horizon": {
            step: round(val, 4) for step, val in candidate_eval.mape_by_horizon.items()
        },
        "top_5_trials": [
            {
                "trial_number": t.number,
                "search_overall_mape": round(float(t.value), 4) if t.value is not None else None,
                "params": t.params,
            }
            for t in top_trials
        ],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the TICKET-803 dynamic_horizon_forecast hyperparameter study."
    )
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Root directory for snapshot files (default: data/lab/snapshots).",
    )
    parser.add_argument(
        "--n-trials",
        type=int,
        default=N_TRIALS,
        help=f"Number of Optuna trials (default: {N_TRIALS}).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=STUDY_SEED,
        help=f"Random seed for Optuna TPESampler (default: {STUDY_SEED}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_study(
        snapshots_dir=args.snapshots_dir,
        n_trials=args.n_trials,
        seed=args.seed,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
