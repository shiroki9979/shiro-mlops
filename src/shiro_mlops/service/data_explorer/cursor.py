"""Opaque, stateless, filter-bound keyset cursor for Data Explorer lists."""

from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any

CURSOR_VERSION = 1


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


def decode_cursor(token: str, *, dataset: str, filters: dict[str, Any]) -> dict[str, Any]:
    """Decode a cursor and reject invalid, version-incompatible, or filter-bound tokens."""
    padded = token + "=" * (-len(token) % 4)
    try:
        payload = json.loads(urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CursorError("Invalid cursor") from exc
    if not isinstance(payload, dict):
        raise CursorError("Invalid cursor")
    if payload.get("v") != CURSOR_VERSION:
        raise CursorError("Incompatible cursor version")
    if payload.get("ds") != dataset:
        raise CursorError("Cursor dataset mismatch")
    if payload.get("f") != _canonical_filters(filters):
        raise CursorError("Cursor filter mismatch")
    key = payload.get("k")
    if not isinstance(key, dict):
        raise CursorError("Invalid cursor")
    return key
