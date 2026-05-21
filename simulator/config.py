"""Station configuration loaded from environment variables (architektura 10)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Station IDs are always ST-XXX (architektura 10.2).
_STATION_ID_RE = re.compile(r"^ST-\d{3}$")


@dataclass(frozen=True)
class StationConfig:
    """Immutable configuration for one simulated station."""

    mqtt_host: str
    mqtt_port: int
    station_id: str
    max_power_kw: float
    fault_probability: float
    fault_recovery_sec: float
    connector_type: str
    firmware_version: str
    monitoring_agent: str

    @classmethod
    def from_env(cls) -> "StationConfig":
        """Build a config from the process environment.

        ``STATION_ID`` and ``MAX_POWER_KW`` are required — a station without
        them is meaningless, so we fail fast with a clear error.
        """
        station_id = os.environ.get("STATION_ID")
        if not station_id:
            raise ValueError("STATION_ID is required")
        if not _STATION_ID_RE.match(station_id):
            raise ValueError(f"STATION_ID must match ST-XXX, got {station_id!r}")

        max_power_raw = os.environ.get("MAX_POWER_KW")
        if not max_power_raw:
            raise ValueError("MAX_POWER_KW is required")

        return cls(
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            station_id=station_id,
            max_power_kw=float(max_power_raw),
            fault_probability=float(os.environ.get("FAULT_PROBABILITY", "0.02")),
            fault_recovery_sec=float(os.environ.get("FAULT_RECOVERY_SEC", "30")),
            connector_type=os.environ.get("CONNECTOR_TYPE", "AC"),
            firmware_version=os.environ.get("FIRMWARE_VERSION", "1.0.0"),
            monitoring_agent=os.environ.get("MONITORING_AGENT", "none"),
        )
