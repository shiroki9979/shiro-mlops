"""The deployed forecast track record asset: its lineage and which jobs leave it out."""

from dagster import AssetKey

from shiro_mlops.pipelines.definitions import defs
from shiro_mlops.pipelines.forecast_track_record import FORECAST_TRACK_RECORD_ASSET
from shiro_mlops.pipelines.issued_forecast import ISSUED_FORECAST_ASSET, issued_forecast_job
from tests.helpers import selected_asset_names, task_jobs


def test_track_record_lineage_depends_on_issued_forecasts_and_hourly_load() -> None:
    node = defs.resolve_asset_graph().get(AssetKey(FORECAST_TRACK_RECORD_ASSET))

    assert {key.to_user_string() for key in node.parent_keys} == {
        ISSUED_FORECAST_ASSET,
        "raw_taipower_load",
    }


def test_issuing_and_task_jobs_never_compile_the_track_record() -> None:
    for job in [issued_forecast_job, *task_jobs()]:
        assert FORECAST_TRACK_RECORD_ASSET not in selected_asset_names(job), job.name
