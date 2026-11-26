"""集中共用測試資料，避免測試模組互相依賴私有 builder。"""

import json
import math
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from dagster import (
    AssetsDefinition,
    Definitions,
    JobDefinition,
    RetryPolicy,
    RunRequest,
    ScheduleDefinition,
    build_schedule_context,
    define_asset_job,
)
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from shiro_mlops.core.constants import NATIONWIDE_SUBJECT
from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.core.schema_migrations import MIGRATIONS
from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.hourly_actual_load_store import HourlyActualLoadStore
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
    parse_regional_supply_demand_csv,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandSnapshot,
    parse_supply_demand_payload,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationBatch,
    TaipowerUnitGenerationSnapshot,
    parse_unit_generation_payload,
)
from shiro_mlops.pipelines.execution_origin import REEXECUTION_TAGS, RUN_KEY_TAG
from shiro_mlops.service.data_explorer.dataset_query import DatasetQuery
from shiro_mlops.service.data_explorer.datasets import Dataset
from shiro_mlops.service.data_explorer.schemas import ListEnvelope
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_task, deployed_tasks
from shiro_mlops.tasks.model_store import SavedModel, model_directory, save_model
from shiro_mlops.tasks.runner import TaskRuntime, train_task

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TAIWAN = ZoneInfo(TAIWAN_TZ)

# 人事行政總處公告的 2026 年辦公日曆中落在平日的 16 個放假日（含補假）；週末一律放假，
# 2026 年起不再有週六補班。
OFFICIAL_2026_WEEKDAY_DAYS_OFF = {
    "2026-01-01",
    "2026-02-16",
    "2026-02-17",
    "2026-02-18",
    "2026-02-19",
    "2026-02-20",
    "2026-02-27",
    "2026-04-03",
    "2026-04-06",
    "2026-05-01",
    "2026-06-19",
    "2026-09-25",
    "2026-09-28",
    "2026-10-09",
    "2026-10-26",
    "2026-12-25",
}


def rfc3339(value: datetime) -> str:
    """測試時間統一套用臺灣時區，避免各測試產生不同 offset 語意。"""
    return value.replace(tzinfo=TAIWAN).isoformat(timespec="seconds")


def explorer_pages(reader, params: dict[str, Any], *, max_pages: int = 20) -> list:
    """Follow a Data Explorer reader's cursors from the first page to the last.

    A cursor handed out twice fails at once; paging that never reaches the last page fails
    at ``max_pages`` instead of hanging.
    """
    pages = [reader.list(params)]
    seen_cursors: set[str] = set()
    while pages[-1].has_more:
        assert len(pages) < max_pages, f"cursor paging did not end within {max_pages} pages"
        cursor = pages[-1].next_cursor
        assert cursor is not None
        assert cursor not in seen_cursors, f"repeated cursor {cursor!r} after {len(pages)} pages"
        seen_cursors.add(cursor)
        pages.append(reader.list({**params, "cursor": cursor}))
    assert pages[-1].next_cursor is None
    return pages


def supply_demand_snapshot(
    observed_at: datetime | None = None,
) -> TaipowerSupplyDemandSnapshot:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    with (FIXTURES_DIR / "taipower_supply_demand_sample.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    return parse_supply_demand_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def regional_supply_demand_snapshots(
    observed_at: datetime | None = None,
) -> list[TaipowerRegionalSupplyDemandSnapshot]:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    csv_text = (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(
        encoding="utf-8"
    )
    return parse_regional_supply_demand_csv(
        csv_text,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def unit_generation_batch(
    observed_at: datetime | None = None,
) -> TaipowerUnitGenerationBatch:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    with (FIXTURES_DIR / "taipower_unit_generation_sample.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    return parse_unit_generation_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


def unit_snapshots(
    repo: TimeSeriesRepository, observed_at: datetime
) -> list[TaipowerUnitGenerationSnapshot]:
    """The unit snapshots stored for ``observed_at``; empty when no batch was written."""
    batch = repo.unit_generation_store.fetch(observed_at)
    return [] if batch is None else list(batch.snapshots)


def township_forecast(
    valid_from: datetime,
    temperature_c: float,
    *,
    valid_to: datetime | None = None,
    relative_humidity_pct: float | None = None,
) -> CWATownshipForecast:
    """集中預報測試預設值，讓個別測試只呈現契約差異。"""
    return CWATownshipForecast(
        valid_from=pd.Timestamp(valid_from),
        valid_to=pd.Timestamp(valid_to or valid_from),
        geocode="63000050",
        location_name="臺北",
        temperature_c=temperature_c,
        dew_point_c=None,
        apparent_temperature_c=None,
        relative_humidity_pct=relative_humidity_pct,
        probability_of_precipitation_pct=None,
        wind_speed_m_s=None,
        wind_direction=None,
    )


def forecast_release(
    issued_at: datetime,
    forecasts: tuple[CWATownshipForecast, ...],
    *,
    raw_payload: dict[str, Any] | None = None,
) -> CWAForecastRelease:
    """集中 release 識別與完整度預設值，讓分頁測試聚焦版本行為。"""
    return CWAForecastRelease(
        dataset_id="F-D0047-089",
        issued_at=pd.Timestamp(issued_at),
        source_updated_at=pd.Timestamp(issued_at),
        fetched_at=issued_at,
        missing_geocodes=(),
        raw_payload=raw_payload or {},
        forecasts=forecasts,
    )


def canonical_observation_batch(frame: pd.DataFrame) -> CWAObservationBatch:
    """Build canonical observations from fixture rows with an explicit allowed location."""
    locations = {location.alias: location for location in DEFAULT_CWA_LOCATIONS.values()}
    observations = []
    for row in frame.itertuples():
        location = locations[row.location]
        observations.append(
            CWAStationObservation(
                observed_at=pd.Timestamp(row.datetime),
                station_id=location.station_id,
                station_name=location.alias,
                town_code=location.geocode,
                temperature_c=float(row.temperature) if pd.notna(row.temperature) else None,
                relative_humidity_pct=(
                    float(row.relative_humidity) if pd.notna(row.relative_humidity) else None
                ),
                air_pressure_hpa=None,
                precipitation_mm=None,
                wind_speed_m_s=None,
                wind_direction_deg=None,
            )
        )
    return CWAObservationBatch(
        fetched_at=pd.Timestamp(frame.datetime.max()).to_pydatetime(),
        missing_station_ids=(),
        raw_payload={"fixture": "canonical_observation_batch"},
        observations=tuple(observations),
    )


def derived_hourly_load(hours: int, last_hour: datetime) -> pd.DataFrame:
    """Build contiguous derived hourly load ending at ``last_hour`` with HH:00 timestamps."""
    times = pd.date_range(end=last_hour, periods=hours, freq="h")
    return pd.DataFrame({"datetime": times, "load_mw": [30000.0 + i for i in range(hours)]})


class _ModelFilesDouble:
    """A task model whose saved files stand in for a trained one; presence checks never load it."""

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        (directory / "model.txt").write_text("trained", encoding="utf-8")


def install_model_double(root: Path, task_id: str = DYNAMIC_HORIZON_FORECAST) -> None:
    """Install a model directory through the model store, as training would, without training."""
    save_model(root, task_id, _ModelFilesDouble())


def hand_copied_model_double(root: Path, task_id: str = DYNAMIC_HORIZON_FORECAST) -> None:
    """Write a model directory the model store did not install."""
    _ModelFilesDouble().save(model_directory(root, task_id))


def write_derived_load(
    engine: Engine, hourly_load: pd.DataFrame, *, subject: str = NATIONWIDE_SUBJECT
) -> None:
    """Seed derived hours from ``datetime`` and ``load_mw`` columns the way the schedule writes them."""
    HourlyActualLoadStore(engine).write(hourly_load, subject=subject)


def derived_load_series(engine: Engine, *, subject: str = NATIONWIDE_SUBJECT) -> pd.DataFrame:
    """Every derived hour stored for ``subject``, oldest first, in ``datetime`` and ``load_mw``."""
    return HourlyActualLoadStore(engine).series(end=datetime.max, subject=subject)


# 0001 至 0004 早於紀錄表，各自檢視 schema 決定是否已套用，可在已遷移的資料庫上重跑（ADR-0017 §2.1）。
PROBING_MIGRATIONS = MIGRATIONS[:4]
# 0006 之前的 schema：機組列仍各自帶完整回應 raw_payload。
MIGRATIONS_BEFORE_UNIT_BATCH = tuple(
    migration
    for migration in MIGRATIONS
    if migration.id < "0006_move_unit_generation_payload_to_batch"
)


def forget_schema_migrations(engine: Engine) -> None:
    """Forget the migrations that predate the record, as in a database older than it (ADR-0017).

    A test that rebuilds a legacy table shape in an already migrated database calls this;
    otherwise the recorded migrations are skipped and the shape stays legacy. Only
    0001 to 0004 are forgotten: they probe the schema and redo nothing already applied,
    while a later migration assumes the shape it was written for and cannot run twice.
    """
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM schema_migration WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": [migration.id for migration in PROBING_MIGRATIONS]},
        )


def create_legacy_load_table(engine: Engine) -> None:
    """Model a d015046-era database without a source column; migration leaves legacy rows with NULL source."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE raw_taipower_load (
                    time TIMESTAMP NOT NULL,
                    location VARCHAR(64) NOT NULL,
                    load_mw DOUBLE PRECISION NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (time, location)
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, location, load_mw) "
                "VALUES ('2026-08-20 00:00:00', 'Taipei', 26500.0)"
            )
        )


def create_location_keyed_load_table(engine: Engine) -> None:
    """Model a pre-ADR-0009 database that stores nationwide load under location='Taipei'."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE raw_taipower_load (
                    time TIMESTAMP NOT NULL,
                    location VARCHAR(64) NOT NULL,
                    load_mw DOUBLE PRECISION NOT NULL,
                    source VARCHAR(32) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (time, location)
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, location, load_mw, source) VALUES "
                "('2026-08-20 00:00:00', 'Taipei', 26500.0, 'regional_snapshot_sum'), "
                "('2026-08-20 01:00:00', 'Taipei', 26600.0, 'regional_snapshot_sum')"
            )
        )


def insert_legacy_load_row(
    engine: Engine, taiwan_time: datetime, load_mw: float, *, subject: str = NATIONWIDE_SUBJECT
) -> None:
    """Insert a d015046-era row without source after migrating the schema to allow NULL source."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw) "
                "VALUES (:time, :subject, :load_mw)"
            ),
            {"time": to_storage_time(taiwan_time), "subject": subject, "load_mw": load_mw},
        )


def insert_other_source_load_row(
    engine: Engine, taiwan_time: datetime, load_mw: float, *, subject: str = NATIONWIDE_SUBJECT
) -> None:
    """Insert a row of another derivation source, which no production path writes."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw, source) "
                "VALUES (:time, :subject, :load_mw, 'other_source')"
            ),
            {"time": to_storage_time(taiwan_time), "subject": subject, "load_mw": load_mw},
        )


def selected_asset_names(job) -> set[str]:
    """Resolve job selection from the deployed asset graph so tests inspect the same graph."""
    from shiro_mlops.pipelines.definitions import all_assets

    return {key.to_user_string() for key in job.selection.resolve(all_assets)}


def scheduler_launch_tags(request: RunRequest) -> dict:
    """The tags the scheduler daemon puts on the run it launches for ``request``.

    Evaluating a tick already merges the schedule name into the request's tags; only
    the daemon adds the run key, so a run launched from a tick preview never has it.
    """
    tags = dict(request.tags)
    if request.run_key:
        tags[RUN_KEY_TAG] = request.run_key
    return tags


def _evaluated_request(
    schedule: ScheduleDefinition,
    tick: datetime,
    instance=None,
    resources: dict[str, Any] | None = None,
) -> RunRequest:
    execution = schedule.evaluate_tick(
        build_schedule_context(
            instance=instance, scheduled_execution_time=tick, resources=resources
        )
    )
    [request] = execution.run_requests
    return request


def scheduled_run_tags(
    schedule: ScheduleDefinition,
    tick: datetime,
    instance=None,
    resources: dict[str, Any] | None = None,
) -> dict:
    """The tags of the run the scheduler launches for ``schedule`` at ``tick``."""
    return scheduler_launch_tags(_evaluated_request(schedule, tick, instance, resources))


def tick_preview_launch_tags(
    schedule: ScheduleDefinition,
    tick: datetime,
    instance=None,
    resources: dict[str, Any] | None = None,
) -> dict:
    """The tags of a run a person launches from the Dagster UI's tick preview of ``schedule``.

    The preview evaluates the schedule at a past or future tick and its launch button copies
    the evaluated request's tags, schedule name and tick included, onto a hand-started run.
    """
    return dict(_evaluated_request(schedule, tick, instance, resources).tags)


# Dagster 重新執行 run 時加上的標籤；與原 run 複製過來的標籤合併即為重新執行的 run。
REEXECUTION = dict.fromkeys(REEXECUTION_TAGS, "tick-run")


def job_retrying_once_at_once(asset: AssetsDefinition, resources: dict[str, Any]) -> JobDefinition:
    """A job materializing ``asset`` that retries a failed op once, without waiting."""
    return Definitions(
        assets=[asset],
        jobs=[
            define_asset_job(
                "retrying_once_at_once",
                selection=[asset.key],
                op_retry_policy=RetryPolicy(max_retries=1),
            )
        ],
        resources=resources,
    ).resolve_job_def("retrying_once_at_once")


def run_creation_time(instance, run_id: str) -> datetime:
    """The naive Taiwan-local time at which Dagster created the run; callers floor it themselves."""
    created = instance.get_run_record_by_id(run_id).create_timestamp
    return created.astimezone(TAIWAN).replace(tzinfo=None)


def task_jobs() -> list:
    """Build training and monitoring jobs for every deployed task through the asset factory."""
    from shiro_mlops.pipelines.definitions import task_pipelines

    return [job for pipeline in task_pipelines for job in pipeline.jobs]


def hourly_load_with_weather(hours: int, last_hour: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build daily patterned nationwide load and correlated observed weather for model tests."""
    times = pd.date_range(end=last_hour, periods=hours, freq="h")
    daily = np.sin(2 * np.pi * times.hour / 24.0)
    temperature = 28.0 + 4.0 * daily
    load = pd.DataFrame(
        {
            "datetime": times,
            "subject": "nationwide",
            "load_mw": 30000.0 + 3000.0 * daily + 150.0 * (temperature - 28.0),
        }
    )
    weather = pd.DataFrame(
        {"datetime": times, "temperature": temperature, "relative_humidity": 75.0 - 5.0 * daily}
    )
    return load, weather


def with_dynamic_horizon_lookback(load: pd.DataFrame) -> pd.DataFrame:
    """Extend contiguous hourly load back over the dynamic-horizon lookback ending at its last hour.

    Earlier hours cycle through the given rows so the sequence still ends on the given last row;
    the given rows keep their values and serving finds every lookback hour present.
    """
    hours = deployed_tasks()[DYNAMIC_HORIZON_FORECAST].params.lookback_hours
    given = load.sort_values("datetime").reset_index(drop=True)
    times = pd.date_range(end=given["datetime"].max(), periods=max(hours, len(given)), freq="h")
    offsets_from_last_row = np.arange(-len(times), 0)
    positions = offsets_from_last_row % len(given)
    return given.iloc[positions].assign(datetime=times).reset_index(drop=True)


def override_task_policies(
    monkeypatch, task_id: str = DYNAMIC_HORIZON_FORECAST, **updates: object
) -> TaskDefinition:
    """Override deployed task policies with test values and let monkeypatch restore them."""
    tasks = deployed_tasks()
    task = tasks[task_id]
    updated = replace(task, policies=task.policies.model_copy(update=updates))
    monkeypatch.setitem(tasks, task_id, updated)
    return updated


def task_runtime(repository: TimeSeriesRepository) -> TaskRuntime:
    """The runtime the deployed entry points build from the composition root."""
    return TaskRuntime.from_composition_root(repository)


def train_and_install_forecast_model(
    repository: TimeSeriesRepository,
    models_root: Path,
    *,
    as_of: datetime,
    min_training_hours: int,
    n_estimators: int,
) -> SavedModel:
    """Train the dynamic horizon forecast on the persisted load and install it as training would.

    ``n_estimators`` keeps training fast; a different value also yields a different model hash.
    """
    shipped = deployed_task(DYNAMIC_HORIZON_FORECAST)
    task = replace(
        shipped,
        params=shipped.params.model_copy(
            update={"model": shipped.params.model.model_copy(update={"n_estimators": n_estimators})}
        ),
        policies=shipped.policies.model_copy(update={"min_training_hours": min_training_hours}),
    )
    model = train_task(task, task_runtime(repository), as_of=as_of).model
    return save_model(models_root, DYNAMIC_HORIZON_FORECAST, model)


def upstream_http_500(url: str = "https://example.invalid/source") -> httpx.HTTPStatusError:
    """The error an HTTP adapter raises when the upstream source answers HTTP 500."""
    request = httpx.Request("GET", url)
    return httpx.HTTPStatusError(
        "upstream returned HTTP 500", request=request, response=httpx.Response(500, request=request)
    )


class FixtureSource:
    """Fixture adapter for a Taipower source port: serves one payload, optionally failing first.

    ``fail_first`` counts the fetches that raise ``error`` before the payload is served;
    ``math.inf`` makes every fetch fail.
    """

    def __init__(
        self,
        payload: Any = None,
        *,
        fail_first: float = 0,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.fail_first = fail_first
        self.error = error or upstream_http_500()
        self.calls = 0

    def fetch_payload(self) -> Any:
        self.calls += 1
        if self.calls <= self.fail_first:
            raise self.error
        return self.payload


class FixtureCWASource:
    """Fixture adapter for the CWA source port; an exception value is raised instead of served."""

    def __init__(
        self,
        observation_batch: CWAObservationBatch | Exception | None = None,
        forecast_releases: dict[str, CWAForecastRelease | Exception] | None = None,
    ) -> None:
        self.observation_batch = observation_batch
        self.forecast_releases = forecast_releases or {}
        self.calls: list[str] = []

    def fetch_observation_batch(self, locations: object = None) -> CWAObservationBatch:
        self.calls.append("observation")
        return _served(self.observation_batch)

    def fetch_forecast_release(
        self, dataset_id: str, locations: object = None
    ) -> CWAForecastRelease:
        self.calls.append(dataset_id)
        return _served(self.forecast_releases[dataset_id])


def _served(value: Any) -> Any:
    if isinstance(value, Exception):
        raise value
    if value is None:
        raise AssertionError("FixtureCWASource was asked for a payload it was not given")
    return value


def unfetched_source_resources() -> dict[str, Any]:
    """Every ingestion source port bound to an adapter that fails if a run ever fetches it.

    Definitions that load the ingestion assets without running them still have to bind
    their source resources.
    """
    from shiro_mlops.pipelines.assets import (
        CWA_SOURCE,
        TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
        TAIPOWER_SUPPLY_DEMAND_SOURCE,
        TAIPOWER_UNIT_GENERATION_SOURCE,
    )

    def unfetched(key: str) -> FixtureSource:
        return FixtureSource(fail_first=math.inf, error=AssertionError(f"{key} was fetched"))

    return {
        CWA_SOURCE: FixtureCWASource(),
        **{
            key: unfetched(key)
            for key in (
                TAIPOWER_SUPPLY_DEMAND_SOURCE,
                TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
                TAIPOWER_UNIT_GENERATION_SOURCE,
            )
        },
    }


class DatasetLister:
    """Bind `DatasetQuery.list` to one dataset so a test pages it like the HTTP list."""

    def __init__(self, engine: Engine, dataset: Dataset) -> None:
        self.query = DatasetQuery(engine)
        self.dataset = dataset

    def list(self, params: dict[str, Any]) -> ListEnvelope:
        return self.query.list(self.dataset, params)
