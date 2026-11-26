"""HTTP adapter for the trusted-network Data Explorer read surface."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BeforeValidator
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from shiro_mlops.service.data_explorer.access import is_data_explorer_enabled
from shiro_mlops.service.data_explorer.cursor import CursorError
from shiro_mlops.service.data_explorer.dataset_query import DatasetQuery
from shiro_mlops.service.data_explorer.datasets import (
    CWA_FORECAST_AUDITS,
    CWA_FORECASTS,
    CWA_OBSERVATION_AUDITS,
    CWA_OBSERVATIONS,
    HOURLY_LOAD,
    NATIONAL_SUPPLY_DEMAND,
    REGIONAL_SUPPLY_DEMAND,
    UNIT_GENERATION,
    Dataset,
)
from shiro_mlops.service.data_explorer.datasets.power import (
    HourlyLoadSeriesField,
    NationalSeriesField,
    RegionalSeriesField,
    UnitGroupBy,
    UnitSeriesField,
)
from shiro_mlops.service.data_explorer.datasets.weather import (
    ForecastSeriesField,
    ObservationSeriesField,
)
from shiro_mlops.service.data_explorer.errors import DatabaseUnavailableError, ExplorerQueryError
from shiro_mlops.service.data_explorer.schemas import (
    ListEnvelope,
    SeriesResponse,
    StatusResponse,
)
from shiro_mlops.service.data_explorer.series import Agg, Bucket, TooManyPointsError

router = APIRouter(prefix="/data", tags=["data-explorer"])


def _empty_reads_as(default: object) -> BeforeValidator:
    """A declared parameter sent empty reads as not given (rest-api.md §5.1), so the type
    validation FastAPI runs on it must see the default instead of an empty string."""
    return BeforeValidator(lambda value: default if value == "" else value)


_EMPTY_AS_NONE = _empty_reads_as(None)


def _without_empty_values(values: object) -> object:
    """`fields=` arrives as `[""]`; an empty repeat reads as not given, as any empty value does."""
    if not isinstance(values, list):
        return values
    return [value for value in values if value != ""] or None


_EMPTY_DROPPED = BeforeValidator(_without_empty_values)


def _engine(request: Request) -> Engine:
    engine: Engine = request.app.state.repository.engine
    return engine


def _ensure_enabled() -> None:
    if not is_data_explorer_enabled():
        raise HTTPException(status_code=404, detail="Data Explorer is not enabled")


def _query_params(request: Request) -> dict[str, str]:
    """Last value of each query parameter, empty ones included so an undeclared one is still
    rejected; series read `fields` separately as a list."""
    return dict(request.query_params)


@contextmanager
def _explorer_errors() -> Iterator[None]:
    """Map the query layer's refusals to HTTP once for every endpoint."""
    try:
        yield
    except CursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TooManyPointsError as exc:
        suggested = exc.suggested_bucket.value if exc.suggested_bucket else None
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "suggested_bucket": suggested}
        ) from exc
    except ExplorerQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (DatabaseUnavailableError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="Persistence unavailable") from exc


def _run_list(request: Request, dataset: Dataset) -> ListEnvelope:
    _ensure_enabled()
    with _explorer_errors():
        return DatasetQuery(_engine(request)).list(dataset, _query_params(request))


def _run_series(
    request: Request,
    dataset: Dataset,
    *,
    fields: Sequence[StrEnum] | None = None,
    bucket: Bucket,
    agg: Agg | None = None,
) -> SeriesResponse:
    _ensure_enabled()
    with _explorer_errors():
        return DatasetQuery(_engine(request)).series(
            dataset,
            _query_params(request),
            fields=_field_names(fields),
            bucket=bucket,
            agg=agg,
        )


def _field_names(fields: Sequence[StrEnum] | None) -> list[str] | None:
    return [field.value for field in fields] if fields else None


@router.get("/status", response_model=StatusResponse)
def get_status(request: Request) -> StatusResponse:
    """Return shared dataset availability, freshness, and completeness."""
    _ensure_enabled()
    with _explorer_errors():
        return DatasetQuery(_engine(request)).status()


@router.get("/power/load", response_model=ListEnvelope)
def list_hourly_load(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    subject: str | None = None,
    limit: Annotated[int | None, _EMPTY_AS_NONE] = None,
    cursor: str | None = None,
) -> ListEnvelope:
    """List persisted hourly electricity load rows."""
    del start, end, subject, limit, cursor
    return _run_list(request, HOURLY_LOAD)


@router.get("/power/load/series", response_model=SeriesResponse)
def hourly_load_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    subject: str | None = None,
    fields: Annotated[list[HourlyLoadSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
) -> SeriesResponse:
    """Chart series of hourly load per subject over an exact closed window of up to 92 days.

    `bucket=auto` picks the finest of raw, 1h and 1d that keeps every series within 1,200
    points and all series within 10,000 points; an explicit bucket over those limits is
    rejected with 422 and a machine-readable `suggested_bucket`.
    """
    del start, end, subject
    return _run_series(
        request,
        HOURLY_LOAD,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/power/supply-demand", response_model=ListEnvelope)
def list_national_supply_demand(request: Request) -> ListEnvelope:
    """List persisted national supply-demand snapshots."""
    return _run_list(request, NATIONAL_SUPPLY_DEMAND)


@router.get("/power/supply-demand/series", response_model=SeriesResponse)
def national_supply_demand_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    fields: Annotated[list[NationalSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
) -> SeriesResponse:
    """Ungrouped national supply-demand series in MW or percent over a closed window.

    `fields` defaults to `curr_load_mw` and `real_hr_maxi_sply_capacity_mw`, whose distance
    is the supply margin. Bucket, aggregation and point limits follow the shared series
    contract.
    """
    del start, end
    return _run_series(
        request,
        NATIONAL_SUPPLY_DEMAND,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/power/regional", response_model=ListEnvelope)
def list_regional_supply_demand(request: Request) -> ListEnvelope:
    """List persisted regional supply-demand snapshots."""
    return _run_list(request, REGIONAL_SUPPLY_DEMAND)


@router.get("/power/regional/series", response_model=SeriesResponse)
def regional_supply_demand_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    region: str | None = None,
    fields: Annotated[list[RegionalSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
) -> SeriesResponse:
    """Regional supply-demand series in MW, one series per region and field.

    Always grouped by `region`; there is no four-region total. `fields` defaults to
    `load_mw`. A region absent from a bucket yields a `null` point in that region's series.
    """
    del start, end, region
    return _run_series(
        request,
        REGIONAL_SUPPLY_DEMAND,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/power/units", response_model=ListEnvelope)
def list_unit_generation(request: Request) -> ListEnvelope:
    """List persisted unit-generation snapshots."""
    return _run_list(request, UNIT_GENERATION)


@router.get("/power/units/series", response_model=SeriesResponse)
def unit_generation_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    unit_type: str | None = None,
    unit_name: str | None = None,
    fields: Annotated[list[UnitSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    group_by: Annotated[
        UnitGroupBy, _empty_reads_as(UnitGroupBy.UNIT_TYPE)
    ] = UnitGroupBy.UNIT_TYPE,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
) -> SeriesResponse:
    """Chart series of unit generation per unit type, or as one total, over up to 92 days.

    Members sharing a timestamp are summed first (NULL members are skipped, not read as 0),
    then the time aggregation runs over those totals: `1h` `max` is the highest 10-minute
    total within the hour. `unit_type` and `unit_name` narrow the summed members;
    `group_by=none` returns one series for every remaining member.
    """
    del start, end, unit_type, unit_name, group_by
    return _run_series(
        request,
        UNIT_GENERATION,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/weather/observations", response_model=ListEnvelope)
def list_observations(request: Request) -> ListEnvelope:
    """List persisted CWA station observations."""
    return _run_list(request, CWA_OBSERVATIONS)


@router.get("/weather/observations/series", response_model=SeriesResponse)
def observation_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    station_id: str | None = None,
    fields: Annotated[list[ObservationSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
) -> SeriesResponse:
    """Chart series of CWA station observations, one per station and field.

    Stations are never combined, so `group_by` is rejected with 422. `fields` defaults to
    `temperature_c`; hours without an observation up to now appear as `null` points.
    """
    del start, end, station_id
    return _run_series(
        request,
        CWA_OBSERVATIONS,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/weather/forecasts", response_model=ListEnvelope)
def list_forecasts(request: Request) -> ListEnvelope:
    """List persisted CWA township forecast vintages."""
    return _run_list(request, CWA_FORECASTS)


@router.get("/weather/forecasts/series", response_model=SeriesResponse)
def forecast_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    dataset_id: str | None = None,
    geocode: str | None = None,
    issued_at: str | None = None,
    source_updated_at: str | None = None,
    all_vintages: Annotated[bool, _empty_reads_as(False)] = False,
    fields: Annotated[list[ForecastSeriesField] | None, _EMPTY_DROPPED, Query()] = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
    agg: Annotated[Agg, _empty_reads_as(Agg.AVG)] = Agg.AVG,
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
        CWA_FORECASTS,
        fields=fields,
        bucket=bucket,
        agg=agg,
    )


@router.get("/audits/cwa-observations", response_model=ListEnvelope)
def list_observation_audits(request: Request) -> ListEnvelope:
    """List CWA observation batch audit headers without raw payloads."""
    return _run_list(request, CWA_OBSERVATION_AUDITS)


@router.get("/audits/cwa-forecasts", response_model=ListEnvelope)
def list_forecast_audits(request: Request) -> ListEnvelope:
    """List CWA forecast release audit headers without raw payloads."""
    return _run_list(request, CWA_FORECAST_AUDITS)


@router.get("/audits/cwa-observations/series", response_model=SeriesResponse)
def observation_audit_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    status: str | None = None,
    missing_station_id: str | None = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
) -> SeriesResponse:
    """Status timeline of CWA observation batches over an exact closed window of up to 92 days.

    One series per `status`; each point counts the batches fetched in that bucket, and `raw`
    gives one point of value 1 per batch. Buckets without batches are omitted, and `fields`
    or `agg` are rejected with 422.
    """
    del start, end, status, missing_station_id
    return _run_series(request, CWA_OBSERVATION_AUDITS, bucket=bucket)


@router.get("/audits/cwa-forecasts/series", response_model=SeriesResponse)
def forecast_audit_series(
    request: Request,
    start: str | None = None,
    end: str | None = None,
    dataset_id: str | None = None,
    status: str | None = None,
    missing_geocode: str | None = None,
    bucket: Annotated[Bucket, _empty_reads_as(Bucket.AUTO)] = Bucket.AUTO,
) -> SeriesResponse:
    """Status timeline of CWA forecast versions by `issued_at`, over a window of up to 92 days.

    One series per `status`; each point counts the versions issued in that bucket, and `raw`
    gives one point of value 1 per version, so versions sharing `issued_at` stay separate.
    Buckets without versions are omitted, and `fields` or `agg` are rejected with 422.
    """
    del start, end, dataset_id, status, missing_geocode
    return _run_series(request, CWA_FORECAST_AUDITS, bucket=bucket)
