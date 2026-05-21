"""Backend configuration loaded from environment variables (architektura 10.1)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class BackendConfig:
    """Immutable backend configuration."""

    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str
    price_per_kwh: Decimal
    backend_port: int
    mqtt_host: str
    mqtt_port: int
    # Heartbeat age after which the offline detector marks a station Offline
    # (architektura 3.5).
    heartbeat_timeout_sec: int
    # Frontend port — used to build the allowed CORS origin (architektura 7).
    frontend_port: int

    @classmethod
    def from_env(cls) -> "BackendConfig":
        """Build a config from the process environment.

        Every value has a sensible default that matches docker-compose.yml, so
        the backend starts without a hand-written ``.env``.
        """
        return cls(
            db_host=os.environ.get("DB_HOST", "db"),
            db_port=int(os.environ.get("DB_PORT", "5432")),
            db_name=os.environ.get("DB_NAME", "cpo"),
            db_user=os.environ.get("DB_USER", "cpo"),
            db_password=os.environ.get("DB_PASSWORD", "cpo"),
            # Decimal (not float) — total_cost rounding must be exact (architektura 5.2).
            price_per_kwh=Decimal(os.environ.get("PRICE_PER_KWH", "5.50")),
            backend_port=int(os.environ.get("BACKEND_PORT", "3000")),
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "1883")),
            heartbeat_timeout_sec=int(os.environ.get("HEARTBEAT_TIMEOUT_SEC", "90")),
            frontend_port=int(os.environ.get("FRONTEND_PORT", "8080")),
        )

    @property
    def database_url(self) -> str:
        """SQLAlchemy async DSN for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def cors_origin(self) -> str:
        """Allowed browser origin for the frontend SPA (architektura 7)."""
        return f"http://localhost:{self.frontend_port}"
