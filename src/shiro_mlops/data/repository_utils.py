"""Raw API payload serialization shared by the database repositories."""

import json
from typing import Any


def serialize_raw_payload(payload: Any) -> str:
    """Serialize a source payload to JSON text for JSONB or SQLite TEXT storage.

    String payloads such as XML responses become JSON string literals, so the
    stored text is always valid JSON and round-trips through
    ``deserialize_raw_payload``.
    """
    return json.dumps(payload, ensure_ascii=False)


def deserialize_raw_payload(payload: Any) -> Any:
    """Decode a stored payload from JSON text, passing already-parsed values through.

    Engines from ``get_timescale_engine`` return JSONB as JSON text, so a string
    here is always JSON text; a stored string payload decodes back to that string.
    """
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("raw_payload must contain valid JSON") from exc
    return payload
