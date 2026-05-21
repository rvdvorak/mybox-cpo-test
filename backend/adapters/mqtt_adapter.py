"""MQTT adapter — subscribes the station event stream and persists it.

This is the MQTT half of the protocol-adapter pattern (architektura 5.1): it
parses raw broker messages into domain events and drives ``SessionService``,
which stays unaware of MQTT. A future OCPP adapter would be a sibling file.

The module also hosts the offline detector (architektura 3.5) — a periodic DB
sweep that flags stations whose heartbeat has gone stale. Both ``run_*``
coroutines are background tasks owned by the FastAPI lifespan (see ``app.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from aiomqtt import Client, MqttError
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import BackendConfig
from ..db.models import MeterReading, Session, Station
from ..domain.events import BootEvent, MeterReadingEvent, StatusChangedEvent
from ..domain.session_service import SessionService

logger = logging.getLogger(__name__)

# Backend subscribes every station's event topics (architektura 3.1).
EVENTS_TOPIC = "cpo/v1/stations/+/events/+"
RECONNECT_DELAY_SEC = 5.0
OFFLINE_CHECK_INTERVAL_SEC = 10.0
# Fixed client id — with clean_session=True a stable id simply means a clean
# reconnect after a backend restart (architektura 5.4).
_CLIENT_ID = "cpo-backend"


def _now() -> datetime:
    """Current UTC time — the backend's clock, used as message receipt time."""
    return datetime.now(timezone.utc)


# --- MQTT subscriber ---------------------------------------------------------


async def run_mqtt_adapter(
    config: BackendConfig,
    sessionmaker: async_sessionmaker[AsyncSession],
    session_service: SessionService,
) -> None:
    """Subscribe the station event stream, reconnecting on broker errors.

    ``clean_session=True`` (architektura 5.4): the subscriber keeps no broker
    queue across a restart — retained boot + status messages replay the current
    state on every (re)connect. The broker may not be ready when the backend
    starts (no depends_on until Phase 7), so a lost connection is retried.
    """
    while True:
        try:
            async with Client(
                hostname=config.mqtt_host,
                port=config.mqtt_port,
                identifier=_CLIENT_ID,
                clean_session=True,
            ) as client:
                await client.subscribe(EVENTS_TOPIC, qos=1)
                logger.info("MQTT adapter subscribed to %s", EVENTS_TOPIC)
                async for message in client.messages:
                    await _handle_message(message, sessionmaker, session_service)
        except MqttError as exc:
            logger.warning(
                "MQTT error: %s — reconnecting in %ss", exc, RECONNECT_DELAY_SEC
            )
            await asyncio.sleep(RECONNECT_DELAY_SEC)


async def _handle_message(
    message,
    sessionmaker: async_sessionmaker[AsyncSession],
    session_service: SessionService,
) -> None:
    """Persist one station message inside its own transaction.

    The adapter owns the transaction boundary (architektura 5.1): one MQTT
    message = one transaction. A malformed payload or a handler error is logged
    and swallowed — a single bad message must not kill the subscriber loop.
    """
    topic = message.topic.value
    parts = topic.split("/")
    # cpo / v1 / stations / {id} / events / {suffix}
    if len(parts) != 6 or parts[4] != "events":
        logger.warning("Ignoring message on unexpected topic %s", topic)
        return
    station_id, suffix = parts[3], parts[5]

    try:
        async with sessionmaker() as db:
            await _dispatch(db, station_id, suffix, message.payload, session_service)
            await db.commit()
    except Exception:  # noqa: BLE001 — one bad message must not stop the stream
        logger.exception("Failed to handle message on %s", topic)


async def _dispatch(
    db: AsyncSession,
    station_id: str,
    suffix: str,
    raw_payload: bytes,
    session_service: SessionService,
) -> None:
    """Route a message to its handler by the topic suffix (architektura 4.2)."""
    if suffix == "heartbeat":
        await _handle_heartbeat(db, station_id)
    elif suffix == "boot":
        await _handle_boot(db, station_id, raw_payload)
    elif suffix == "status":
        await _handle_status(db, station_id, raw_payload, session_service)
    elif suffix == "meter":
        await _handle_meter(db, raw_payload, session_service)
    else:
        logger.warning("Unknown event suffix '%s' for %s", suffix, station_id)


# --- Event handlers ----------------------------------------------------------


def _parse_json(raw_payload: bytes) -> dict | None:
    """Decode a JSON object payload, or ``None`` if it is malformed."""
    try:
        data = json.loads(raw_payload)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


async def _handle_heartbeat(db: AsyncSession, station_id: str) -> None:
    """Stamp ``last_heartbeat`` with the receipt time.

    The payload ``ts`` is deliberately ignored — it rides on ESP32 clocks prone
    to drift, so the backend's own clock is the authoritative liveness signal
    (architektura 3.5).
    """
    await db.execute(
        update(Station).where(Station.id == station_id).values(last_heartbeat=_now())
    )


async def _handle_boot(db: AsyncSession, station_id: str, raw_payload: bytes) -> None:
    """Refresh the station row from its retained boot announcement.

    The row is guaranteed to exist (seeded in Phase 3); boot fills in the real
    hardware attributes that the seed could only default.
    """
    data = _parse_json(raw_payload)
    if data is None:
        logger.warning("boot for %s has a malformed payload, ignoring", station_id)
        return
    try:
        event = BootEvent.model_validate(data)
    except ValidationError as exc:
        logger.warning("boot for %s failed validation: %s", station_id, exc)
        return
    await db.execute(
        update(Station)
        .where(Station.id == event.station_id)
        .values(
            connector_type=event.connector_type,
            max_power_kw=event.max_power_kw,
            firmware_version=event.firmware_version,
            monitoring_agent=event.monitoring_agent,
        )
    )


async def _handle_status(
    db: AsyncSession,
    station_id: str,
    raw_payload: bytes,
    session_service: SessionService,
) -> None:
    """Apply a status transition and drive the session lifecycle."""
    data = _parse_json(raw_payload)
    if data is None:
        logger.warning("status for %s has a malformed payload, ignoring", station_id)
        return

    station = await db.get(Station, station_id)
    if station is None:
        logger.warning("status for unknown station %s, ignoring", station_id)
        return

    # Offline arrives as an LWT / clean-shutdown payload that carries no ts and
    # no transaction_id — it is not a full StatusChangedEvent (architektura 3.3).
    if data.get("status") == "Offline":
        station.current_status = "Offline"
        return

    try:
        event = StatusChangedEvent.model_validate(data)
    except ValidationError as exc:
        logger.warning("status for %s failed validation: %s", station_id, exc)
        return

    station.current_status = event.status

    if event.status == "Charging":
        if event.transaction_id is None:
            logger.warning(
                "Charging status for %s has no transaction_id, skipping session",
                event.station_id,
            )
            return
        # Idempotent on transaction_id — a replayed retained status is harmless.
        await session_service.start_session(
            db,
            station_id=event.station_id,
            transaction_id=event.transaction_id,
            start_time=event.ts,
            start_meter_wh=station.last_meter_wh or 0,
        )
    elif event.status == "Finishing":
        end_meter_wh = await _resolve_end_meter(db, event.station_id)
        if end_meter_wh is not None:
            await session_service.stop_session(
                db,
                station_id=event.station_id,
                end_time=event.ts,
                end_meter_wh=end_meter_wh,
            )
    elif event.status == "Faulted":
        await session_service.fault_session(db, event)


async def _resolve_end_meter(db: AsyncSession, station_id: str) -> int | None:
    """End meter for a normal stop (architektura 5.2).

    The active session's last meter reading, falling back to its start meter
    when no reading was recorded. Returns ``None`` when the station has no
    active session — there is nothing to close.
    """
    active = await db.scalar(
        select(Session).where(
            Session.station_id == station_id, Session.end_time.is_(None)
        )
    )
    if active is None:
        return None
    last_energy = await db.scalar(
        select(MeterReading.energy_wh)
        .where(MeterReading.session_id == active.id)
        .order_by(MeterReading.ts.desc())
        .limit(1)
    )
    return last_energy if last_energy is not None else active.start_meter_wh


async def _handle_meter(
    db: AsyncSession, raw_payload: bytes, session_service: SessionService
) -> None:
    """Persist an energy meter sample via the domain service."""
    data = _parse_json(raw_payload)
    if data is None:
        logger.warning("meter event has a malformed payload, ignoring")
        return
    try:
        event = MeterReadingEvent.model_validate(data)
    except ValidationError as exc:
        logger.warning("meter event failed validation: %s", exc)
        return
    await session_service.apply_meter_reading(db, event)


# --- Offline detector --------------------------------------------------------


async def run_offline_detector(
    config: BackendConfig,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Periodically flag stations whose heartbeat has gone stale (architektura 3.5).

    The slow-path complement to the LWT: it covers a network partition where the
    Last Will never reaches the broker, and a station that never connects at all.
    """
    while True:
        await asyncio.sleep(OFFLINE_CHECK_INTERVAL_SEC)
        try:
            cutoff = _now() - timedelta(seconds=config.heartbeat_timeout_sec)
            async with sessionmaker() as db:
                result = await db.execute(
                    update(Station)
                    .where(
                        Station.last_heartbeat.is_not(None),
                        Station.last_heartbeat < cutoff,
                        Station.current_status != "Offline",
                    )
                    .values(current_status="Offline")
                )
                await db.commit()
                if result.rowcount:
                    logger.info(
                        "Offline detector marked %d station(s) Offline",
                        result.rowcount,
                    )
        except Exception:  # noqa: BLE001 — keep the detector alive across errors
            logger.exception("Offline detector sweep failed")
