"""SeriesSpec rejects flag combinations whose series would have no defined meaning."""

import pytest

from shiro_mlops.service.data_explorer.series import SeriesField, SeriesSpec


def _spec(**flags: bool) -> SeriesSpec:
    return SeriesSpec(
        dataset="cwa_forecast_audits",
        table="raw_cwa_forecast_release",
        time_column="issued_at",
        fields={"version_count": SeriesField(sql="1", unit="count")},
        group_columns=("status",),
        filter_keys=frozenset(),
        filters=lambda filters: ([], {}),
        **flags,
    )


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
        _spec(**flags)


def test_count_series_without_gap_fill_is_accepted() -> None:
    spec = _spec(count_rows=True, gap_fill=False)

    assert spec.request_params == frozenset({"start", "end", "bucket"})
