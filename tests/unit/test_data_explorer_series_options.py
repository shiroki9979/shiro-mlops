"""A dataset rejects series flag combinations whose series would have no defined meaning."""

from dataclasses import replace

import pytest

from shiro_mlops.service.data_explorer.datasets import CWA_FORECAST_AUDITS, Dataset
from shiro_mlops.service.data_explorer.series import (
    SeriesField,
    SeriesOptions,
    series_request_params,
)


def _dataset(**flags: bool) -> Dataset:
    options = SeriesOptions(
        fields={"version_count": SeriesField(sql="1", unit="count")},
        group_columns=("status",),
        **flags,
    )
    return replace(CWA_FORECAST_AUDITS, series=options)


@pytest.mark.parametrize(
    "flags",
    [
        {"count_rows": True, "member_sum": True, "gap_fill": False},
        {"count_rows": True, "gap_fill": True},
        {"count_rows": True, "rows_share_time": True, "gap_fill": False},
        {"member_sum": True, "rows_share_time": True},
    ],
    ids=["count-of-member-sums", "gap-filled-counts", "count-merging-rows", "sum-merging-rows"],
)
def test_contradictory_series_flags_are_rejected_at_declaration(flags: dict[str, bool]) -> None:
    with pytest.raises(ValueError, match="cwa_forecast_audits"):
        _dataset(**flags)


def test_count_series_without_gap_fill_is_accepted() -> None:
    dataset = _dataset(count_rows=True, gap_fill=False)

    assert series_request_params(dataset, dataset.series) == frozenset(
        {"start", "end", "bucket", "dataset_id", "status", "missing_geocode"}
    )
