"""Integration tests for Taipower realtime snapshot Dagster job execution."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from dagster import Definitions, RetryPolicy, build_schedule_context

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import (
    TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_SUPPLY_DEMAND_SOURCE,
    TAIPOWER_UNIT_GENERATION_SOURCE,
    raw_taipower_regional_supply_demand_snapshot,
    raw_taipower_supply_demand_snapshot,
    raw_taipower_unit_generation_snapshot,
)
from shiro_mlops.pipelines.schedules import (
    build_taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)
from tests.helpers import FIXTURES_DIR, FixtureSource

SCHEDULED_EXECUTION_TIME = datetime(2026, 9, 5, 17, 30, tzinfo=ZoneInfo(TAIWAN_TZ))
OBSERVED_SLOT = datetime(2026, 9, 5, 17, 30)


@dataclass(frozen=True)
class SnapshotSources:
    """台電三個即時來源的 fixture adapter。"""

    supply_demand: FixtureSource
    regional: FixtureSource
    unit: FixtureSource

    def resources(self) -> dict[str, FixtureSource]:
        return {
            TAIPOWER_SUPPLY_DEMAND_SOURCE: self.supply_demand,
            TAIPOWER_REGIONAL_SUPPLY_DEMAND_SOURCE: self.regional,
            TAIPOWER_UNIT_GENERATION_SOURCE: self.unit,
        }


def _fixture_sources(*, unit_fail_first: float = 0) -> SnapshotSources:
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        sd_payload = json.load(f)
    reg_csv = (FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv").read_text(
        encoding="utf-8"
    )
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        unit_payload = json.load(f)
    return SnapshotSources(
        supply_demand=FixtureSource(sd_payload),
        regional=FixtureSource(reg_csv),
        unit=FixtureSource(unit_payload, fail_first=unit_fail_first),
    )


def _build_schedule_run_request():
    context = build_schedule_context(scheduled_execution_time=SCHEDULED_EXECUTION_TIME)
    evaluation = taipower_supply_demand_snapshot_schedule.evaluate_tick(context)
    assert evaluation.run_requests is not None
    return evaluation.run_requests[0]


def _build_realtime_job_def(
    repo: TimeSeriesRepository,
    sources: SnapshotSources,
    *,
    retry_policy: RetryPolicy | None = None,
):
    job = (
        build_taipower_supply_demand_snapshot_job()
        if retry_policy is None
        else build_taipower_supply_demand_snapshot_job(op_retry_policy=retry_policy)
    )
    defs = Definitions(
        assets=[
            raw_taipower_supply_demand_snapshot,
            raw_taipower_regional_supply_demand_snapshot,
            raw_taipower_unit_generation_snapshot,
        ],
        jobs=[job],
        resources={"time_series_repo": repo, **sources.resources()},
    )
    return defs.resolve_job_def("taipower_supply_demand_snapshot_job")


def _build_failure_case(repo: TimeSeriesRepository, *, unit_fail_first: float):
    sources = _fixture_sources(unit_fail_first=unit_fail_first)
    job_def = _build_realtime_job_def(
        repo, sources, retry_policy=RetryPolicy(max_retries=2, delay=0)
    )
    return _build_schedule_run_request(), sources, job_def


def test_realtime_snapshot_job_shared_tick_and_idempotent_rerun(
    test_repo: TimeSeriesRepository,
) -> None:
    """排程觸發 job 應將同一個 tick 注入三來源，重跑時各自冪等更新相同快照。"""
    slot = OBSERVED_SLOT
    run_req = _build_schedule_run_request()

    sources = _fixture_sources()
    job_def = _build_realtime_job_def(test_repo, sources)

    res = job_def.execute_in_process(run_config=run_req.run_config)

    assert res.success

    # 驗證三來源皆以 slot 成功入庫
    sd_record = test_repo.supply_demand_store.fetch(slot)
    assert sd_record is not None
    assert sd_record.curr_load_wan_kw == pytest.approx(3242.1)

    reg_records = test_repo.regional_supply_demand_store.fetch(slot)
    assert len(reg_records) == 4
    north_reg = next(r for r in reg_records if r.region == "北部")
    assert north_reg.load_wan_kw == pytest.approx(1091.7)
    assert north_reg.generation_wan_kw == pytest.approx(1155.4)

    unit_records = test_repo.unit_generation_store.fetch(slot)
    assert len(unit_records) == 4
    target_unit = next(u for u in unit_records if u.unit_name == "大潭CC#1")
    assert target_unit.net_generation_mw == pytest.approx(670.4)

    # 模擬同一 slot 重新執行並取得修正後的資料
    # fixture adapter 是 run 間共用的 resource 物件，原地修改 payload 即模擬來源修正。
    sources.supply_demand.payload["records"][0]["curr_load"] = "3400.0"
    sources.regional.payload = sources.regional.payload.replace("1091.7", "1300.0")
    sources.unit.payload["aaData"][0]["淨發電量(MW)"] = "700.0"

    res2 = job_def.execute_in_process(run_config=run_req.run_config)

    assert res2.success

    # 驗證各快照原位更新，且總列數未重複增加
    updated_sd = test_repo.supply_demand_store.fetch(slot)
    assert updated_sd is not None
    assert updated_sd.curr_load_wan_kw == pytest.approx(3400.0)

    updated_reg = test_repo.regional_supply_demand_store.fetch(slot)
    assert len(updated_reg) == 4
    assert next(r for r in updated_reg if r.region == "北部").load_wan_kw == pytest.approx(1300.0)

    updated_unit = test_repo.unit_generation_store.fetch(slot)
    assert len(updated_unit) == 4
    assert next(
        u for u in updated_unit if u.unit_name == "大潭CC#1"
    ).net_generation_mw == pytest.approx(700.0)

    with test_repo.engine.connect() as conn:
        sd_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_supply_demand_snapshot"
        ).scalar()
        reg_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_regional_supply_demand_snapshot"
        ).scalar()
        unit_count = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM raw_taipower_unit_generation_snapshot"
        ).scalar()

    assert sd_count == 1
    assert reg_count == 4
    assert unit_count == 4


def test_realtime_snapshot_job_transient_failure_retries_and_succeeds(
    test_repo: TimeSeriesRepository,
) -> None:
    """任一來源暫時性失敗時，應依政策有限重試並成功完成 run。"""
    slot = OBSERVED_SLOT
    run_req, sources, job_def = _build_failure_case(test_repo, unit_fail_first=1)

    res = job_def.execute_in_process(run_config=run_req.run_config)

    assert res.success
    # 驗證機組來源確實依 job 重試政策重試（共呼叫 2 次）
    assert sources.unit.calls == 2
    assert sources.supply_demand.calls == 1
    assert sources.regional.calls == 1

    assert test_repo.supply_demand_store.fetch(slot) is not None
    assert len(test_repo.regional_supply_demand_store.fetch(slot)) == 4
    assert len(test_repo.unit_generation_store.fetch(slot)) == 4


def test_realtime_snapshot_job_persistent_failure_exhausts_retries_and_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """任一來源持續失敗耗盡重試時，run 失敗且該來源不得寫入資料。"""
    slot = OBSERVED_SLOT
    run_req, sources, job_def = _build_failure_case(test_repo, unit_fail_first=math.inf)

    res = job_def.execute_in_process(
        run_config=run_req.run_config,
        raise_on_error=False,
    )

    assert not res.success
    # 首次 + 2 次重試 = 3 次呼叫
    assert sources.unit.calls == 3

    # 驗證失敗的機組來源絕對不寫入任何資料
    assert len(test_repo.unit_generation_store.fetch(slot)) == 0
