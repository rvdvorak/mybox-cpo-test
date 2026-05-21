"""Domain events — protocol-agnostic representations of station messages.

These map the MQTT upstream payloads from architektura 4.2 one-to-one, but carry
no MQTT awareness themselves. The MQTT adapter (Phase 4) parses raw messages into
these models; ``SessionService`` consumes them. A future OCPP adapter would build
the same events from a different wire format (architektura 5.1).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _Event(BaseModel):
    """Base for domain events — ignores unknown fields for forward compatibility."""

    model_config = ConfigDict(extra="ignore")


class BootEvent(_Event):
    """Station boot announcement (retained, published on each connect)."""

    station_id: str
    boot_time: datetime
    firmware_version: str
    connector_type: str
    max_power_kw: float
    monitoring_agent: str


class HeartbeatEvent(_Event):
    """Periodic liveness signal (every 30 s + jitter)."""

    station_id: str
    ts: datetime


class StatusChangedEvent(_Event):
    """Station status transition.

    ``transaction_id`` is absent for non-charging statuses (Available, Offline);
    ``error_code`` is present only for ``Faulted``.
    """

    station_id: str
    ts: datetime
    status: str
    transaction_id: str | None = None
    error_code: str | None = None


class MeterReadingEvent(_Event):
    """Energy meter sample emitted every 5 s during Charging.

    ``energy_wh`` is the station's cumulative meter counter (architektura 9.3).
    """

    station_id: str
    ts: datetime
    transaction_id: str
    power_kw: float
    energy_wh: int
