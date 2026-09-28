"""HTTP adapter for the trusted-network Data Explorer read surface."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.access import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.catalog import DatasetStatusCatalog
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError, ExplorerQueryError
from shiro_mlops.service.data_explorer.hourly_load import HourlyLoadReader
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from shiro_mlops.service.data_explorer.schemas import ListEnvelope, StatusResponse
from shiro_mlops.service.data_explorer.weather import (
    ForecastAuditReader,
    ForecastReader,
    ObservationAuditReader,
    ObservationReader,
)

router = APIRouter(prefix="/data", tags=["data-explorer"])


def _repository(request: Request) -> TimeSeriesRepository:
    from shiro_mlops.service import api as service_api

    return service_api.repository_store or TimeSeriesRepository()


def _engine(request: Request) -> Engine:
    return _repository(request).engine


def _ensure_enabled() -> None:
    if not is_data_explorer_enabled():
        raise HTTPException(status_code=404, detail="Data Explorer is not enabled")


def _query_params(request: Request) -> dict[str, Any]:
    return {key: value for key, value in request.query_params.items() if value not in (None, "")}


def _run_list(request: Request, reader_cls: type[DatasetReader]) -> ListEnvelope:
    _ensure_enabled()
    try:
        params = _query_params(request)
        reader_cls.validate_cursor_request(params)
        return reader_cls(_engine(request)).list(params)
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
        return DatasetStatusCatalog(_engine(request)).status()
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from exc


@router.get("/power/load", response_model=ListEnvelope)
def list_hourly_load(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    subject: str | None = None,
    limit: int | None = Query(default=None),
    cursor: str | None = None,
) -> ListEnvelope:
    """List persisted hourly electricity load rows."""
    del start, end, subject, limit, cursor
    return _run_list(request, HourlyLoadReader)


@router.get("/power/supply-demand", response_model=ListEnvelope)
def list_national_supply_demand(request: Request) -> ListEnvelope:
    """List persisted national supply-demand snapshots."""
    return _run_list(request, NationalSupplyDemandReader)


@router.get("/power/regional", response_model=ListEnvelope)
def list_regional_supply_demand(request: Request) -> ListEnvelope:
    """List persisted regional supply-demand snapshots."""
    return _run_list(request, RegionalSupplyDemandReader)


@router.get("/power/units", response_model=ListEnvelope)
def list_unit_generation(request: Request) -> ListEnvelope:
    """List persisted unit-generation snapshots."""
    return _run_list(request, UnitGenerationReader)


@router.get("/weather/observations", response_model=ListEnvelope)
def list_observations(request: Request) -> ListEnvelope:
    """List persisted CWA station observations."""
    return _run_list(request, ObservationReader)


@router.get("/weather/forecasts", response_model=ListEnvelope)
def list_forecasts(request: Request) -> ListEnvelope:
    """List persisted CWA township forecast vintages."""
    return _run_list(request, ForecastReader)


@router.get("/audits/cwa-observations", response_model=ListEnvelope)
def list_observation_audits(request: Request) -> ListEnvelope:
    """List CWA observation batch audit headers without raw payloads."""
    return _run_list(request, ObservationAuditReader)


@router.get("/audits/cwa-forecasts", response_model=ListEnvelope)
def list_forecast_audits(request: Request) -> ListEnvelope:
    """List CWA forecast release audit headers without raw payloads."""
    return _run_list(request, ForecastAuditReader)
