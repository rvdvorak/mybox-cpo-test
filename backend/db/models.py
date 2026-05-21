"""SQLAlchemy 2.0 declarative models — mirrors the DDL in architektura 6.1.

Column types, foreign keys and indexes (including the partial active-session
index) reproduce section 6.1 exactly. ``Base.metadata`` drives the idempotent
schema creation in ``db/schema.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all backend tables."""


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    connector_type: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'AC'")
    )
    max_power_kw: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String, nullable=True)
    monitoring_agent: Mapped[str | None] = mapped_column(
        String, nullable=True, server_default=text("'none'")
    )
    current_status: Mapped[str] = mapped_column(String, nullable=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    last_meter_wh: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    station_id: Mapped[str] = mapped_column(String, ForeignKey("stations.id"))
    transaction_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    start_time: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    end_time: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    start_meter_wh: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_meter_wh: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_kwh: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_sessions_station_start", "station_id", text("start_time DESC")),
        # Partial index — active sessions only (architektura 6.1).
        Index(
            "ix_sessions_station_active",
            "station_id",
            postgresql_where=text("end_time IS NULL"),
        ),
    )


class MeterReading(Base):
    __tablename__ = "meter_readings"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    station_id: Mapped[str] = mapped_column(String, nullable=False)
    ts: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    power_kw: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    energy_wh: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        Index("ix_meter_session_ts", "session_id", "ts"),
        Index("ix_meter_station_ts", "station_id", text("ts DESC")),
    )
