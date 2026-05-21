"""REST API adapter — HTTP half of the protocol-adapter pattern (architektura 7).

Read endpoints query the database directly; the ``POST`` endpoints publish MQTT
commands and return ``202`` — the session row itself is created later by the
MQTT adapter when the station reports ``status: Charging`` (Phase 4 decision).
``SessionService`` is therefore not touched here.

All errors use the ``{"error", "code"}`` envelope (architektura 7), not the
FastAPI default ``{"detail": ...}`` — see ``register_error_handlers``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from aiomqtt import MqttError
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import MeterReading, Session, Station
from .mqtt_adapter import publish_command

logger = logging.getLogger(__name__)

# Detail view shows a meter graph over the recent past — architektura 7.2.
_RECENT_READINGS_LIMIT = 60


# --- Error envelope ----------------------------------------------------------


class ApiError(Exception):
    """Domain-level HTTP error carrying the architektura 7 ``{error, code}`` envelope.

    ``extra`` merges extra top-level keys into the body — e.g. ``current_status``
    on a 409 ``STATION_NOT_AVAILABLE`` (architektura 7.4).
    """

    def __init__(
        self, status_code: int, code: str, message: str, extra: dict | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.extra = extra or {}
        super().__init__(message)


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers so every error response uses the {error, code} envelope."""

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "code": exc.code, **exc.extra},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # Keep the envelope consistent even for malformed request bodies.
        return JSONResponse(
            status_code=422,
            content={"error": "Request validation failed", "code": "VALIDATION_ERROR"},
        )


# --- Response models (architektura 7.1-7.5) ----------------------------------


class ActiveSessionOut(BaseModel):
    transaction_id: str
    start_time: datetime
    energy_wh: int
    power_kw: float


class StationSummaryOut(BaseModel):
    station_id: str
    status: str
    connector_type: str
    max_power_kw: float
    last_heartbeat: datetime | None
    active_session: ActiveSessionOut | None


class StationsResponse(BaseModel):
    stations: list[StationSummaryOut]


class MeterReadingOut(BaseModel):
    ts: datetime
    power_kw: float
    energy_wh: int


class StationDetailOut(BaseModel):
    station_id: str
    status: str
    connector_type: str
    max_power_kw: float
    firmware_version: str | None
    monitoring_agent: str | None
    last_heartbeat: datetime | None
    active_session: ActiveSessionOut | None
    recent_meter_readings: list[MeterReadingOut]


class SessionOut(BaseModel):
    transaction_id: str
    station_id: str
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int | None
    start_meter_wh: int
    end_meter_wh: int | None
    total_kwh: float | None
    total_cost: float | None
    end_reason: str | None


class SessionsResponse(BaseModel):
    sessions: list[SessionOut]
    total: int


class StartRequest(BaseModel):
    transaction_id: str | None = None


class StartResponse(BaseModel):
    transaction_id: str
    issued_at: datetime
    message: str


class StopResponse(BaseModel):
    issued_at: datetime
    message: str


# --- Dependencies ------------------------------------------------------------


async def get_db(request: Request) -> AsyncSession:
    """Yield an ``AsyncSession`` scoped to one request (architektura 7)."""
    async with request.app.state.sessionmaker() as db:
        yield db


# --- Helpers -----------------------------------------------------------------


async def _active_session_payload(
    db: AsyncSession, session: Session
) -> ActiveSessionOut:
    """Build the ``active_session`` block, enriched from the last meter reading.

    A freshly opened session may have no reading yet — fall back to its start
    meter and zero power.
    """
    last = await db.scalar(
        select(MeterReading)
        .where(MeterReading.session_id == session.id)
        .order_by(MeterReading.ts.desc())
        .limit(1)
    )
    if last is not None:
        energy_wh, power_kw = last.energy_wh, float(last.power_kw)
    else:
        energy_wh, power_kw = session.start_meter_wh, 0.0
    return ActiveSessionOut(
        transaction_id=session.transaction_id,
        start_time=session.start_time,
        energy_wh=energy_wh,
        power_kw=power_kw,
    )


async def _find_active_session(db: AsyncSession, station_id: str) -> Session | None:
    """Return the open session for a station, or ``None`` (uses the partial index)."""
    return await db.scalar(
        select(Session).where(
            Session.station_id == station_id, Session.end_time.is_(None)
        )
    )


def _session_out(session: Session) -> SessionOut:
    """Map a ``Session`` row to its API shape, computing ``duration_seconds``."""
    duration = None
    if session.end_time is not None:
        duration = int((session.end_time - session.start_time).total_seconds())
    return SessionOut(
        transaction_id=session.transaction_id,
        station_id=session.station_id,
        start_time=session.start_time,
        end_time=session.end_time,
        duration_seconds=duration,
        start_meter_wh=session.start_meter_wh,
        end_meter_wh=session.end_meter_wh,
        total_kwh=float(session.total_kwh) if session.total_kwh is not None else None,
        total_cost=float(session.total_cost)
        if session.total_cost is not None
        else None,
        end_reason=session.end_reason,
    )


# --- Endpoints ---------------------------------------------------------------

rest_router = APIRouter()


@rest_router.get("/stations", response_model=StationsResponse)
async def list_stations(db: AsyncSession = Depends(get_db)) -> StationsResponse:
    """List every station with its current status and active session (architektura 7.1)."""
    stations = (await db.scalars(select(Station).order_by(Station.id))).all()
    summaries = []
    for station in stations:
        active = await _find_active_session(db, station.id)
        summaries.append(
            StationSummaryOut(
                station_id=station.id,
                status=station.current_status,
                connector_type=station.connector_type,
                max_power_kw=float(station.max_power_kw),
                last_heartbeat=station.last_heartbeat,
                active_session=await _active_session_payload(db, active)
                if active is not None
                else None,
            )
        )
    return StationsResponse(stations=summaries)


@rest_router.get("/stations/{station_id}", response_model=StationDetailOut)
async def get_station(
    station_id: str, db: AsyncSession = Depends(get_db)
) -> StationDetailOut:
    """Station detail with the recent meter graph data (architektura 7.2)."""
    station = await db.get(Station, station_id)
    if station is None:
        raise ApiError(404, "STATION_NOT_FOUND", f"Station {station_id} not found")

    active = await _find_active_session(db, station_id)

    # Meter graph: readings of the active session, else of the last finished one.
    graph_session = active
    if graph_session is None:
        graph_session = await db.scalar(
            select(Session)
            .where(Session.station_id == station_id)
            .order_by(Session.start_time.desc())
            .limit(1)
        )

    readings: list[MeterReadingOut] = []
    if graph_session is not None:
        rows = (
            await db.scalars(
                select(MeterReading)
                .where(MeterReading.session_id == graph_session.id)
                .order_by(MeterReading.ts.desc())
                .limit(_RECENT_READINGS_LIMIT)
            )
        ).all()
        # Query is newest-first for the LIMIT; the graph wants oldest-first.
        readings = [
            MeterReadingOut(ts=r.ts, power_kw=float(r.power_kw), energy_wh=r.energy_wh)
            for r in reversed(rows)
        ]

    return StationDetailOut(
        station_id=station.id,
        status=station.current_status,
        connector_type=station.connector_type,
        max_power_kw=float(station.max_power_kw),
        firmware_version=station.firmware_version,
        monitoring_agent=station.monitoring_agent,
        last_heartbeat=station.last_heartbeat,
        active_session=await _active_session_payload(db, active)
        if active is not None
        else None,
        recent_meter_readings=readings,
    )


@rest_router.get("/stations/{station_id}/sessions", response_model=SessionsResponse)
async def list_sessions(
    station_id: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> SessionsResponse:
    """Paginated session history for a station, newest first (architektura 7.3)."""
    station = await db.get(Station, station_id)
    if station is None:
        raise ApiError(404, "STATION_NOT_FOUND", f"Station {station_id} not found")

    total = await db.scalar(
        select(func.count())
        .select_from(Session)
        .where(Session.station_id == station_id)
    )
    rows = (
        await db.scalars(
            select(Session)
            .where(Session.station_id == station_id)
            .order_by(Session.start_time.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return SessionsResponse(sessions=[_session_out(s) for s in rows], total=total or 0)


@rest_router.post("/stations/{station_id}/start")
async def start_charging(
    station_id: str,
    request: Request,
    body: StartRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Publish a start command to a station (architektura 7.4).

    Idempotent: a retry carrying a ``transaction_id`` that already has a session
    returns ``200`` with that session instead of re-issuing the command.
    """
    transaction_id = body.transaction_id if body is not None else None

    station = await db.get(Station, station_id)
    if station is None:
        raise ApiError(404, "STATION_NOT_FOUND", f"Station {station_id} not found")

    if transaction_id is not None:
        existing = await db.scalar(
            select(Session).where(Session.transaction_id == transaction_id)
        )
        if existing is not None:
            return JSONResponse(
                status_code=200,
                content=StartResponse(
                    transaction_id=transaction_id,
                    issued_at=existing.start_time,
                    message="Session already exists",
                ).model_dump(mode="json"),
            )

    if station.current_status != "Available":
        raise ApiError(
            409,
            "STATION_NOT_AVAILABLE",
            "Station is not available",
            extra={"current_status": station.current_status},
        )

    tx_id = transaction_id or str(uuid.uuid4())
    issued_at = datetime.now(timezone.utc)
    try:
        await publish_command(
            request.app.state.config,
            station_id,
            "start_charging",
            {"transaction_id": tx_id, "issued_at": issued_at.isoformat()},
        )
    except MqttError as exc:
        raise ApiError(
            503, "MQTT_PUBLISH_FAILED", "Failed to publish command to the broker"
        ) from exc

    return JSONResponse(
        status_code=202,
        content=StartResponse(
            transaction_id=tx_id,
            issued_at=issued_at,
            message="Start command published to station",
        ).model_dump(mode="json"),
    )


@rest_router.post("/stations/{station_id}/stop")
async def stop_charging(
    station_id: str, request: Request, db: AsyncSession = Depends(get_db)
) -> JSONResponse:
    """Publish a stop command for a station's active session (architektura 7.5)."""
    station = await db.get(Station, station_id)
    if station is None:
        raise ApiError(404, "STATION_NOT_FOUND", f"Station {station_id} not found")

    active = await _find_active_session(db, station_id)
    if active is None:
        raise ApiError(409, "NO_ACTIVE_SESSION", "No active session to stop")

    issued_at = datetime.now(timezone.utc)
    try:
        await publish_command(
            request.app.state.config,
            station_id,
            "stop_charging",
            {"issued_at": issued_at.isoformat()},
        )
    except MqttError as exc:
        raise ApiError(
            503, "MQTT_PUBLISH_FAILED", "Failed to publish command to the broker"
        ) from exc

    return JSONResponse(
        status_code=202,
        content=StopResponse(
            issued_at=issued_at, message="Stop command published to station"
        ).model_dump(mode="json"),
    )
