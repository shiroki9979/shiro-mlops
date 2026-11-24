"""Request timestamps: only RFC 3339 inside the supported range; anything else is a 422, not a guess."""

from datetime import datetime

import pytest

from shiro_mlops.service.data_explorer.datasets import CWA_FORECASTS, HOURLY_LOAD
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import ExplorerQueryError
from shiro_mlops.service.data_explorer.query import ExplorerQuery, list_params, resolve_window
from shiro_mlops.service.data_explorer.timefmt import parse_request_time


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-20T00:00:00+08:00", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-20T00:00:00", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-20T00:00", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-19T16:00:00Z", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-19t16:00:00z", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-20T01:00:00+09:00", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-19T11:00:00-05:00", datetime(2026, 11, 20, 0, 0)),
        ("2026-11-20T00:00:00.250+08:00", datetime(2026, 11, 20, 0, 0, 0, 250000)),
        ("2026-11-20T00:00:00.123456+08:00", datetime(2026, 11, 20, 0, 0, 0, 123456)),
        ("2024-02-29T23:59:59+08:00", datetime(2024, 2, 29, 23, 59, 59)),
    ],
)
def test_rfc_3339_timestamps_read_as_taiwan_local(value: str, expected: datetime) -> None:
    assert parse_request_time(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("2026-11-20T00:00:00 08:00", id="plus-sign-decoded-as-space"),
        pytest.param("now", id="word-now"),
        pytest.param("today", id="word-today"),
        pytest.param("12:00", id="time-only"),
        pytest.param("2026", id="year-only"),
        pytest.param("2026-11", id="year-month"),
        pytest.param("2026-11-20", id="date-only"),
        pytest.param("20261120T000000", id="basic-format"),
        pytest.param("2026-11-20 00:00:00", id="space-separator"),
        pytest.param("2026-11-20T00:00:00 EST", id="zone-name"),
        pytest.param("2026-11-20T00:00:00+0800", id="offset-without-colon"),
        pytest.param("2026-11-20T00:00:00+08", id="hour-only-offset"),
        pytest.param("2026-13-01T00:00:00", id="month-13"),
        pytest.param("2026-02-30T00:00:00", id="february-30"),
        pytest.param("2026-11-20T24:00:00", id="hour-24"),
        pytest.param("2026-11-20T00:60:00", id="minute-60"),
        pytest.param("2026-11-20T00:00:00+25:00", id="offset-25-hours"),
        pytest.param(" 2026-11-20T00:00:00", id="leading-space"),
        pytest.param("2026-11-20T00:00:00\n", id="trailing-newline"),
        pytest.param("2026-11-20T00:00:00\x00", id="nul-byte"),
        pytest.param("", id="empty"),
        pytest.param("NaT", id="nat"),
        pytest.param("२०२६-11-20T00:00:00", id="non-ascii-digits"),
    ],
)
def test_anything_else_is_refused(value: str) -> None:
    with pytest.raises(ValueError):
        parse_request_time(value)


@pytest.mark.parametrize(
    "value",
    [
        "0001-01-01T00:00:00",
        "1500-01-01T00:00:00",
        "1677-09-22T00:00:00",
        "1969-12-31T23:59:59+08:00",
        "2200-01-01T00:00:00+08:00",
        "3000-01-01T00:00:00",
        "9999-12-31T23:59:59",
        "0001-01-01T00:00:00+14:00",
        "9999-12-31T23:59:59-14:00",
    ],
)
def test_timestamps_outside_the_supported_range_are_refused(value: str) -> None:
    with pytest.raises(ValueError, match="between"):
        parse_request_time(value)


@pytest.mark.parametrize("value", ["1970-01-01T00:00:00+08:00", "2199-12-31T23:59:59.999999+08:00"])
def test_the_edges_of_the_supported_range_are_accepted(value: str) -> None:
    assert parse_request_time(value).isoformat() == value.removesuffix("+08:00")


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-11-20T00:00:00 08:00", "2026-11-20T12:00:00 08:00"),
        ("0001-01-01T00:00:00", "0001-01-02T00:00:00"),
        ("1500-01-01T00:00:00", "1500-01-02T00:00:00"),
        ("3000-01-01T00:00:00", "3000-01-02T00:00:00"),
        ("2026-11-20", "2026-11-21"),
        ("now", "today"),
    ],
)
def test_a_window_that_is_not_two_supported_timestamps_is_a_query_error(
    start: str, end: str
) -> None:
    with pytest.raises(ExplorerQueryError, match="RFC 3339"):
        resolve_window(start, end, max_days=31)


def test_a_window_may_still_be_given_as_datetimes() -> None:
    window = resolve_window(datetime(2026, 11, 20), datetime(2026, 11, 21), max_days=31)

    assert (window.start, window.end) == (datetime(2026, 11, 20), datetime(2026, 11, 21))


def test_a_datetime_window_outside_the_supported_range_is_a_query_error() -> None:
    with pytest.raises(ExplorerQueryError, match="RFC 3339"):
        resolve_window(datetime(1500, 1, 1), datetime(1500, 1, 2), max_days=31)


def test_zero_length_window_is_accepted() -> None:
    window = resolve_window("2026-11-20T08:00:00+08:00", "2026-11-20T08:00:00+08:00", max_days=1)

    assert window.start == window.end


@pytest.mark.parametrize(
    "issued_at",
    ["2026-11-20T05:30:00 08:00", "2026-11", "0001-01-01T00:00:00", "tomorrow"],
)
def test_an_instant_filter_takes_only_supported_timestamps(issued_at: str) -> None:
    query = ExplorerQuery.from_params(
        CWA_FORECASTS,
        {
            "start": "2026-11-20T00:00:00+08:00",
            "end": "2026-11-21T00:00:00+08:00",
            "issued_at": issued_at,
        },
    )

    with pytest.raises(ExplorerQueryError, match="issued_at must be a valid RFC 3339"):
        CWA_FORECASTS.clauses(ExplorerDb.__new__(ExplorerDb), query.filters)


@pytest.mark.parametrize(
    "value", ["\x00", "nation\x00wide", "a\x1fb", "a\x7fb", "line\nbreak", "tab\there"]
)
@pytest.mark.parametrize("name", ["subject", "start", "cursor", "limit"])
def test_a_parameter_with_control_characters_is_a_query_error(name: str, value: str) -> None:
    """PostgreSQL refuses NUL in a parameter with a plain ValueError, which would be a 500."""
    with pytest.raises(ExplorerQueryError, match=f"{name} must not contain control characters"):
        list_params(HOURLY_LOAD, {name: value})


def test_an_undeclared_parameter_is_reported_before_its_control_characters() -> None:
    with pytest.raises(ExplorerQueryError, match="unsupported list parameters: nope"):
        list_params(HOURLY_LOAD, {"nope": "\x00"})


def test_a_parameter_may_hold_any_printable_text() -> None:
    params = list_params(HOURLY_LOAD, {"subject": "臺北 – north (1)", "limit": ""})

    assert params == {"subject": "臺北 – north (1)"}
