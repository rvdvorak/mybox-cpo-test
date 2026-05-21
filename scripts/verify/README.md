# scripts/verify/ — deterministic phase verification

Operational verification scripts that exercise the **running** system (docker
compose, MQTT, REST, DB) and assert PASS/FAIL between implementation phases.

These are **not** an automated test suite (no `tests/`, no pytest, no test
framework) — see CLAUDE.md § "Verifikace mezi fázemi". They are verification
gates run before a manual commit, and they seed the README "How to test"
section in Phase 8.

## How verification runs

At the end of each phase the `e2e-runner` subagent runs the matching script and
returns a structured verdict. To re-run manually after a fix: `/verify-phase N`.

## When scripts are written

A `phase-N-*.sh` script is authored as the **last task of phase N**, after the
implementation is done — never up front, never as a stub. During implementation
an approved deviation from `docs/architektura.md` may occur; a script written
afterward asserts the behaviour as actually built.

## Contract every script obeys

- Exit code: `0` = PASS, `1` = FAIL (an assertion failed), `2` = ERROR
  (environment/setup problem — not a code failure).
- Final stdout line: `RESULT: PASS|FAIL|ERROR`, always agreeing with the exit code.
- Each assertion prints `PASS: <desc>` or `FAIL: <desc> (expected X, got Y)`.
- Bounded timeouts only — no unbounded `sleep`, no hangs.
- Cleanup on exit (`docker compose down`) via `compose_down_trap`.

## Isolation

Every run uses the dedicated compose project `cpo-verify`, layering
`docker-compose.verify.yml` (which pins probabilistic faults to deterministic
values). It never touches the developer's interactive stack.

**Before verifying, stop any interactive stack** — both bind host ports
1883 / 3000 / 8080 and would collide.

## Files

- `_lib.sh` — shared assertions, `poll_until`, `dcv` compose wrapper, cleanup trap.
- `docker-compose.verify.yml` — verify-only override: station-1 `FAULT_PROBABILITY=0.0`,
  station-3 `FAULT_PROBABILITY=1.0` (deterministic fault / no-fault branches).
- `phase-1-broker.sh`, `phase-2-simulator.sh` — baseline checks (phases done).
- `phase-3-*.sh` … `phase-9-*.sh` — added at the end of their respective phases.
