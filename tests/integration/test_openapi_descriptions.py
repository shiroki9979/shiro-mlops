"""Docstrings FastAPI turns into OpenAPI text are interface text: they must never go empty."""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from shiro_mlops.service.api import app

HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _operations_without_description(openapi: dict[str, Any]) -> list[str]:
    return [
        f"{method.upper()} {path}"
        for path, item in openapi["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS and not operation.get("description", "").strip()
    ]


def _prediction_item_descriptions(openapi: dict[str, Any]) -> dict[str, str]:
    """Description of every schema a response lists under ``predictions``, by schema name."""
    schemas = openapi["components"]["schemas"]
    names = {
        schema["properties"]["predictions"]["items"]["$ref"].rsplit("/", 1)[-1]
        for schema in schemas.values()
        if "$ref" in schema.get("properties", {}).get("predictions", {}).get("items", {})
    }
    return {name: schemas[name].get("description", "").strip() for name in names}


def test_every_api_operation_has_a_description() -> None:
    openapi = app.openapi()

    assert openapi["paths"]
    assert _operations_without_description(openapi) == []


def test_every_prediction_item_schema_has_a_description() -> None:
    descriptions = _prediction_item_descriptions(app.openapi())

    assert "PredictionItem" in descriptions
    assert len(descriptions) > 1
    assert {name for name, text in descriptions.items() if not text} == set()


class _DescribedItem(BaseModel):
    """One predicted hour."""

    value: float


class _UndescribedItem(BaseModel):
    value: float


class _DescribedResponse(BaseModel):
    predictions: list[_DescribedItem]


class _UndescribedResponse(BaseModel):
    predictions: list[_UndescribedItem]


def _sample_openapi() -> dict[str, Any]:
    sample = FastAPI()

    @sample.get("/described", response_model=_DescribedResponse)
    def described() -> _DescribedResponse:
        """Answer with described items."""
        return _DescribedResponse(predictions=[])

    @sample.post("/undescribed", response_model=_UndescribedResponse)
    def undescribed() -> _UndescribedResponse:
        return _UndescribedResponse(predictions=[])

    @sample.get("/blank")
    def blank() -> None:
        """ """

    return sample.openapi()


def test_a_route_without_docstring_is_reported() -> None:
    assert _operations_without_description(_sample_openapi()) == [
        "POST /undescribed",
        "GET /blank",
    ]


def test_a_prediction_item_without_docstring_is_reported() -> None:
    descriptions = _prediction_item_descriptions(_sample_openapi())

    assert descriptions == {"_DescribedItem": "One predicted hour.", "_UndescribedItem": ""}
