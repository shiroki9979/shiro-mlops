"""HTTP adapter for the trusted-network Data Explorer read surface."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.data.repository import TimeSeriesRepository
from shiro_mlops.service.data_explorer.access import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.catalog import DatasetStatusCatalog
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.dataset_reader import DatasetReader
from shiro_mlops.service.data_explorer.db import ExplorerDb
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError, ExplorerQueryError
from shiro_mlops.service.data_explorer.hourly_load import (
    HOURLY_LOAD_SERIES,
    HourlyLoadReader,
    HourlyLoadSeriesField,
)
from shiro_mlops.service.data_explorer.power import (
    NationalSupplyDemandReader,
    RegionalSupplyDemandReader,
    UnitGenerationReader,
)
from shiro_mlops.service.data_explorer.schemas import (
    ListEnvelope,
    SeriesResponse,
    StatusResponse,
)
from shiro_mlops.service.data_explorer.series import (
    Agg,
    Bucket,
    SeriesReader,
    SeriesRequest,
    SeriesSpec,
    TooManyPointsError,
)
from shiro_mlops.service.data_explorer.weather import (
    FORECAST_SERIES,
    OBSERVATION_SERIES,
    ForecastAuditReader,
    ForecastReader,
    ForecastSeriesField,
    ObservationAuditReader,
    ObservationReader,
    ObservationSeriesField,
    plan_forecast_series,
)

router = APIRouter(prefix="/data", tags=["data-explorer"])

SeriesPlan = Callable[[ExplorerDb, dict[str, str]], tuple[SeriesSpec, dict[str, str]]]


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


def _run_series(
    request: Request,
    spec: SeriesSpec,
    *,
    fields: list[str] | None,
    bucket: Bucket,
    agg: Agg,
    plan: SeriesPlan | None = None,
) -> SeriesResponse:
    """Read a series; `plan` lets a dataset specialise its spec from the request first."""
    _ensure_enabled()
    try:
        engine = _engine(request)
        params = _series_query_params(request)
        if plan is not None:
            spec, params = plan(ExplorerDb(engine), params)
        series_request = SeriesRequest.build(spec, params, fields=fields, bucket=bucket, agg=agg)
        return SeriesReader(engine, spec).read(series_request)
    except TooManyPointsError as exc:
        suggested = exc.suggested_bucket.value if exc.suggested_bucket else None
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "suggested_bucket": suggested}
        ) from exc
    except ExplorerQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from exc


def _series_query_params(request: Request) -> dict[str, str]:
    """Single-valued view of the query string; `fields` is read separately as a list."""
    return {key: value for key, value in request.query_params.items() if value != ""}


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


@router.get("/power/load/series", response_model=SeriesResponse)
def hourly_load_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    subject: str | None = None,
    fields: list[HourlyLoadSeriesField] | None = Query(default=None),
    bucket: Bucket = Bucket.AUTO,
    agg: Agg = Agg.AVG,
) -> SeriesResponse:
    """Chart series of hourly load per subject over an exact closed window of up to 92 days.

    `bucket=auto` picks the finest of raw, 1h and 1d that keeps every series within 1,200
    points and all series within 10,000 points; an explicit bucket over those limits is
    rejected with 422 and a machine-readable `suggested_bucket`.
    """
    del start, end, subject
    return _run_series(
        request,
        HOURLY_LOAD_SERIES,
        fields=[field.value for field in fields] if fields else None,
        bucket=bucket,
        agg=agg,
    )


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


@router.get("/weather/observations/series", response_model=SeriesResponse)
def observation_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    station_id: str | None = None,
    fields: list[ObservationSeriesField] | None = Query(default=None),
    bucket: Bucket = Bucket.AUTO,
    agg: Agg = Agg.AVG,
) -> SeriesResponse:
    """Chart series of CWA station observations, one per station and field.

    Stations are never combined, so `group_by` is rejected with 422. `fields` defaults to
    `temperature_c`; hours without an observation up to now appear as `null` points.
    """
    del start, end, station_id
    return _run_series(
        request,
        OBSERVATION_SERIES,
        fields=[field.value for field in fields] if fields else None,
        bucket=bucket,
        agg=agg,
    )


@router.get("/weather/forecasts", response_model=ListEnvelope)
def list_forecasts(request: Request) -> ListEnvelope:
    """List persisted CWA township forecast vintages."""
    return _run_list(request, ForecastReader)


@router.get("/weather/forecasts/series", response_model=SeriesResponse)
def forecast_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    dataset_id: str | None = None,
    geocode: str | None = None,
    issued_at: str | None = None,
    source_updated_at: str | None = None,
    all_vintages: bool = False,
    fields: list[ForecastSeriesField] | None = Query(default=None),
    bucket: Bucket = Bucket.AUTO,
    agg: Agg = Agg.AVG,
) -> SeriesResponse:
    """Chart series of CWA township forecasts on `valid_from`, one per geocode.

    Like the list, the latest release is shown unless a version is named; with
    `all_vintages=true` or a version filter each issue (`dataset_id`, `issued_at`, using its
    newest correction unless `source_updated_at` is given) is a separate series per geocode.
    Forecasts are not gap-filled: only points with a value are returned. `fields` defaults
    to `temperature_c`.
    """
    del start, end, dataset_id, geocode, issued_at, source_updated_at, all_vintages
    return _run_series(
        request,
        FORECAST_SERIES,
        fields=[field.value for field in fields] if fields else None,
        bucket=bucket,
        agg=agg,
        plan=plan_forecast_series,
    )


@router.get("/audits/cwa-observations", response_model=ListEnvelope)
def list_observation_audits(request: Request) -> ListEnvelope:
    """List CWA observation batch audit headers without raw payloads."""
    return _run_list(request, ObservationAuditReader)


@router.get("/audits/cwa-forecasts", response_model=ListEnvelope)
def list_forecast_audits(request: Request) -> ListEnvelope:
    """List CWA forecast release audit headers without raw payloads."""
    return _run_list(request, ForecastAuditReader)
