"""CWA header schema upgrade scenarios shared across database dialects."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from shiro_mlops.core import schema_migrations
from shiro_mlops.core.database import ensure_timescale_hypertables
from tests.helpers import forget_schema_migrations

OBSERVATION_BATCH_TABLE = "raw_cwa_observation_batch"
FORECAST_RELEASE_TABLE = "raw_cwa_forecast_release"
CWA_HEADER_TABLES = (OBSERVATION_BATCH_TABLE, FORECAST_RELEASE_TABLE)
LEGACY_STATUS_COLUMN = "status"
# 遠離實際擷取時刻的瞬間，在共用的驗收資料庫上也不會與其他情境的列相撞。
UPGRADE_FETCHED_AT = datetime(2000, 1, 2, 3, 4, 5, tzinfo=UTC)
UPGRADE_DATASET_ID = "F-UPGRADE"

_LEGACY_HEADER_ROWS = {
    OBSERVATION_BATCH_TABLE: (
        "INSERT INTO raw_cwa_observation_batch "
        "(fetched_at, status, missing_station_ids, raw_payload) "
        "VALUES (:fetched_at, 'incomplete', '[\"467490\"]', '{}')"
    ),
    FORECAST_RELEASE_TABLE: (
        "INSERT INTO raw_cwa_forecast_release "
        "(dataset_id, issued_at, source_updated_at, fetched_at, status, missing_geocodes, raw_payload) "
        "VALUES (:dataset_id, :fetched_at, :fetched_at, :fetched_at, 'complete', '[]', '{}')"
    ),
}
_UPGRADE_ROW_KEYS = {
    OBSERVATION_BATCH_TABLE: "fetched_at = :fetched_at",
    FORECAST_RELEASE_TABLE: "dataset_id = :dataset_id",
}
_UPGRADE_PARAMS = {"fetched_at": UPGRADE_FETCHED_AT, "dataset_id": UPGRADE_DATASET_ID}


def header_columns(engine: Engine, table: str) -> list[str]:
    return [column["name"] for column in inspect(engine).get_columns(table)]


def assert_header_status_is_dropped_repeatably(engine: Engine) -> None:
    """舊 schema 的 header status 欄經升級後消失，其餘欄位與資料列不變；重跑升級不改動任何東西。"""
    with _legacy_header_rows(engine):
        legacy_columns = {table: header_columns(engine, table) for table in CWA_HEADER_TABLES}
        legacy_rows = {table: _upgrade_row(engine, table) for table in CWA_HEADER_TABLES}

        ensure_timescale_hypertables(engine)
        upgraded_rows = {table: _upgrade_row(engine, table) for table in CWA_HEADER_TABLES}
        ensure_timescale_hypertables(engine)
        rerun_rows = {table: _upgrade_row(engine, table) for table in CWA_HEADER_TABLES}

        for table in CWA_HEADER_TABLES:
            kept_columns = [name for name in legacy_columns[table] if name != LEGACY_STATUS_COLUMN]
            assert header_columns(engine, table) == kept_columns, table
            kept_row = {
                name: value
                for name, value in legacy_rows[table].items()
                if name != LEGACY_STATUS_COLUMN
            }
            assert upgraded_rows[table] == kept_row, table
            assert rerun_rows[table] == kept_row, table


def assert_header_status_drop_survives_an_unlocked_upgrade(engine: Engine) -> None:
    """紀錄表出現前的程式版本不取遷移鎖：本程式檢視時仍見 status 欄，對方已先移除；本程式的升級不得失敗。"""
    with _legacy_header_rows(engine):
        stale = inspect(engine)
        for table in CWA_HEADER_TABLES:
            assert LEGACY_STATUS_COLUMN in [column["name"] for column in stale.get_columns(table)]
        ensure_timescale_hypertables(engine)
        forget_schema_migrations(engine)

        with patch.object(schema_migrations, "inspect", return_value=stale):
            ensure_timescale_hypertables(engine)

        for table in CWA_HEADER_TABLES:
            assert LEGACY_STATUS_COLUMN not in header_columns(engine, table), table


@contextmanager
def _legacy_header_rows(engine: Engine) -> Iterator[None]:
    """Restore the pre-#339 header `status` column and seed one header row per table.

    The migration record forgets the drop too, as in a database older than the record.
    """
    forget_schema_migrations(engine)
    with engine.begin() as connection:
        for table, insert in _LEGACY_HEADER_ROWS.items():
            connection.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN {LEGACY_STATUS_COLUMN} VARCHAR(16) NOT NULL DEFAULT 'complete'"
                )
            )
            connection.execute(text(insert), _UPGRADE_PARAMS)
    try:
        yield
    finally:
        with engine.begin() as connection:
            for table, key in _UPGRADE_ROW_KEYS.items():
                connection.execute(text(f"DELETE FROM {table} WHERE {key}"), _UPGRADE_PARAMS)


def _upgrade_row(engine: Engine, table: str) -> dict[str, Any]:
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(f"SELECT * FROM {table} WHERE {_UPGRADE_ROW_KEYS[table]}"), _UPGRADE_PARAMS
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1, table
    return dict(rows[0])
