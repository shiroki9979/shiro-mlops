"""Opaque keyset cursor encoding stays filter-bound and versioned."""

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode

import pytest

from shiro_mlops.service.data_explorer.cursor import (
    CursorError,
    decode_cursor,
    encode_cursor,
)


def test_cursor_round_trip_preserves_sort_key() -> None:
    """編碼後的 cursor 必須能還原最後一筆排序鍵。"""
    filters = {"start": "2026-08-01T00:00:00+08:00", "end": "2026-08-02T00:00:00+08:00"}
    key = {"time": "2026-08-01T12:00:00+08:00", "subject": "nationwide"}

    token = encode_cursor(dataset="hourly_load", filters=filters, key=key)

    assert "=" not in token
    assert json.loads(urlsafe_b64decode(token + "=" * (-len(token) % 4)))["v"] == 2
    assert decode_cursor(token, dataset="hourly_load", filters=filters) == key


def test_cursor_rejects_filter_mismatch() -> None:
    """篩選條件改變後不得繼續使用舊 cursor。"""
    token = encode_cursor(
        dataset="hourly_load",
        filters={"subject": "nationwide"},
        key={"time": "2026-08-01T12:00:00+08:00"},
    )

    with pytest.raises(CursorError, match="filter"):
        decode_cursor(token, dataset="hourly_load", filters={"subject": "north"})


def test_cursor_rejects_invalid_or_incompatible_payload() -> None:
    """格式無效、資料集不符或版本不相容的 cursor 必須拒絕。"""
    with pytest.raises(CursorError):
        decode_cursor("not-a-cursor", dataset="hourly_load", filters={})

    token = encode_cursor(
        dataset="hourly_load", filters={}, key={"time": "2026-08-01T00:00:00+08:00"}
    )
    with pytest.raises(CursorError, match="dataset"):
        decode_cursor(token, dataset="national_supply_demand", filters={})

    legacy = urlsafe_b64encode(b'{"v":1,"ds":"hourly_load","f":{},"k":{}}').decode()
    with pytest.raises(CursorError, match="version"):
        decode_cursor(legacy, dataset="hourly_load", filters={})


def _token(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_deeply_nested_cursor_json_is_an_invalid_cursor_not_a_crash() -> None:
    """json.loads raises RecursionError, not ValueError, on thousands of nested arrays."""
    token = urlsafe_b64encode(b"[" * 10000).decode("ascii").rstrip("=")

    with pytest.raises(CursorError, match="Invalid cursor"):
        decode_cursor(token, dataset="hourly_load", filters={})


def test_cursor_far_longer_than_any_issued_one_is_refused_before_decoding() -> None:
    oversized = _token({"v": 2, "ds": "hourly_load", "f": {"subject": "x" * 20000}, "k": {}})

    with pytest.raises(CursorError, match="Invalid cursor"):
        decode_cursor(oversized, dataset="hourly_load", filters={"subject": "x" * 20000})


def test_the_longest_cursor_a_dataset_can_issue_still_round_trips() -> None:
    filters = {
        "start": "2026-08-01T00:00:00.123456+08:00",
        "end": "2026-08-02T00:00:00.123456+08:00",
        "dataset": "cwa_forecasts",
        "dataset_id": "F-D0047-089",
        "geocode": "63000000",
        "issued_at": "2026-08-01T05:30:00.123456+08:00",
        "source_updated_at": "2026-08-01T05:35:00.123456+08:00",
        "all_vintages": "true",
    }
    key = {
        "valid_from": "2026-08-01T12:00:00.123456+08:00",
        "issued_at": "2026-08-01T05:30:00.123456+08:00",
        "source_updated_at": "2026-08-01T05:35:00.123456+08:00",
        "dataset_id": "F-D0047-089",
        "geocode": "63000000",
    }

    token = encode_cursor(dataset="cwa_forecasts", filters=filters, key=key)

    assert decode_cursor(token, dataset="cwa_forecasts", filters=filters) == key


@pytest.mark.parametrize(
    "payload",
    [None, [], "text", 7, True, {"v": 2, "ds": "hourly_load", "f": [], "k": {}}, {"v": "2"}],
)
def test_cursor_payload_of_the_wrong_shape_is_refused(payload: object) -> None:
    with pytest.raises(CursorError):
        decode_cursor(_token(payload), dataset="hourly_load", filters={})


@pytest.mark.parametrize("token", ["", "!!!!", "a", "====", "\x00", "Zm9v\n"])
def test_cursor_that_is_not_base64_json_is_refused(token: str) -> None:
    with pytest.raises(CursorError):
        decode_cursor(token, dataset="hourly_load", filters={})
