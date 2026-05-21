"""FastAPI application — Phase 3 carries only startup wiring, no routes.

The lifespan handler runs idempotent schema init + station seeding (architektura
6.3) and exposes the engine, session factory and ``SessionService`` on
``app.state`` for the adapters added in Phases 4 and 5.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from .config import BackendConfig
from .db.engine import build_engine, build_sessionmaker
from .db.schema import init_schema, seed_stations
from .domain.pricing import FlatRatePricing
from .domain.session_service import SessionService

logger = logging.getLogger(__name__)

# docker-compose has no depends_on/healthcheck yet (Phase 7), so the backend may
# start before Postgres accepts connections. Retry the first contact briefly.
_DB_CONNECT_ATTEMPTS = 10
_DB_CONNECT_DELAY_SEC = 2.0


async def _wait_for_db(engine) -> None:
    """Block until the database accepts a connection, or fail after N tries."""
    for attempt in range(1, _DB_CONNECT_ATTEMPTS + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 — any connect error is retryable here
            if attempt == _DB_CONNECT_ATTEMPTS:
                raise
            logger.warning(
                "Database not ready (attempt %d/%d): %s",
                attempt,
                _DB_CONNECT_ATTEMPTS,
                exc,
            )
            await asyncio.sleep(_DB_CONNECT_DELAY_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = BackendConfig.from_env()
    engine = build_engine(config)
    sessionmaker = build_sessionmaker(engine)

    await _wait_for_db(engine)
    await init_schema(engine)
    await seed_stations(sessionmaker)

    app.state.config = config
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.session_service = SessionService(FlatRatePricing(config.price_per_kwh))
    logger.info("Backend startup complete")

    yield

    await engine.dispose()


app = FastAPI(title="Mini CPO Backend", lifespan=lifespan)
