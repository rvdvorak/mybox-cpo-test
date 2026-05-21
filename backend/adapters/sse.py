"""Server-Sent Events adapter — real-time push to the frontend (architektura 7.6).

A second protocol adapter alongside ``rest_api.py``: the MQTT adapter ingests
station messages and, after each commit, pushes domain events into the in-process
``SseBroadcaster``; this module fans them out to every connected browser over a
single long-lived ``GET /api/stream/events`` stream.

The broadcaster is process-local — fine for a single-process MVP backend. A
multi-worker deployment would need a shared bus (Redis pub/sub), noted as a
scaling tradeoff for DESIGN.md.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Idle gap after which the stream emits a comment line, so an intermediary proxy
# does not drop a quiet connection (architektura 7.6).
_KEEPALIVE_SEC = 15.0


class SseBroadcaster:
    """In-process fan-out of SSE events to all connected stream clients.

    Each subscriber owns an ``asyncio.Queue``; ``publish`` enqueues a fully
    formatted SSE frame for every client. Queues are unbounded — acceptable for
    the MVP scale (5 stations); a slow client is cleaned up on disconnect.
    """

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        """Register a new client and return its event queue."""
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        """Drop a client's queue — called when its stream disconnects."""
        self._clients.discard(queue)

    def publish(self, event_type: str, data: dict) -> None:
        """Fan one event out to every connected client as an SSE frame."""
        frame = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for queue in self._clients:
            queue.put_nowait(frame)


sse_router = APIRouter()


@sse_router.get("/stream/events")
async def stream_events(request: Request) -> StreamingResponse:
    """Stream domain events to one browser via Server-Sent Events.

    The generator blocks on the client's queue and yields each SSE frame as it
    arrives; on an idle gap it emits a keepalive comment. The ``finally`` block
    unsubscribes when the client disconnects (the generator is closed).
    """
    broadcaster: SseBroadcaster = request.app.state.broadcaster
    queue = broadcaster.subscribe()

    async def event_stream():
        yield ": connected\n\n"
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SEC)
                    yield frame
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
