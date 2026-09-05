"""Integration tests for Taipower realtime snapshot Dagster job execution."""

import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from dagster import Definitions, RetryPolicy, build_schedule_context

from shiro_mlops.core.datetime_utils import TAIWAN_TZ
from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.pipelines.assets import (
    raw_taipower_regional_supply_demand_snapshot,
    raw_taipower_supply_demand_snapshot,
    raw_taipower_unit_generation_snapshot,
)
from shiro_mlops.pipelines.schedules import (
    build_taipower_supply_demand_snapshot_job,
    taipower_supply_demand_snapshot_schedule,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
SCHEDULED_EXECUTION_TIME = datetime(2026, 9, 5, 17, 30, tzinfo=ZoneInfo(TAIWAN_TZ))
OBSERVED_SLOT = datetime(2026, 9, 5, 17, 30)


class FailureScenario(StrEnum):
    """測試來源擷取失敗情境。"""

    NONE = "none"
    REGIONAL_ONCE = "regional_once"
    UNIT_ALWAYS = "unit_always"


@dataclass(frozen=True)
class SnapshotFixtures:
    """台電三個即時來源的測試 payload。"""

    sd_payload: dict
    reg_csv: str
    unit_payload: dict


def _load_fixtures() -> SnapshotFixtures:
    with open(FIXTURES_DIR / "taipower_supply_demand_sample.json", encoding="utf-8") as f:
        sd_data = json.load(f)
    with open(FIXTURES_DIR / "taipower_regional_supply_demand_sample.csv", encoding="utf-8") as f:
        reg_data = f.read()
    with open(FIXTURES_DIR / "taipower_unit_generation_sample.json", encoding="utf-8") as f:
        unit_data = json.load(f)
    return SnapshotFixtures(sd_payload=sd_data, reg_csv=reg_data, unit_payload=unit_data)


def _build_test_defs(repo: TimeSeriesRepository, job=None) -> Definitions:
    resolved_job = job or build_taipower_supply_demand_snapshot_job()
    return Definitions(
        assets=[
            raw_taipower_supply_demand_snapshot,
            raw_taipower_regional_supply_demand_snapshot,
            raw_taipower_unit_generation_snapshot,
        ],
        jobs=[resolved_job],
        resources={"time_series_repo": repo},
    )


def _build_schedule_run_request():
    context = build_schedule_context(scheduled_execution_time=SCHEDULED_EXECUTION_TIME)
    evaluation = taipower_supply_demand_snapshot_schedule.evaluate_tick(context)
    assert evaluation.run_requests is not None
    return evaluation.run_requests[0]


def _build_realtime_job_def(
    repo: TimeSeriesRepository,
    *,
    retry_policy: RetryPolicy | None = None,
):
    job = (
        build_taipower_supply_demand_snapshot_job()
        if retry_policy is None
        else build_taipower_supply_demand_snapshot_job(op_retry_policy=retry_policy)
    )
    return _build_test_defs(repo, job=job).resolve_job_def("taipower_supply_demand_snapshot_job")


def _build_failure_case(
    repo: TimeSeriesRepository,
    failure_scenario: FailureScenario,
):
    fixtures = _load_fixtures()
    router = MockHTTPXRouter(fixtures, failure_scenario=failure_scenario)
    job_def = _build_realtime_job_def(
        repo,
        retry_policy=RetryPolicy(max_retries=2, delay=0),
    )
    return _build_schedule_run_request(), router, job_def


class MockHTTPXRouter:
    """Mock HTTPX client routing requests by Taipower open-data URL."""

    def __init__(
        self,
        fixtures: SnapshotFixtures,
        failure_scenario: FailureScenario = FailureScenario.NONE,
    ):
        self.fixtures = fixtures
        self.failure_scenario = failure_scenario
        self.sd_call_count = 0
        self.reg_call_count = 0
        self.unit_call_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, *args, **kwargs):
        url_str = str(url)
        resp = MagicMock()

        if "d006020" in url_str:
            self.sd_call_count += 1
            resp.raise_for_status.return_value = None
            resp.json.return_value = self.fixtures.sd_payload
            return resp

        if "d006019" in url_str:
            self.reg_call_count += 1
            if self.failure_scenario == FailureScenario.REGIONAL_ONCE and self.reg_call_count == 1:
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Reg 500 error", request=MagicMock(), response=MagicMock(status_code=500)
                )
            else:
                resp.raise_for_status.return_value = None
                resp.text = self.fixtures.reg_csv
            return resp

        if "d006001" in url_str:
            self.unit_call_count += 1
            if self.failure_scenario == FailureScenario.UNIT_ALWAYS:
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "Unit 500 error", request=MagicMock(), response=MagicMock(status_code=500)
                )
            else:
                resp.raise_for_status.return_value = None
                resp.content = json.dumps(self.fixtures.unit_payload, ensure_ascii=False).encode(
                    "utf-8"
                )
            return resp

        raise ValueError(f"Unexpected URL: {url_str}")


def test_realtime_snapshot_job_shared_tick_and_idempotent_rerun(
    test_repo: TimeSeriesRepository,
) -> None:
    """排程觸發 job 應將同一個 tick 注入三來源，重跑時各自冪等更新相同快照。"""
    slot = OBSERVED_SLOT
    run_req = _build_schedule_run_request()

    fixtures = _load_fixtures()
    router = MockHTTPXRouter(fixtures)

    job_def = _build_realtime_job_def(test_repo)

    with patch("httpx.Client", return_value=router):
        res = job_def.execute_in_process(run_config=run_req.run_config)

    assert res.success

    # 驗證三來源皆以 slot 成功入庫
    sd_record = test_repo.fetch_supply_demand_snapshot(slot)
    assert sd_record is not None
    assert sd_record.curr_load_wan_kw == pytest.approx(3242.1)

    reg_records = test_repo.fetch_regional_supply_demand_snapshots(slot)
    assert len(reg_records) == 4
    north_reg = next(r for r in reg_records if r.region == "北部")
    assert north_reg.load_wan_kw == pytest.approx(1091.7)
    assert north_reg.generation_wan_kw == pytest.approx(1155.4)

    unit_records = test_repo.fetch_unit_generation_snapshots(slot)
    assert len(unit_records) == 4
    target_unit = next(u for u in unit_records if u.unit_name == "大潭CC#1")
    assert target_unit.net_generation_mw == pytest.approx(670.4)

    # 模擬同一 slot 重新執行並取得修正後的資料
    revised_sd = json.loads(json.dumps(fixtures.sd_payload))
    revised_sd["records"][0]["curr_load"] = "3400.0"

    revised_reg = fixtures.reg_csv.replace("1091.7", "1300.0")

    revised_unit = json.loads(json.dumps(fixtures.unit_payload))
    revised_unit["aaData"][0]["淨發電量(MW)"] = "700.0"

    revised_fixtures = replace(
        fixtures,
        sd_payload=revised_sd,
        reg_csv=revised_reg,
        unit_payload=revised_unit,
    )
    router_revised = MockHTTPXRouter(revised_fixtures)
    with patch("httpx.Client", return_value=router_revised):
        res2 = job_def.execute_in_process(run_config=run_req.run_config)

    assert res2.success

    # 驗證各快照原位更新，且總列數未重複增加
    updated_sd = test_repo.fetch_supply_demand_snapshot(slot)
    assert updated_sd is not None
    assert updated_sd.curr_load_wan_kw == pytest.approx(3400.0)

    updated_reg = test_repo.fetch_regional_supply_demand_snapshots(slot)
    assert len(updated_reg) == 4
    assert next(r for r in updated_reg if r.region == "北部").load_wan_kw == pytest.approx(1300.0)

    updated_unit = test_repo.fetch_unit_generation_snapshots(slot)
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
    run_req, router, job_def = _build_failure_case(
        test_repo,
        FailureScenario.REGIONAL_ONCE,
    )

    with patch("httpx.Client", return_value=router):
        res = job_def.execute_in_process(run_config=run_req.run_config)

    assert res.success
    # 驗證區域來源確實觸發了重試（共呼叫 2 次）
    assert router.reg_call_count == 2
    assert router.sd_call_count == 1
    assert router.unit_call_count == 1

    assert test_repo.fetch_supply_demand_snapshot(slot) is not None
    assert len(test_repo.fetch_regional_supply_demand_snapshots(slot)) == 4
    assert len(test_repo.fetch_unit_generation_snapshots(slot)) == 4


def test_realtime_snapshot_job_persistent_failure_exhausts_retries_and_does_not_write(
    test_repo: TimeSeriesRepository,
) -> None:
    """任一來源持續失敗耗盡重試時，run 失敗且該來源不得寫入資料。"""
    slot = OBSERVED_SLOT
    run_req, router, job_def = _build_failure_case(
        test_repo,
        FailureScenario.UNIT_ALWAYS,
    )

    with patch("httpx.Client", return_value=router):
        res = job_def.execute_in_process(
            run_config=run_req.run_config,
            raise_on_error=False,
        )

    assert not res.success
    # 首次 + 2 次重試 = 3 次呼叫
    assert router.unit_call_count == 3

    # 驗證失敗的機組來源絕對不寫入任何資料
    assert len(test_repo.fetch_unit_generation_snapshots(slot)) == 0
