"""Session lifecycle business logic — the core of the protocol-adapter pattern.

``SessionService`` knows nothing about MQTT or FastAPI. It receives domain events
or explicit parameters plus a SQLAlchemy ``AsyncSession`` and persists domain
state. The MQTT adapter (Phase 4) and REST adapter (Phase 5) are thin layers that
translate their wire format into these calls.

Transaction policy: the service only ``add``s / ``flush``es — it never commits.
The calling adapter owns the transaction boundary, so it can compose several
operations atomically.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import MeterReading, Session, Station
from .events import MeterReadingEvent, StatusChangedEvent
from .pricing import PricingStrategy

logger = logging.getLogger(__name__)


class SessionService:
    """Stateless service — one instance is shared across all requests/messages."""

    def __init__(self, pricing: PricingStrategy) -> None:
        self._pricing = pricing

    async def start_session(
        self,
        db: AsyncSession,
        *,
        station_id: str,
        transaction_id: str,
        start_time: datetime,
        start_meter_wh: int,
    ) -> tuple[Session, bool]:
        """Open a charging session, driven by the MQTT ``status: Charging`` event.

        Idempotent (architektura 7.4): if a session with ``transaction_id``
        already exists, it is returned unchanged instead of inserting a duplicate.

        Returns ``(session, created)`` — ``created`` is ``True`` only for a
        genuinely new row, so the adapter can emit ``session_started`` once and
        not re-emit on a retained-status replay (architektura 7.6).
        """
        existing = await db.scalar(
            select(Session).where(Session.transaction_id == transaction_id)
        )
        if existing is not None:
            logger.info(
                "start_session: transaction %s already exists, returning it",
                transaction_id,
            )
            return existing, False

        session = Session(
            id=uuid.uuid4(),
            station_id=station_id,
            transaction_id=transaction_id,
            start_time=start_time,
            start_meter_wh=start_meter_wh,
        )
        db.add(session)
        await db.flush()
        logger.info("Started session %s on station %s", transaction_id, station_id)
        return session, True

    async def apply_meter_reading(
        self, db: AsyncSession, event: MeterReadingEvent
    ) -> MeterReading | None:
        """Persist a meter sample and refresh the station's cached meter value.

        Called by the MQTT adapter (Phase 4). If the station has no active
        session the reading is dropped with a warning — a meter sample without
        an open session is a protocol anomaly, not a fatal error.
        """
        active = await self._active_session(db, event.station_id)
        if active is None:
            logger.warning(
                "Meter reading for %s has no active session, dropping",
                event.station_id,
            )
            return None

        # Deduplicate in the application layer (architektura 3.2): a QoS 1
        # meter message may be redelivered. Keyed on (session_id, ts) — no
        # unique constraint, that would be a schema deviation.
        duplicate = await db.scalar(
            select(MeterReading.id).where(
                MeterReading.session_id == active.id,
                MeterReading.ts == event.ts,
            )
        )
        if duplicate is not None:
            logger.info(
                "Duplicate meter reading for session %s at %s, skipping",
                active.id,
                event.ts,
            )
            return None

        reading = MeterReading(
            session_id=active.id,
            station_id=event.station_id,
            ts=event.ts,
            power_kw=event.power_kw,
            energy_wh=event.energy_wh,
        )
        db.add(reading)

        station = await db.get(Station, event.station_id)
        if station is not None:
            station.last_meter_wh = event.energy_wh

        await db.flush()
        return reading

    async def stop_session(
        self,
        db: AsyncSession,
        *,
        station_id: str,
        end_time: datetime,
        end_meter_wh: int,
    ) -> Session | None:
        """Close the active session normally (architektura 5.2).

        Called by the MQTT adapter on a non-charging status transition. Returns
        ``None`` if the station has no active session.
        """
        active = await self._active_session(db, station_id)
        if active is None:
            logger.warning("stop_session: no active session for %s", station_id)
            return None

        active.end_time = end_time
        active.end_meter_wh = end_meter_wh
        active.end_reason = "completed"
        active.total_kwh, active.total_cost = self._compute_totals(
            active.start_meter_wh, end_meter_wh
        )
        await db.flush()
        logger.info(
            "Stopped session %s on station %s", active.transaction_id, station_id
        )
        return active

    async def fault_session(
        self, db: AsyncSession, event: StatusChangedEvent
    ) -> Session | None:
        """Close the active session on a Faulted status (architektura 5.3).

        ``end_meter_wh`` is the last meter reading of this session, or
        ``start_meter_wh`` if no reading was recorded. Returns ``None`` if the
        station has no active session.
        """
        active = await self._active_session(db, event.station_id)
        if active is None:
            return None

        last_energy = await db.scalar(
            select(MeterReading.energy_wh)
            .where(MeterReading.session_id == active.id)
            .order_by(MeterReading.ts.desc())
            .limit(1)
        )
        end_meter_wh = last_energy if last_energy is not None else active.start_meter_wh

        active.end_time = event.ts
        active.end_meter_wh = end_meter_wh
        active.end_reason = "faulted"
        active.total_kwh, active.total_cost = self._compute_totals(
            active.start_meter_wh, end_meter_wh
        )
        await db.flush()
        logger.info(
            "Faulted session %s on station %s",
            active.transaction_id,
            event.station_id,
        )
        return active

    async def _active_session(
        self, db: AsyncSession, station_id: str
    ) -> Session | None:
        """Return the open session for a station (uses the partial index)."""
        return await db.scalar(
            select(Session).where(
                Session.station_id == station_id, Session.end_time.is_(None)
            )
        )

    def _compute_totals(
        self, start_meter_wh: int, end_meter_wh: int
    ) -> tuple[Decimal, Decimal]:
        """Compute (total_kwh, total_cost) per architektura 5.2.

        Decimal arithmetic with explicit quantize — billing values must round
        deterministically. The formula is applied literally; a negative delta
        (simulator meter reset, architektura 9.3) is not clamped.
        """
        total_kwh = (Decimal(end_meter_wh - start_meter_wh) / Decimal(1000)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
        total_cost = self._pricing.cost_for_kwh(total_kwh).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return total_kwh, total_cost
