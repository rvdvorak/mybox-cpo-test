"""FastAPI application — startup wiring, REST + SSE routes (architektura 5, 7).

The lifespan handler runs idempotent schema init + station seeding (architektura
6.3), exposes the engine, session factory, ``SessionService`` and the SSE
broadcaster on ``app.state``, and runs the MQTT adapter + offline detector as
background tasks (architektura 3.5, 5.1). The REST and SSE routers are mounted
under ``/api``; all errors use the ``{error, code}`` envelope (architektura 7).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .adapters.mqtt_adapter import run_mqtt_adapter, run_offline_detector
from .adapters.rest_api import register_error_handlers, rest_router
from .adapters.sse import SseBroadcaster, sse_router
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

# Loaded at import time so CORSMiddleware (which must be registered before the
# app starts serving) can read the allowed origin. The lifespan reuses it.
config = BackendConfig.from_env()


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
    engine = build_engine(config)
    sessionmaker = build_sessionmaker(engine)

    await _wait_for_db(engine)
    await init_schema(engine)
    await seed_stations(sessionmaker)

    session_service = SessionService(FlatRatePricing(config.price_per_kwh))
    broadcaster = SseBroadcaster()
    app.state.config = config
    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.session_service = session_service
    app.state.broadcaster = broadcaster

    # Background tasks: ingest the MQTT station stream and sweep for stale
    # heartbeats. Both push real-time events into the SSE broadcaster. Started
    # after the schema + seed so station rows already exist.
    tasks = [
        asyncio.create_task(
            run_mqtt_adapter(config, sessionmaker, session_service, broadcaster)
        ),
        asyncio.create_task(run_offline_detector(config, sessionmaker, broadcaster)),
    ]
    logger.info("Backend startup complete")

    yield

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await engine.dispose()


app = FastAPI(title="Mini CPO Backend", lifespan=lifespan)

# CORS: the frontend SPA runs on a different origin (architektura 7). No
# credentials check and no authentication in the MVP.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.cors_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_router, prefix="/api")
app.include_router(sse_router, prefix="/api")
register_error_handlers(app)
