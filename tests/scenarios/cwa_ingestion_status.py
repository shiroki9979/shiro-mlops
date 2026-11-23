"""CWA ingestion completeness scenarios shared across database dialects."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from shiro_mlops.core.storage_time import to_storage_time
from shiro_mlops.data.cwa_client import CWAObservationBatch, cwa_ingestion_status_sql
from shiro_mlops.data.cwa_weather_store import CWAWeatherStore

# 遠離實際擷取時刻的瞬間，在共用的驗收資料庫上也不會與其他情境的列相撞。
STATUS_FETCHED_AT = datetime(2000, 1, 3, 4, 5, 6, tzinfo=UTC)

COMPLETENESS_CASES = [
    pytest.param((), "complete", id="nothing-missing"),
    pytest.param(("467490", "466920"), "incomplete", id="stations-missing"),
]


def assert_python_and_sql_judge_alike(
    engine: Engine, missing_station_ids: tuple[str, ...], expected: str
) -> None:
    """A stored batch's SQL-judged status equals the status its Python value derives."""
    batch = CWAObservationBatch(
        fetched_at=STATUS_FETCHED_AT,
        missing_station_ids=missing_station_ids,
        raw_payload={},
        observations=(),
    )
    params = {"fetched_at": to_storage_time(STATUS_FETCHED_AT)}
    CWAWeatherStore(engine).upsert_cwa_observation_batch(batch)
    try:
        with engine.connect() as connection:
            stored = connection.execute(
                text(
                    f"SELECT {cwa_ingestion_status_sql('missing_station_ids')} "
                    "FROM raw_cwa_observation_batch WHERE fetched_at = :fetched_at"
                ),
                params,
            ).scalar_one()
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM raw_cwa_observation_batch WHERE fetched_at = :fetched_at"),
                params,
            )

    assert batch.status == expected
    assert stored == expected
