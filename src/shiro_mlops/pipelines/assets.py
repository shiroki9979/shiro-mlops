"""Shared, source-centric Dagster assets: ingestion plus the frozen Feast export.

Per-task features, model, and monitoring assets come from the asset factory in
``pipelines/task_pipelines.py``.
"""

from datetime import datetime

import pandas as pd
from dagster import (
    AssetExecutionContext,
    AssetIn,
    AssetKey,
    AssetOut,
    Backoff,
    RetryPolicy,
    asset,
    multi_asset,
)

from shiro_mlops.core.config import settings
from shiro_mlops.data.cwa_client import (
    CWAForecastRelease,
    CWAObservationBatch,
    CWASource,
)
from shiro_mlops.data.hourly_actual_load import ONE_HOUR
from shiro_mlops.data.hourly_actual_load_store import (
    HourlyActualLoadStore,
    ScheduledDerivationPolicy,
)
from shiro_mlops.data.taipower_regional_supply_demand import (
    RegionalSupplyDemandSource,
    TaipowerRegionalSupplyDemandSnapshot,
    parse_regional_supply_demand_csv,
)
from shiro_mlops.data.taipower_supply_demand import (
    SupplyDemandSource,
    TaipowerSupplyDemandSnapshot,
    floor_to_ten_minutes,
    parse_supply_demand_payload,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationSnapshot,
    UnitGenerationSource,
    parse_unit_generation_payload,
)
from shiro_mlops.features.feast_export import build_feast_feature_frames
from shiro_mlops.pipelines.execution_origin import WithoutTick, run_as_of
from shiro_mlops.pipelines.task_pipelines import TIME_SERIES_REPO, TaskPipelineNames
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task
from shiro_mlops.tasks.runner import training_data_from_table

FEAST_TASK_NAMES = TaskPipelineNames(DYNAMIC_HORIZON_FORECAST)
FEAST_EXPORT_ASSET = f"{DYNAMIC_HORIZON_FORECAST}_feast_export"

CWA_SOURCE = "cwa_source"
TAIPOWER_SUPPLY_DEMAND_SOURCE = "taipower_supply_demand_source"
TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE = "taipower_regional_supply_demand_source"
TAIPOWER_UNIT_GENERATION_SOURCE = "taipower_unit_generation_source"


# 區域快照是全台逐時實際負載的唯一來源且無法回補，故重試比其他即時快照更久；
# Dagster 指數退避等待 (2^n - 1) × delay，即 10、30、70 秒，約 110 秒內結束，
# 仍早於下一個 10 分鐘 slot。
TAIPOWER_REGIONAL_SNAPSHOT_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    delay=10,
    backoff=Backoff.EXPONENTIAL,
)


@asset(
    name="raw_cwa_station_observation",
    group_name="ingestion",
    description="Fetch and persist canonical CWA station observations",
    required_resource_keys={TIME_SERIES_REPO, CWA_SOURCE},
)
def raw_cwa_station_observation(context: AssetExecutionContext) -> CWAObservationBatch:
    """Asset: canonical CWA station observation batch."""
    source: CWASource = getattr(context.resources, CWA_SOURCE)
    batch = source.fetch_observation_batch(locations=settings.cwa_locations)
    repository = getattr(context.resources, TIME_SERIES_REPO)
    persisted = repository.upsert_cwa_observation_batch(batch)
    context.log.info("Persisted %s canonical CWA station observations.", persisted)
    if batch.status != "complete":
        missing = ", ".join(batch.missing_station_ids)
        raise RuntimeError(f"CWA observation batch incomplete; missing station IDs: {missing}")
    return batch


@asset(
    name="raw_cwa_township_forecast",
    group_name="ingestion",
    description="Fetch and persist canonical CWA township forecast vintages",
    required_resource_keys={TIME_SERIES_REPO, CWA_SOURCE},
)
def raw_cwa_township_forecast(context: AssetExecutionContext) -> list[CWAForecastRelease]:
    """Asset: canonical CWA township forecast releases for three-day and weekly products."""
    source: CWASource = getattr(context.resources, CWA_SOURCE)
    repository = getattr(context.resources, TIME_SERIES_REPO)
    releases: list[CWAForecastRelease] = []
    missing: dict[str, tuple[str, ...]] = {}
    for dataset_id in ("F-D0047-089", "F-D0047-091"):
        release = source.fetch_forecast_release(dataset_id, locations=settings.cwa_locations)
        releases.append(release)
        if release.status != "complete":
            missing[dataset_id] = release.missing_geocodes
    repository.upsert_cwa_forecast_releases(releases)
    if missing:
        details = "; ".join(
            f"{dataset}: {', '.join(values)}" for dataset, values in missing.items()
        )
        raise RuntimeError(f"CWA forecast release incomplete; missing Geocodes: {details}")
    return releases


def _observation_slot(context: AssetExecutionContext) -> datetime:
    """The ten-minute slot of the run's as_of, shared by all three realtime snapshots.

    Without a tick the slot falls back to the run's creation time, so a manual run or a
    re-execution writes what the realtime API serves now into the slot it is served in.
    """
    return floor_to_ten_minutes(run_as_of(context, without_tick=WithoutTick.FALL_BACK_TO_NOW))


@asset(
    group_name="ingestion",
    description="Fetch current Taipower power supply-demand snapshot",
    required_resource_keys={TIME_SERIES_REPO, TAIPOWER_SUPPLY_DEMAND_SOURCE},
)
def raw_taipower_supply_demand_snapshot(
    context: AssetExecutionContext,
) -> TaipowerSupplyDemandSnapshot:
    """Asset: Taipower supply-demand snapshot upserted by observation slot."""
    observed_at = _observation_slot(context)
    source: SupplyDemandSource = getattr(context.resources, TAIPOWER_SUPPLY_DEMAND_SOURCE)
    snapshot = parse_supply_demand_payload(source.fetch_payload(), observed_at=observed_at)
    context.log.info(
        "Fetched supply-demand snapshot for observed_at=%s curr_load=%s",
        snapshot.observed_at.isoformat(),
        snapshot.curr_load_wan_kw,
    )
    getattr(context.resources, TIME_SERIES_REPO).upsert_supply_demand_snapshot(snapshot)
    return snapshot


@asset(
    group_name="ingestion",
    description="Fetch current Taipower regional supply-demand snapshots",
    required_resource_keys={TIME_SERIES_REPO, TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE},
    retry_policy=TAIPOWER_REGIONAL_SNAPSHOT_RETRY_POLICY,
)
def raw_taipower_regional_supply_demand_snapshot(
    context: AssetExecutionContext,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """Asset: regional supply-demand snapshots upserted by observation slot and region."""
    observed_at = _observation_slot(context)
    source: RegionalSupplyDemandSource = getattr(
        context.resources, TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE
    )
    snapshots = parse_regional_supply_demand_csv(source.fetch_payload(), observed_at=observed_at)
    context.log.info(
        "Fetched %s regional supply-demand snapshots for observed_at=%s",
        len(snapshots),
        snapshots[0].observed_at.isoformat(),
    )
    getattr(context.resources, TIME_SERIES_REPO).upsert_regional_supply_demand_snapshots(snapshots)
    return snapshots


@asset(
    group_name="ingestion",
    description="Derive nationwide hourly actual load from regional supply-demand snapshots",
    required_resource_keys={TIME_SERIES_REPO},
    deps=[raw_taipower_regional_supply_demand_snapshot],
)
def raw_taipower_load(context: AssetExecutionContext) -> pd.DataFrame:
    """Asset: recompute recent hours and any after the latest derived hour, then upsert them.

    The run's as_of is the evaluation time: the tick for a run a schedule tick
    launched, otherwise the run's creation time, so a retry in the same run
    derives the same window.
    """
    store: HourlyActualLoadStore = getattr(
        context.resources, TIME_SERIES_REPO
    ).hourly_actual_load_store
    derivation = store.derive_scheduled(
        run_as_of(context, without_tick=WithoutTick.FALL_BACK_TO_NOW),
        ScheduledDerivationPolicy(
            recompute_hours=settings.HOURLY_LOAD_RECOMPUTE_HOURS,
            max_catchup_hours=settings.HOURLY_LOAD_CATCHUP_MAX_HOURS,
            min_samples=settings.HOURLY_LOAD_MIN_SAMPLES,
        ),
    )
    gap = derivation.uncovered_gap
    if gap is not None:
        context.log.warning(
            "Hours in [%s, %s) exceed HOURLY_LOAD_CATCHUP_MAX_HOURS=%s and are not derived; "
            "run scripts/rederive_hourly_actual_load.py for that range",
            gap.start.isoformat(),
            gap.end.isoformat(),
            settings.HOURLY_LOAD_CATCHUP_MAX_HOURS,
        )
    window = derivation.window
    context.log.info(
        "Derived %s of %s hours in [%s, %s) from %s regional snapshots",
        derivation.written_hours,
        (window.end - window.start) // ONE_HOUR,
        window.start.isoformat(),
        window.end.isoformat(),
        derivation.snapshot_count,
    )
    return derivation.hourly_load


@asset(
    group_name="ingestion",
    description="Fetch current Taipower unit net-generation snapshots",
    required_resource_keys={TIME_SERIES_REPO, TAIPOWER_UNIT_GENERATION_SOURCE},
)
def raw_taipower_unit_generation_snapshot(
    context: AssetExecutionContext,
) -> list[TaipowerUnitGenerationSnapshot]:
    """Asset: unit net-generation snapshots upserted by observation slot and unit identity."""
    observed_at = _observation_slot(context)
    source: UnitGenerationSource = getattr(context.resources, TAIPOWER_UNIT_GENERATION_SOURCE)
    snapshots = parse_unit_generation_payload(source.fetch_payload(), observed_at=observed_at)
    context.log.info(
        "Fetched %s unit-generation snapshots for observed_at=%s",
        len(snapshots),
        snapshots[0].observed_at.isoformat(),
    )
    getattr(context.resources, TIME_SERIES_REPO).upsert_unit_generation_snapshots(snapshots)
    return snapshots


@multi_asset(
    name=FEAST_EXPORT_ASSET,
    description="Publish the Feast offline Parquet contracts from the forecast training table",
    ins={"features": AssetIn(key=AssetKey(FEAST_TASK_NAMES.features))},
    outs={
        "taipower_features": AssetOut(
            group_name="features",
            io_manager_key="feast_io_manager",
            description="Feast Taipower offline Parquet contract",
        ),
        "weather_features": AssetOut(
            group_name="features",
            io_manager_key="feast_io_manager",
            description="Feast CWA weather offline Parquet contract",
        ),
    },
)
def feast_feature_export(
    context: AssetExecutionContext, features: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Publish the frozen Feast contracts from the dynamic horizon forecast's training table.

    Feast stays exclusive to this task (ADR-0009), so the export hangs off its
    features asset only and runs inside that task's training job.
    """
    data = training_data_from_table(deployed_task(DYNAMIC_HORIZON_FORECAST), features)
    frames = build_feast_feature_frames(data.load, data.weather)
    context.log.info(
        "Built Feast frames: %s load rows, %s weather rows",
        len(frames.taipower),
        len(frames.weather),
    )
    return frames.taipower, frames.weather
