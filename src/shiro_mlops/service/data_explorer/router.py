"""HTTP adapter for the trusted-network Data Explorer read surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.access import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.schemas import ListEnvelope, StatusResponse
from shiro_mlops.service.data_explorer.store import (
    DatabaseUnavailableError,
    DataExplorerStore,
    ExplorerQueryError,
)

router = APIRouter(prefix="/data", tags=["data-explorer"])


def _repository(request: Request) -> TimeSeriesRepository:
    from shiro_mlops.service import api as service_api

    return service_api.repository_store or TimeSeriesRepository()


def _store(request: Request) -> DataExplorerStore:
    return DataExplorerStore(_repository(request).engine)


def _ensure_enabled() -> None:
    if not is_data_explorer_enabled():
        raise HTTPException(status_code=404, detail="Data Explorer is not enabled")


def _query_params(request: Request) -> dict[str, Any]:
    return {key: value for key, value in request.query_params.items() if value not in (None, "")}


def _run_list(request: Request, reader) -> ListEnvelope:
    _ensure_enabled()
    try:
        return reader(_store(request), _query_params(request))
    except CursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExplorerQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from exc


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    """Return shared dataset availability, freshness, and completeness."""
    _ensure_enabled()
    try:
        return _store(request).status()
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from exc


@router.get("/power/load", response_model=ListEnvelope)
def list_hourly_load(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    limit: int | None = Query(default=None),
    cursor: str | None = None,
) -> ListEnvelope:
    """List persisted hourly electricity load rows."""
    del start, end, location, limit, cursor
    return _run_list(request, lambda store, params: store.list_hourly_load(params))


@router.get("/power/supply-demand", response_model=ListEnvelope)
def list_national_supply_demand(request: Request) -> ListEnvelope:
    """List persisted national supply-demand snapshots."""
    return _run_list(request, lambda store, params: store.list_national_supply_demand(params))


@router.get("/power/regional", response_model=ListEnvelope)
def list_regional_supply_demand(request: Request) -> ListEnvelope:
    """List persisted regional supply-demand snapshots."""
    return _run_list(request, lambda store, params: store.list_regional_supply_demand(params))


@router.get("/power/units", response_model=ListEnvelope)
def list_unit_generation(request: Request) -> ListEnvelope:
    """List persisted unit-generation snapshots."""
    return _run_list(request, lambda store, params: store.list_unit_generation(params))


@router.get("/weather/observations", response_model=ListEnvelope)
def list_observations(request: Request) -> ListEnvelope:
    """List persisted CWA station observations."""
    return _run_list(request, lambda store, params: store.list_observations(params))


@router.get("/weather/forecasts", response_model=ListEnvelope)
def list_forecasts(request: Request) -> ListEnvelope:
    """List persisted CWA township forecast vintages."""
    return _run_list(request, lambda store, params: store.list_forecasts(params))


@router.get("/audits/cwa-observations", response_model=ListEnvelope)
def list_observation_audits(request: Request) -> ListEnvelope:
    """List CWA observation batch audit headers without raw payloads."""
    return _run_list(request, lambda store, params: store.list_observation_audits(params))


@router.get("/audits/cwa-forecasts", response_model=ListEnvelope)
def list_forecast_audits(request: Request) -> ListEnvelope:
    """List CWA forecast release audit headers without raw payloads."""
    return _run_list(request, lambda store, params: store.list_forecast_audits(params))
