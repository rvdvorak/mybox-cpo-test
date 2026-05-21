"""Async I/O layer: wires the state machine to an MQTT client and a tick loop.

This module owns the clock, the aiomqtt connection and the concurrency. The
pure logic lives in :mod:`simulator.state_machine`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from aiomqtt import Client, MqttError, Will

from .config import StationConfig
from .state_machine import (
    EFFECT_LOG_WARNING,
    EFFECT_METER,
    EFFECT_STATUS,
    State,
    StationStateMachine,
)

HEARTBEAT_INTERVAL_SEC = 30.0
TICK_INTERVAL_SEC = 1.0
RECONNECT_DELAY_SEC = 5.0
# Jitter window spreads heartbeats when 5 stations start together (architektura 3.6).
HEARTBEAT_JITTER_SEC = 30.0

log = logging.getLogger("simulator")


def _now_iso() -> str:
    """Current UTC time as ISO 8601 with millisecond precision and a Z suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class Topics:
    """Resolved MQTT topics for one station (architektura 3.1)."""

    boot: str
    heartbeat: str
    status: str
    meter: str
    cmd_wildcard: str

    @classmethod
    def for_station(cls, station_id: str) -> "Topics":
        base = f"cpo/v1/stations/{station_id}"
        return cls(
            boot=f"{base}/events/boot",
            heartbeat=f"{base}/events/heartbeat",
            status=f"{base}/events/status",
            meter=f"{base}/events/meter",
            cmd_wildcard=f"{base}/commands/+",
        )


class StationInstance:
    """A running station simulator: MQTT connection + state machine + loops."""

    def __init__(self, config: StationConfig) -> None:
        self.config = config
        self._topics = Topics.for_station(config.station_id)
        self._sm = StationStateMachine(
            max_power_kw=config.max_power_kw,
            fault_probability=config.fault_probability,
            fault_recovery_sec=config.fault_recovery_sec,
        )
        self._heartbeat_offset = random.uniform(0.0, HEARTBEAT_JITTER_SEC)
        self._stop = asyncio.Event()
        self._log = logging.getLogger(f"simulator.{config.station_id}")

    def request_stop(self) -> None:
        """Signal a graceful shutdown — wired to SIGTERM/SIGINT."""
        self._stop.set()

    # --- Connection lifecycle ------------------------------------------------

    async def run(self) -> None:
        """Connect and serve, reconnecting with a fixed backoff on MQTT errors."""
        while not self._stop.is_set():
            try:
                async with Client(
                    hostname=self.config.mqtt_host,
                    port=self.config.mqtt_port,
                    identifier=self.config.station_id,
                    clean_session=False,
                    will=self._build_will(),
                ) as client:
                    await self._session(client)
            except MqttError as exc:
                if self._stop.is_set():
                    break
                self._log.warning(
                    "MQTT error: %s — reconnecting in %ss", exc, RECONNECT_DELAY_SEC
                )
                await self._sleep_or_stop(RECONNECT_DELAY_SEC)
        self._log.info("simulator stopped")

    def _build_will(self) -> Will:
        """Last Will: broker publishes Offline on an unclean disconnect."""
        payload = json.dumps(
            {
                "station_id": self.config.station_id,
                "status": State.OFFLINE.value,
                "reason": "unclean_disconnect",
            }
        )
        return Will(topic=self._topics.status, payload=payload, qos=1, retain=True)

    async def _session(self, client: Client) -> None:
        """Drive one connected session until shutdown or connection loss."""
        await client.subscribe(self._topics.cmd_wildcard, qos=2)
        await self._publish_boot(client)
        await self._publish_status(client)
        self._log.info("connected as %s", self.config.station_id)

        workers = [
            asyncio.create_task(self._command_loop(client)),
            asyncio.create_task(self._tick_loop(client)),
            asyncio.create_task(self._heartbeat_loop(client)),
        ]
        stop_waiter = asyncio.create_task(self._stop.wait())

        done, pending = await asyncio.wait(
            [*workers, stop_waiter], return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

        # The worker loops never return on their own — if one is done, it raised
        # (typically an MqttError on connection loss). Surface it to reconnect.
        for task in workers:
            if task in done and task.exception() is not None:
                raise task.exception()

        # Clean stop: announce Offline while the connection is still live, then
        # let the context manager close it cleanly so the LWT does not fire.
        if self._stop.is_set():
            try:
                await self._publish_offline(client)
            except MqttError:
                self._log.warning("could not publish Offline status on shutdown")

    async def _sleep_or_stop(self, seconds: float) -> None:
        """Sleep, returning early if a shutdown is requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except TimeoutError:
            pass

    # --- Worker loops --------------------------------------------------------

    async def _command_loop(self, client: Client) -> None:
        """Consume downstream commands and feed them to the state machine."""
        async for message in client.messages:
            effects = self._handle_command(message)
            await self._publish_effects(client, effects)

    def _handle_command(self, message) -> list:
        """Parse one command message into state-machine effects.

        Malformed input is silently ignored with a warning — never a crash
        (architektura 9.2 edge cases).
        """
        topic = message.topic.value
        try:
            payload = json.loads(message.payload)
        except (ValueError, TypeError):
            self._log.warning("ignored command with malformed payload on %s", topic)
            return []

        if topic.endswith("/commands/start_charging"):
            tx_id = payload.get("transaction_id")
            if not tx_id:
                self._log.warning("start_charging without transaction_id ignored")
                return []
            return self._sm.handle_start_charging(tx_id)
        if topic.endswith("/commands/stop_charging"):
            return self._sm.handle_stop_charging()

        self._log.warning("ignored unknown command topic %s", topic)
        return []

    async def _tick_loop(self, client: Client) -> None:
        """Advance the state machine once per second using a monotonic delta."""
        last = time.monotonic()
        while not self._stop.is_set():
            await asyncio.sleep(TICK_INTERVAL_SEC)
            now = time.monotonic()
            effects = self._sm.tick(now - last)
            last = now
            await self._publish_effects(client, effects)

    async def _heartbeat_loop(self, client: Client) -> None:
        """Publish a heartbeat every 30 s, after an initial jitter offset."""
        await asyncio.sleep(self._heartbeat_offset)
        while not self._stop.is_set():
            await self._publish_heartbeat(client)
            await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)

    # --- Publishing ----------------------------------------------------------

    async def _publish_effects(self, client: Client, effects: list) -> None:
        for effect in effects:
            if effect.kind == EFFECT_STATUS:
                await self._publish_status(client)
            elif effect.kind == EFFECT_METER:
                await self._publish_meter(client, effect)
            elif effect.kind == EFFECT_LOG_WARNING:
                self._log.warning(effect.message)

    async def _publish_boot(self, client: Client) -> None:
        """Boot — retained, QoS 1, on every connect (architektura 3.3, 4.2)."""
        payload = {
            "station_id": self.config.station_id,
            "boot_time": _now_iso(),
            "firmware_version": self.config.firmware_version,
            "connector_type": self.config.connector_type,
            "max_power_kw": self.config.max_power_kw,
            "monitoring_agent": self.config.monitoring_agent,
        }
        await client.publish(self._topics.boot, json.dumps(payload), qos=1, retain=True)

    async def _publish_status(self, client: Client) -> None:
        """Status — retained, QoS 1. Reflects the current state machine state."""
        payload = {
            "station_id": self.config.station_id,
            "ts": _now_iso(),
            "status": self._sm.state.value,
            "transaction_id": self._sm.transaction_id,
        }
        if self._sm.state is State.FAULTED and self._sm.error_code is not None:
            payload["error_code"] = self._sm.error_code
        await client.publish(
            self._topics.status, json.dumps(payload), qos=1, retain=True
        )

    async def _publish_meter(self, client: Client, effect) -> None:
        """Meter — not retained, QoS 1, every 5 s while Charging (architektura 4.2)."""
        payload = {
            "station_id": self.config.station_id,
            "ts": _now_iso(),
            "transaction_id": self._sm.transaction_id,
            "power_kw": round(effect.power_kw, 2),
            "energy_wh": round(effect.energy_wh),
        }
        await client.publish(
            self._topics.meter, json.dumps(payload), qos=1, retain=False
        )

    async def _publish_heartbeat(self, client: Client) -> None:
        """Heartbeat — not retained, QoS 0 (architektura 3.2, 3.3)."""
        payload = {
            "station_id": self.config.station_id,
            "ts": _now_iso(),
        }
        await client.publish(
            self._topics.heartbeat, json.dumps(payload), qos=0, retain=False
        )

    async def _publish_offline(self, client: Client) -> None:
        """Graceful Offline status — retained, QoS 1 (architektura 9.4)."""
        payload = {
            "station_id": self.config.station_id,
            "ts": _now_iso(),
            "status": State.OFFLINE.value,
            "reason": "clean_shutdown",
        }
        await client.publish(
            self._topics.status, json.dumps(payload), qos=1, retain=True
        )
