"""Pure station state machine.

This module is intentionally free of any I/O, async code or MQTT awareness so
it can be reasoned about and exercised in a vacuum. Time is injected as a delta
through ``tick``; the caller owns the clock. Every public method returns a list
of :class:`Effect` objects describing what the I/O layer should publish — the
state machine itself never publishes anything.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

# --- Tunables (architektura 9.2) ---------------------------------------------

PREPARING_DURATION_SEC = 2.0
FINISHING_DURATION_SEC = 2.0
METER_INTERVAL_SEC = 5.0

# Charging power is 92-100 % of MAX_POWER_KW with uniform noise (architektura 9.2).
POWER_NOISE_MIN = 0.92
POWER_NOISE_MAX = 1.00

# Random error code drawn on a probabilistic fault (architektura 9.2).
ERROR_CODES = [
    "InternalError",
    "OverCurrentFailure",
    "HighTemperature",
    "PowerMeterFailure",
]

# --- Effect kinds ------------------------------------------------------------

EFFECT_STATUS = "status"
EFFECT_METER = "meter"
EFFECT_LOG_WARNING = "log_warning"


class State(str, Enum):
    """Station lifecycle states (architektura 9.2).

    Subclassing ``str`` makes ``.value`` directly JSON-serializable.
    """

    AVAILABLE = "Available"
    PREPARING = "Preparing"
    CHARGING = "Charging"
    FINISHING = "Finishing"
    FAULTED = "Faulted"
    OFFLINE = "Offline"


@dataclass(frozen=True)
class Effect:
    """A side effect the I/O layer should carry out.

    ``kind`` discriminates the payload; the remaining fields are populated only
    where relevant for that kind.
    """

    kind: str
    status: State | None = None
    error_code: str | None = None
    power_kw: float | None = None
    energy_wh: float | None = None
    message: str | None = None


class StationStateMachine:
    """In-memory state and transition logic for a single charging station."""

    def __init__(
        self,
        max_power_kw: float,
        fault_probability: float,
        fault_recovery_sec: float = 30.0,
        rng: random.Random | None = None,
    ) -> None:
        self.max_power_kw = max_power_kw
        self.fault_probability = fault_probability
        self.fault_recovery_sec = fault_recovery_sec
        # Injectable RNG keeps the fault roll and power noise deterministic in tests.
        self.rng = rng or random.Random()

        self.state: State = State.AVAILABLE
        self.transaction_id: str | None = None
        self.error_code: str | None = None
        # Cumulative meter, odometer-style. In-memory only — resets on restart
        # (architektura 9.3). Never reset on session boundaries.
        self.energy_wh: float = 0.0

        # Seconds spent in the current state — drives the auto-transition
        # deadlines for Preparing / Finishing / Faulted.
        self.state_elapsed_sec: float = 0.0
        # Seconds accumulated towards the next meter emission while Charging.
        self.meter_elapsed_sec: float = 0.0

    # --- Command handlers ----------------------------------------------------

    def handle_start_charging(self, tx_id: str) -> list[Effect]:
        """Handle a ``start_charging`` command.

        Accepted only in ``Available``; any other state is a silent ignore with
        a warning (architektura 9.2 edge cases).
        """
        if self.state is State.AVAILABLE:
            self.transaction_id = tx_id
            self._transition(State.PREPARING)
            return [Effect(EFFECT_STATUS, status=State.PREPARING)]
        if tx_id == self.transaction_id:
            return [
                Effect(
                    EFFECT_LOG_WARNING,
                    message=f"start_charging ignored: tx {tx_id} already active "
                    f"(state {self.state.value})",
                )
            ]
        return [
            Effect(
                EFFECT_LOG_WARNING,
                message=f"start_charging ignored: station busy "
                f"(state {self.state.value})",
            )
        ]

    def handle_stop_charging(self) -> list[Effect]:
        """Handle a ``stop_charging`` command.

        Accepted only in ``Charging``; any other state is a silent ignore with
        a warning (architektura 9.2 edge cases).
        """
        if self.state is State.CHARGING:
            self._transition(State.FINISHING)
            return [Effect(EFFECT_STATUS, status=State.FINISHING)]
        return [
            Effect(
                EFFECT_LOG_WARNING,
                message=f"stop_charging ignored: no active charge "
                f"(state {self.state.value})",
            )
        ]

    # --- Time-driven engine --------------------------------------------------

    def tick(self, delta_sec: float) -> list[Effect]:
        """Advance the machine by ``delta_sec`` seconds.

        Drives the auto-transitions (Preparing/Finishing/Faulted) and the meter
        emissions while Charging. A single tick may yield zero, one or several
        effects — a slow tick carrying several seconds correctly catches up.
        """
        effects: list[Effect] = []
        self.state_elapsed_sec += delta_sec

        if self.state is State.PREPARING:
            if self.state_elapsed_sec >= PREPARING_DURATION_SEC:
                self._transition(State.CHARGING)
                self.meter_elapsed_sec = 0.0
                effects.append(Effect(EFFECT_STATUS, status=State.CHARGING))
        elif self.state is State.FINISHING:
            if self.state_elapsed_sec >= FINISHING_DURATION_SEC:
                self.transaction_id = None
                self._transition(State.AVAILABLE)
                effects.append(Effect(EFFECT_STATUS, status=State.AVAILABLE))
        elif self.state is State.FAULTED:
            if self.state_elapsed_sec >= self.fault_recovery_sec:
                self.transaction_id = None
                self.error_code = None
                self._transition(State.AVAILABLE)
                effects.append(Effect(EFFECT_STATUS, status=State.AVAILABLE))
        elif self.state is State.CHARGING:
            self.meter_elapsed_sec += delta_sec
            # One iteration == exactly one 5 s meter step; the guard re-checks
            # the state because a fault step transitions out of Charging.
            while (
                self.state is State.CHARGING
                and self.meter_elapsed_sec >= METER_INTERVAL_SEC
            ):
                self.meter_elapsed_sec -= METER_INTERVAL_SEC
                effects.extend(self._meter_step())

        return effects

    def _meter_step(self) -> list[Effect]:
        """Run one 5 s meter step: probabilistic fault roll, else a reading."""
        if self.rng.random() < self.fault_probability:
            self.error_code = self.rng.choice(ERROR_CODES)
            self._transition(State.FAULTED)
            return [
                Effect(EFFECT_STATUS, status=State.FAULTED, error_code=self.error_code)
            ]

        power_kw = self.max_power_kw * self.rng.uniform(POWER_NOISE_MIN, POWER_NOISE_MAX)
        self.energy_wh += power_kw * (METER_INTERVAL_SEC / 3600.0) * 1000.0
        return [Effect(EFFECT_METER, power_kw=power_kw, energy_wh=self.energy_wh)]

    def _transition(self, new_state: State) -> None:
        self.state = new_state
        self.state_elapsed_sec = 0.0
