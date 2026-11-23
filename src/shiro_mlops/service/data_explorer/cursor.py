"""Opaque, stateless, filter-bound keyset cursor for Data Explorer lists."""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

CURSOR_VERSION = 2
# 最長的合法 cursor（鄉鎮預報，篩選全帶、時間含微秒）約 700 字元；超過此長度的不是本服務發出的，
# 解碼前就拒絕，不為它配置記憶體或解析 JSON。
MAX_CURSOR_LENGTH = 4096


class CursorError(ValueError):
    """Raised when a cursor cannot be decoded or does not match the current query."""


def _canonical_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """Normalize filter payloads so equivalent queries share the same binding."""
    canonical: dict[str, Any] = {}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        canonical[key] = value
    return dict(sorted(canonical.items()))


def encode_cursor(*, dataset: str, filters: dict[str, Any], key: dict[str, Any]) -> str:
    """Encode the last sort key and current filters into an opaque cursor token."""
    payload = {
        "v": CURSOR_VERSION,
        "ds": dataset,
        "f": _canonical_filters(filters),
        "k": key,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor_payload(token: str, *, dataset: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(token) > MAX_CURSOR_LENGTH:
        raise CursorError("Invalid cursor")
    padded = token + "=" * (-len(token) % 4)
    try:
        payload = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
    # json.loads raises RecursionError, not ValueError, on deeply nested input.
    except (ValueError, RecursionError) as exc:
        raise CursorError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise CursorError("Invalid cursor")
    if payload.get("v") != CURSOR_VERSION:
        raise CursorError("Incompatible cursor version")
    if payload.get("ds") != dataset:
        raise CursorError("Cursor dataset mismatch")
    cursor_filters = payload.get("f")
    key = payload.get("k")
    if not isinstance(cursor_filters, dict) or not isinstance(key, dict):
        raise CursorError("Invalid cursor")
    return cursor_filters, key


def decode_cursor_filters(token: str, *, dataset: str) -> dict[str, Any]:
    """取得 cursor 固定的篩選條件，避免跨頁期間重新解析動態預設值。"""
    filters, _ = _decode_cursor_payload(token, dataset=dataset)
    return filters


def decode_cursor(token: str, *, dataset: str, filters: dict[str, Any]) -> dict[str, Any]:
    """Decode a cursor and reject invalid, version-incompatible, or filter-bound tokens."""
    cursor_filters, key = _decode_cursor_payload(token, dataset=dataset)
    if cursor_filters != _canonical_filters(filters):
        raise CursorError("Cursor filter mismatch")
    return key
