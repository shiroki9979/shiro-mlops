"""The test session refuses SQLite binds that bypass the storage-time module."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from shiro_mlops.core.database import get_timescale_engine
from shiro_mlops.core.storage_time import to_storage_time

TAIWAN_OFFSET = timezone(timedelta(hours=8))


@pytest.fixture(params=["bare_create_engine", "get_timescale_engine"])
def instants_engine(request, tmp_path):
    uri = f"sqlite:///{tmp_path / 'guard.db'}"
    engine = (
        create_engine(uri)
        if request.param == "bare_create_engine"
        else get_timescale_engine(uri=uri)
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE instants (observed_at TIMESTAMPTZ)"))
    yield engine
    engine.dispose()


@pytest.mark.parametrize(
    "bypassing_bind",
    [datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 1, 8, 0, tzinfo=TAIWAN_OFFSET)],
    ids=["naive", "aware_non_utc"],
)
def test_writing_an_instant_that_bypassed_the_module_fails(instants_engine, bypassing_bind):
    with pytest.raises(TypeError, match="shiro_mlops.core.storage_time"):
        with instants_engine.begin() as conn:
            conn.execute(text("INSERT INTO instants VALUES (:at)"), {"at": bypassing_bind})


def test_querying_with_a_naive_parameter_fails(instants_engine):
    with pytest.raises(TypeError, match="shiro_mlops.core.storage_time"):
        with instants_engine.connect() as conn:
            conn.execute(
                text("SELECT COUNT(*) FROM instants WHERE observed_at >= :start"),
                {"start": datetime(2026, 1, 1, 8, 0)},
            )


def test_storage_time_binds_are_accepted_and_keep_the_aware_utc_text(instants_engine):
    with instants_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO instants VALUES (:at)"),
            {"at": to_storage_time(datetime(2026, 1, 1, 8, 0))},
        )
        stored = conn.execute(text("SELECT observed_at FROM instants")).scalar_one()

    assert stored == "2026-01-01 00:00:00+00:00"
