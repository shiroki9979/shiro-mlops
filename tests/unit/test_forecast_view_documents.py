"""The public JSON documents match the fixtures that the Nginx smoke check serves (ADR-0015 §2.4)."""

import json
from datetime import datetime, timedelta

import pytest

from shiro_mlops.data.forecast_view import (
    FORECAST_TRACK_RECORD_FILE,
    LATEST_ISSUED_FORECAST_FILE,
    encode_document,
    forecast_track_record_document,
    latest_issued_forecast_document,
)
from shiro_mlops.data.issued_forecast import IssuedForecast, IssuedForecastStep
from tests.conftest import FIXTURES_DIR

PUBLISHED_FIXTURES = FIXTURES_DIR / "published"


def _fixture(name: str) -> dict:
    return json.loads((PUBLISHED_FIXTURES / name).read_text(encoding="utf-8"))


def test_latest_issued_forecast_fixture_is_what_the_export_writes() -> None:
    """Anchor 09:00 for a 10:15 issue: the 10:00 step is not after the issue time."""
    anchor = datetime(2026, 11, 20, 9, 0)
    forecast = IssuedForecast(
        issued_at=datetime(2026, 11, 20, 10, 15),
        load_anchor=anchor,
        status="normal",
        model_sha256="c" * 64,
        mlflow_model_version="3",
        steps=tuple(
            IssuedForecastStep(anchor + timedelta(hours=k), load_mw)
            for k, load_mw in enumerate([30800.0, 31250.5, 31980.0, 32410.25], start=1)
        ),
    )

    document = latest_issued_forecast_document(forecast)

    assert json.loads(encode_document(document)) == _fixture(LATEST_ISSUED_FORECAST_FILE)


def test_track_record_fixture_is_what_the_export_writes_below_seven_days() -> None:
    artifact = {"cutoff": "2026-11-20T10:00:00", "accumulated_days": 3, "metrics": None}

    document = forecast_track_record_document(artifact)

    assert json.loads(encode_document(document)) == _fixture(FORECAST_TRACK_RECORD_FILE)


def test_a_non_finite_number_fails_the_export_instead_of_publishing_invalid_json() -> None:
    with pytest.raises(ValueError):
        encode_document({"issued_at": None, "steps": [{"predicted_load_mw": float("nan")}]})
