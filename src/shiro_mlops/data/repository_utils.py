"""Raw API payload serialization shared by the database repositories."""

import json
from typing import Any


def serialize_raw_payload(payload: Any) -> str:
    """Serialize raw API payload to JSON text for database column storage."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False)


def deserialize_raw_payload(payload: Any) -> Any:
    """Deserialize raw API payload from JSON text or pass through parsed objects."""
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("raw_payload must contain valid JSON") from exc
    return payload
