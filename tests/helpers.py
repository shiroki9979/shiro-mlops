"""集中共用測試資料，避免測試模組互相依賴私有 builder。"""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.datetime_utils import TAIWAN_TZ, taiwan_local_to_utc
from shiro_mlops.data.cwa_client import (
    DEFAULT_CWA_LOCATIONS,
    CWAForecastRelease,
    CWAObservationBatch,
    CWAStationObservation,
    CWATownshipForecast,
)
from shiro_mlops.data.taipower_regional_supply_demand import (
    TaipowerRegionalSupplyDemandSnapshot,
    parse_regional_supply_demand_csv,
)
from shiro_mlops.data.taipower_supply_demand import (
    TaipowerSupplyDemandSnapshot,
    parse_supply_demand_payload,
)
from shiro_mlops.data.taipower_unit_generation import (
    TaipowerUnitGenerationSnapshot,
    parse_unit_generation_payload,
)
from shiro_mlops.tasks.definition import TaskDefinition
from shiro_mlops.tasks.deployed import DYNAMIC_HORIZON_FORECAST, deployed_tasks

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TAIWAN = ZoneInfo(TAIWAN_TZ)


def rfc3339(value: datetime) -> str:
    """測試時間統一套用臺灣時區，避免各測試產生不同 offset 語意。"""
    return value.replace(tzinfo=TAIWAN).isoformat(timespec="seconds")


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


def unit_generation_snapshots(
    observed_at: datetime | None = None,
) -> list[TaipowerUnitGenerationSnapshot]:
    """共用正式 fixture，避免測試間複製或相依私有 builder。"""
    with (FIXTURES_DIR / "taipower_unit_generation_sample.json").open(encoding="utf-8") as file:
        payload = json.load(file)
    return parse_unit_generation_payload(
        payload,
        observed_at=observed_at or datetime(2026, 9, 5, 17, 30),
    )


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
        status="complete",
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
        status="complete",
        missing_station_ids=(),
        raw_payload={"fixture": "canonical_observation_batch"},
        observations=tuple(observations),
    )


def derived_hourly_load(hours: int, last_hour: datetime) -> pd.DataFrame:
    """建立連續且以 HH:00 標記的推算逐時負載，最後一列落在 ``last_hour``。"""
    times = pd.date_range(end=last_hour, periods=hours, freq="h")
    return pd.DataFrame({"datetime": times, "load_mw": [30000.0 + i for i in range(hours)]})


def create_legacy_load_table(engine: Engine) -> None:
    """模擬 d015046 時期資料庫：舊表沒有 source 欄，升級後舊列 source 為 NULL。"""
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
    """模擬 ADR-0009 之前的資料庫：全台負載以 location='Taipei' 保存。"""
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


def insert_legacy_load_row(engine: Engine, taiwan_time: datetime, load_mw: float) -> None:
    """以 d015046 時期的寫法（不帶 source）插入一列；需先完成 schema 升級使 source 可為 NULL。"""
    utc_time = pd.Timestamp(taiwan_local_to_utc(pd.Series([taiwan_time])).iloc[0])
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO raw_taipower_load (time, subject, load_mw) "
                "VALUES (:time, 'nationwide', :load_mw)"
            ),
            {"time": utc_time.to_pydatetime(), "load_mw": load_mw},
        )


def selected_asset_names(job) -> set[str]:
    """以正式部署的資產圖解析 job selection，讓各測試對同一份資產圖斷言。"""
    from shiro_mlops.pipelines.definitions import all_assets

    return {key.to_user_string() for key in job.selection.resolve(all_assets)}


def task_jobs() -> list:
    """資產工廠為所有已部署任務產生的訓練與監控 job。"""
    from shiro_mlops.pipelines.definitions import task_pipelines

    return [job for pipeline in task_pipelines for job in pipeline.jobs]


def hourly_load_with_weather(hours: int, last_hour: datetime) -> tuple[pd.DataFrame, pd.DataFrame]:
    """建立具日週期且與氣溫相關的全台負載及同時段觀測天氣，使模型有可學習的訊號。"""
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


def override_task_policies(
    monkeypatch, task_id: str = DYNAMIC_HORIZON_FORECAST, **updates: object
) -> TaskDefinition:
    """以測試值取代已部署任務的 [policies]，測試結束後由 monkeypatch 還原。"""
    tasks = deployed_tasks()
    task = tasks[task_id]
    updated = replace(task, policies=task.policies.model_copy(update=updates))
    monkeypatch.setitem(tasks, task_id, updated)
    return updated
