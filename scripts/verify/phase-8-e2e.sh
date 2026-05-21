#!/usr/bin/env bash
# Phase 8 verification — end-to-end over the REAL docker compose stack
# (architektura sekce 11 krok 8).
#
# Phases 1-7 each ran through `dcv`: an isolated compose project (cpo-verify)
# layering docker-compose.verify.yml, which pins FAULT_PROBABILITY to
# deterministic values (station-1 -> 0.0, station-3 -> 1.0). No phase has yet
# exercised what a MyBox recruiter actually runs first: the REAL `docker
# compose` — real project, real `.env`, real probabilistic faults (station-3 =
# 0.30, others = 0.02).
#
# This script therefore deliberately does NOT use `dcv` or `compose_down_trap`
# from _lib.sh (both target the cpo-verify project). It defines its own `dc()`
# wrapper (default project, reads ./.env) and its own EXIT trap. The assert_*,
# poll_until, pass/fail, die and finish helpers from _lib.sh are used unchanged.
#
# It tears down the default-project stack on entry and exit — if the developer
# has an interactive `docker compose up` running, phase 8 replaces it. That is
# intentional: phase 8 verifies the out-of-the-box stack, not a warm one.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh

command -v curl >/dev/null 2>&1 \
  || die "curl not found on host (needed to drive the REST API and SSE)"
command -v mosquitto_sub >/dev/null 2>&1 \
  || die "mosquitto_sub not found on host (needed to observe MQTT traffic)"

# dc: the REAL docker compose — default project (mybox-cpo-test), reads ./.env.
# NOT dcv: phase 8 verifies the out-of-the-box stack, not the verify overlay.
dc() { docker compose "$@"; }

API="http://localhost:3000/api"
HTTP_BODY="$(mktemp)"
SSE_OUT="$(mktemp)"
MQTT_OUT="$(mktemp)"
SSE_PID=""
cleanup() {
  [ -n "$SSE_PID" ] && kill "$SSE_PID" 2>/dev/null || true
  dc down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

# health_of <service>: container health status reported by Docker.
health_of() {
  docker inspect --format '{{.State.Health.Status}}' \
    "$(dc ps -q "$1" 2>/dev/null)" 2>/dev/null
}
svc_healthy() { [ "$(health_of "$1")" = "healthy" ]; }

# psql runs INSIDE the db container — no host psql client dependency.
psql_q() {
  dc exec -T db psql -U cpo -d cpo -tAc "$1" 2>/dev/null
}

# http_code <method> <path> [json-body]: echoes HTTP status, body -> $HTTP_BODY.
http_code() {
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -s -o "$HTTP_BODY" -w '%{http_code}' -X "$method" \
      -H 'Content-Type: application/json' -d "$body" "$API$path"
  else
    curl -s -o "$HTTP_BODY" -w '%{http_code}' -X "$method" "$API$path"
  fi
}

# station_available <station-id>: true once the station's status is Available.
station_available() {
  http_code GET "/stations/$1" >/dev/null
  grep -qF '"status":"Available"' "$HTTP_BODY"
}

# --- 1. .env setup gate ------------------------------------------------------
# A recruiter's documented first step is `cp .env.example .env`. Verify it: if
# .env is absent, create it from the example (and say so). The .env file is the
# user's to own (CLAUDE.md) — the script only seeds it when missing, never
# deletes or stages it.
if [ -f .env ]; then
  echo "INFO: .env already present — using it as-is"
else
  cp .env.example .env
  echo "INFO: .env created from .env.example (verifies the documented Setup step)"
fi

# --- 2. Build + start the REAL stack -----------------------------------------
dc down -v --remove-orphans >/dev/null 2>&1 || true
dc up -d --build >/tmp/phase8-build.log 2>&1 \
  || die "docker compose up -d --build failed — see /tmp/phase8-build.log"

# --- 3. Out-of-the-box health gate -------------------------------------------
# Every healthchecked service must reach `healthy`. Generous timeout: the
# backend image compiles asyncpg from source (python:3.14, no cp314 wheel) and
# carries a 40 s start_period. A healthy backend/frontend implicitly proves the
# depends_on ordering — they only start once their service_healthy deps are up.
poll_until 240 "mosquitto healthcheck -> healthy" svc_healthy mosquitto || finish
poll_until 240 "db healthcheck -> healthy"        svc_healthy db        || finish
poll_until 240 "backend healthcheck -> healthy"   svc_healthy backend   || finish
poll_until 240 "frontend healthcheck -> healthy"  svc_healthy frontend  || finish

# --- 4. REST: GET /api/stations -> 200 with 5 seeded stations ----------------
assert_eq "200" "$(http_code GET /stations)" "GET /api/stations -> 200"
assert_eq "5" "$(grep -o '"station_id"' "$HTTP_BODY" | wc -l)" \
  "GET /api/stations lists the 5 seeded stations"

# --- 5. REST: station detail + 404 envelope for an unknown id ----------------
assert_eq "200" "$(http_code GET /stations/ST-001)" "GET /api/stations/ST-001 -> 200"
assert_contains "$(cat "$HTTP_BODY")" '"station_id":"ST-001"' \
  "ST-001 detail body carries the station_id"

assert_eq "404" "$(http_code GET /stations/UNKNOWN)" "GET /api/stations/UNKNOWN -> 404"
unknown_body="$(cat "$HTTP_BODY")"
assert_contains "$unknown_body" '"error"' "404 body uses the {error,code} envelope (error)"
assert_contains "$unknown_body" '"code"'  "404 body uses the {error,code} envelope (code)"

# --- 6. REST: sessions list --------------------------------------------------
assert_eq "200" "$(http_code GET /stations/ST-001/sessions)" \
  "GET /api/stations/ST-001/sessions -> 200"
assert_contains "$(cat "$HTTP_BODY")" '"sessions"' \
  "sessions response carries a sessions array"

# --- 7. REST: deterministic 409 (no probabilistic dependency) ----------------
# POST /stop on a station with no active session -> 409 NO_ACTIVE_SESSION.
# Deterministic: independent of the station's status and of any fault roll.
assert_eq "409" "$(http_code POST /stations/ST-005/stop '{}')" \
  "POST /stop on an idle station (ST-005) -> 409"
assert_contains "$(cat "$HTTP_BODY")" 'NO_ACTIVE_SESSION' \
  "409 body carries code NO_ACTIVE_SESSION"

# --- 8. MQTT traffic observable ----------------------------------------------
# Stations publish retained status + periodic heartbeats — traffic is
# guaranteed. Capture ~15 s of the cpo/v1 tree from the host.
mosquitto_sub -h localhost -p 1883 -t 'cpo/v1/#' -W 15 -v >"$MQTT_OUT" 2>/dev/null || true
assert_match "$(cat "$MQTT_OUT")" 'cpo/v1/stations/ST-[0-9]{3}/' \
  "mosquitto_sub observes cpo/v1 station traffic on the broker"

# --- 9. Charging kick-off (early) --------------------------------------------
# Start ST-003 (fault demo, real FAULT_PROBABILITY=0.30 — soft check in step
# 14) and ST-004 (backup meter source, 0.02). Started early so their fault and
# meter windows overlap the rest of the script. Together with ST-001 they make
# the global meter gate in step 11 robust. POST /start needs the station to be
# Available first — the retained status must be ingested by the MQTT adapter.
poll_until 60 "ST-003 reaches Available before start" station_available ST-003 || finish
assert_eq "202" "$(http_code POST /stations/ST-003/start '{}')" \
  "POST /start ST-003 -> 202 (fault-demo station)"
poll_until 60 "ST-004 reaches Available before start" station_available ST-004 || finish
assert_eq "202" "$(http_code POST /stations/ST-004/start '{}')" \
  "POST /start ST-004 -> 202 (backup meter source)"

# --- 10. Open the SSE stream before the ST-001 lifecycle ---------------------
curl -sN "$API/stream/events" >"$SSE_OUT" 2>/dev/null &
SSE_PID=$!
sleep 2  # let the stream connect and subscribe before commands flow

# --- 11. Happy-path lifecycle on ST-001 --------------------------------------
poll_until 60 "ST-001 reaches Available before start" station_available ST-001 || finish

assert_eq "202" "$(http_code POST /stations/ST-001/start '{}')" \
  "POST /api/stations/ST-001/start -> 202"
TX="$(grep -o '"transaction_id":"[^"]*"' "$HTTP_BODY" | head -1 | sed 's/.*:"//;s/"$//')"
[ -n "$TX" ] || die "no transaction_id in the /start 202 response body"

# The session row appears only after the round-trip: command -> station ->
# Preparing 2s -> Charging -> status event -> MQTT adapter -> start_session.
session_exists() {
  [ "$(psql_q "SELECT count(*) FROM sessions WHERE transaction_id='$TX'")" = "1" ]
}
poll_until 60 "ST-001 session row committed to DB" session_exists || finish

# Global meter gate: the simulator rolls the fault BEFORE emitting a meter
# (state_machine.py:188) — a station that faults on its first tick records zero
# readings. Polling the whole meter_readings table across the three charging
# stations (ST-001 0.02, ST-003 0.30, ST-004 0.02) makes this sound: it fails
# only if all three fault on tick 1 (~0.012%), never a real flake.
meter_recorded() {
  local n
  n="$(psql_q "SELECT count(*) FROM meter_readings")"
  [ -n "$n" ] && [ "$n" != "0" ]
}
poll_until 60 "meter readings recorded in DB (simulator -> MQTT -> adapter -> DB)" \
  meter_recorded || finish

# POST /start on a non-available station -> 409. Does not race: ST-001 is
# Charging (or, rarely, Faulted) — both reject /start with STATION_NOT_AVAILABLE.
assert_eq "409" "$(http_code POST /stations/ST-001/start '{}')" \
  "POST /start on a non-available ST-001 -> 409"
assert_contains "$(cat "$HTTP_BODY")" 'STATION_NOT_AVAILABLE' \
  "409 body carries code STATION_NOT_AVAILABLE"

# POST /stop accepts {202, 409 NO_ACTIVE_SESSION}: 202 = normal stop; 409 = a
# real fault (0.02) closed the session itself in the gap between this read and
# the stop. Both are valid outcomes — no flaky assertion on predicted state.
stop_code="$(http_code POST /stations/ST-001/stop '{}')"
if [ "$stop_code" = "202" ]; then
  pass "POST /api/stations/ST-001/stop -> 202 (normal stop)"
elif [ "$stop_code" = "409" ] && grep -qF 'NO_ACTIVE_SESSION' "$HTTP_BODY"; then
  pass "POST /api/stations/ST-001/stop -> 409 NO_ACTIVE_SESSION (fault closed the session first)"
else
  fail "POST /api/stations/ST-001/stop -> 202 or 409 NO_ACTIVE_SESSION" \
    "202 or 409" "$stop_code"
fi

# Hard gate: the session ends up correctly closed regardless of how it ended
# (stop or fault). The invariant is "the session closes cleanly", not a
# predicted station status.
session_closed() {
  local r
  r="$(psql_q "SELECT end_reason FROM sessions WHERE transaction_id='$TX'")"
  [ "$r" = "completed" ] || [ "$r" = "faulted" ]
}
poll_until 60 "ST-001 session closed (end_reason completed|faulted)" \
  session_closed || finish

http_code GET /stations/ST-001/sessions >/dev/null
closed_body="$(cat "$HTTP_BODY")"
assert_match "$closed_body" '"end_reason":"(completed|faulted)"' \
  "closed session reports a terminal end_reason"
assert_match "$closed_body" '"total_kwh":[0-9]'  "closed session has a numeric total_kwh"
assert_match "$closed_body" '"total_cost":[0-9]' "closed session has a numeric total_cost"

# --- 12. Offline detection ---------------------------------------------------
# SIGKILL the station container -> unclean MQTT disconnect -> the broker
# delivers the retained LWT Offline message -> the backend flips the status.
# 45 s window: well under the 90 s heartbeat-timeout fallback, so this gates
# the LWT path specifically (a recent heartbeat keeps the timeout path idle).
dc kill station-2 >/dev/null 2>&1 || die "docker compose kill station-2 failed"
station_offline() {
  http_code GET /stations/ST-002 >/dev/null
  grep -qF '"status":"Offline"' "$HTTP_BODY"
}
poll_until 45 "ST-002 -> Offline after the container is killed (LWT)" \
  station_offline || finish

# --- 13. SSE carried the lifecycle events ------------------------------------
sleep 2  # let trailing frames flush before the stream is cut
kill "$SSE_PID" 2>/dev/null || true
SSE_PID=""
sse="$(cat "$SSE_OUT" 2>/dev/null || true)"
assert_contains "$sse" "event: status_changed"  "SSE emitted status_changed"
assert_contains "$sse" "event: meter"           "SSE emitted meter"
assert_contains "$sse" "event: session_started" "SSE emitted session_started"
assert_contains "$sse" "event: session_ended"   "SSE emitted session_ended"

# heartbeat is a soft, non-gating check: the ~30 s interval can exceed the
# capture window. The broadcast pipeline is already proven by the four events
# above — heartbeat rides the identical path.
echo "--- soft check: SSE heartbeat event (non-gating) ---"
if printf '%s' "$sse" | grep -qF "event: heartbeat"; then
  echo "INFO: SSE heartbeat event observed within the capture window"
else
  echo "INFO: no heartbeat in the window (~30 s interval) — not a failure"
fi

# --- 14. Fault scenario soft-check (station-3, non-gating) -------------------
# ST-003 runs with the real FAULT_PROBABILITY=0.30. A fault is probable but not
# guaranteed within one run — this check is observational and never fails the
# script. A faulted station auto-recovers to Available after FAULT_RECOVERY_SEC,
# so the persisted faulted session in the DB is the durable evidence.
echo "--- soft check: ST-003 fault scenario (non-gating, FAULT_PROBABILITY=0.30) ---"
http_code GET /stations/ST-003 >/dev/null
st003_status="$(grep -o '"status":"[^"]*"' "$HTTP_BODY" | head -1 || true)"
st003_faulted="$(psql_q "SELECT count(*) FROM sessions WHERE station_id='ST-003' AND end_reason='faulted'")" || st003_faulted=""
if printf '%s' "$st003_status" | grep -qF 'Faulted' || [ "${st003_faulted:-0}" != "0" ]; then
  echo "INFO: ST-003 fault observed (current=${st003_status:-?}, faulted sessions=${st003_faulted:-?})"
else
  echo "INFO: no ST-003 fault this run — probabilistic (0.30), not a failure"
fi

# --- 15. Frontend dev server + TypeScript ------------------------------------
assert_eq "200" "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080)" \
  "frontend Vite dev server -> 200 on :8080"

if dc exec -T frontend npm run typecheck >/tmp/phase8-tsc.log 2>&1; then
  pass "tsc --noEmit: frontend TypeScript compiles with no type errors"
else
  fail "tsc --noEmit: frontend TypeScript compiles with no type errors" "clean" "errors"
  echo "--- tsc output ---"
  cat /tmp/phase8-tsc.log
fi

finish
