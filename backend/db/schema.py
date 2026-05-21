"""Schema initialization and station seeding (architektura 6.3).

Both operations run on backend startup and are idempotent — a restart over an
existing database is a no-op.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .models import Base, Station

logger = logging.getLogger(__name__)

# 5 stations from architektura 10.2. connector_type / firmware_version are not
# in that table — defaults from architektura 10.1 are used; the retained MQTT
# boot message (Phase 4) overwrites them with the real values anyway.
SEED_STATIONS = [
    {"id": "ST-001", "max_power_kw": 22.0, "monitoring_agent": "none"},
    {"id": "ST-002", "max_power_kw": 11.0, "monitoring_agent": "rpi"},
    {"id": "ST-003", "max_power_kw": 22.0, "monitoring_agent": "none"},
    {"id": "ST-004", "max_power_kw": 22.0, "monitoring_agent": "none"},
    {"id": "ST-005", "max_power_kw": 7.4, "monitoring_agent": "none"},
]


async def init_schema(engine: AsyncEngine) -> None:
    """Create all tables if absent (idempotent — no error on existing tables)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Schema initialized")


async def seed_stations(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Insert the 5 seed stations; existing rows are left untouched.

    ``current_status`` starts as ``Offline`` — the real status is filled in by
    retained MQTT status messages once the MQTT adapter connects (architektura 6.3).
    """
    rows = [
        {
            "id": s["id"],
            "connector_type": "AC",
            "max_power_kw": s["max_power_kw"],
            "firmware_version": "1.0.0",
            "monitoring_agent": s["monitoring_agent"],
            "current_status": "Offline",
        }
        for s in SEED_STATIONS
    ]
    stmt = insert(Station).values(rows).on_conflict_do_nothing(index_elements=["id"])
    async with sessionmaker() as session:
        await session.execute(stmt)
        await session.commit()
    logger.info("Seeded %d stations", len(rows))
