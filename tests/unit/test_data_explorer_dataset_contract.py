"""Every dataset's declared filters drive cursor binding and series parameters alike."""

from dataclasses import replace

import pytest

from shiro_mlops.service.data_explorer.datasets import DATASETS, HOURLY_LOAD, Dataset
from shiro_mlops.service.data_explorer.datasets.audits import (
    FORECAST_AUDIT_SERIES,
    OBSERVATION_AUDIT_SERIES,
)
from shiro_mlops.service.data_explorer.datasets.definition import (
    Exact,
    Filter,
    InstantEquals,
    OneOf,
)
from shiro_mlops.service.data_explorer.datasets.power import (
    HOURLY_LOAD_SERIES,
    NATIONAL_SERIES,
    REGIONAL_SERIES,
    UNIT_GENERATION_SERIES,
)
from shiro_mlops.service.data_explorer.datasets.weather import FORECAST_SERIES, OBSERVATION_SERIES
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery
from shiro_mlops.service.data_explorer.series import Bucket, SeriesRequest

WINDOW = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
SERIES_BY_DATASET = {
    spec.dataset.id: spec
    for spec in (
        HOURLY_LOAD_SERIES,
        NATIONAL_SERIES,
        REGIONAL_SERIES,
        UNIT_GENERATION_SERIES,
        OBSERVATION_SERIES,
        FORECAST_SERIES,
        OBSERVATION_AUDIT_SERIES,
        FORECAST_AUDIT_SERIES,
    )
}
DECLARED_FILTERS = [
    pytest.param(dataset, item, id=f"{dataset.id}-{item.name}")
    for dataset in DATASETS.values()
    for item in dataset.filters
]


def _valid_value(item: Filter) -> str:
    if isinstance(item, OneOf):
        return item.values[0]
    if isinstance(item, InstantEquals):
        return "2026-08-01T12:00:00.123456+08:00"
    return "value"


def test_registry_lists_the_eight_datasets_in_status_order() -> None:
    assert list(DATASETS) == [
        "hourly_load",
        "national_supply_demand",
        "regional_supply_demand",
        "unit_generation",
        "cwa_observations",
        "cwa_forecasts",
        "cwa_observation_audits",
        "cwa_forecast_audits",
    ]
    assert set(SERIES_BY_DATASET) == set(DATASETS)


@pytest.mark.parametrize(("dataset", "item"), DECLARED_FILTERS)
def test_every_declared_filter_is_bound_into_the_cursor(dataset: Dataset, item: Filter) -> None:
    value = _valid_value(item)

    query = ExplorerQuery.from_params(dataset, {**WINDOW, item.name: value})

    assert query.filters[item.name] == value


def test_a_newly_declared_filter_is_bound_without_any_other_change() -> None:
    """新增篩選只需宣告在資料集定義上，cursor 就會綁定它；沒有另一份白名單要同步。"""
    extended = replace(HOURLY_LOAD, filters=(*HOURLY_LOAD.filters, Exact(name="new_filter")))

    query = ExplorerQuery.from_params(extended, {**WINDOW, "new_filter": "x"})

    assert query.filters["new_filter"] == "x"


@pytest.mark.parametrize("dataset", DATASETS.values(), ids=lambda dataset: dataset.id)
def test_parameters_another_dataset_declares_are_not_bound(dataset: Dataset) -> None:
    foreign = {
        item.name
        for other in DATASETS.values()
        for item in other.filters
        if item.name not in dataset.filter_names
    }
    params = {**WINDOW, **{name: "value" for name in foreign}}

    query = ExplorerQuery.from_params(dataset, params)

    assert set(query.filters) == {"start", "end", "dataset"}


@pytest.mark.parametrize(("dataset", "item"), DECLARED_FILTERS)
def test_series_accepts_exactly_the_filters_declared_for_series(
    dataset: Dataset, item: Filter
) -> None:
    spec = SERIES_BY_DATASET[dataset.id]
    params = {**WINDOW, item.name: _valid_value(item)}

    if item.in_series:
        request = SeriesRequest.build(spec, params, fields=None, bucket=Bucket.AUTO)
        assert request.filters[item.name] == params[item.name]
    else:
        with pytest.raises(ExplorerQueryError, match="unsupported series parameters"):
            SeriesRequest.build(spec, params, fields=None, bucket=Bucket.AUTO)


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"sort": ("subject", "time")}, "sort must start with time_column"),
        ({"instant_columns": frozenset()}, "time_column must be an instant column"),
        ({"list_columns": ("time", "load_mw")}, "list_columns must select sort columns subject"),
        (
            {"filters": (Exact(name="subject"), Exact(name="subject"))},
            "filter names must be unique",
        ),
    ],
    ids=["sort", "instant", "select", "unique-filters"],
)
def test_inconsistent_dataset_declarations_are_rejected(
    change: dict[str, object], problem: str
) -> None:
    with pytest.raises(ValueError, match=problem):
        replace(HOURLY_LOAD, **change)
