#!/usr/bin/env bash
# Phase 5 verification — REST API + SSE (architektura 7, sekce 11 krok 5).
#
# Exercises the full loop the way the frontend will: a real `curl` against the
# backend REST API drives a station through a charging session. This replaces
# the raw `mosquitto_pub` of Phase 4 — the backend now publishes the MQTT
# commands itself. Closed loop: REST POST -> MQTT command -> station -> MQTT
# status -> DB -> REST read. A background SSE stream is captured across the
# whole cycle and checked for the four lifecycle event types.
#
# station-1 has FAULT_PROBABILITY pinned to 0.0 by docker-compose.verify.yml,
# so the happy-path session is deterministic — no probabilistic fault.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

command -v curl >/dev/null 2>&1 \
  || die "curl not found on host (needed to drive the REST API)"

dcv down -v --remove-orphans >/dev/null 2>&1 || true
dcv up -d --build mosquitto db backend station-1 >/dev/null 2>&1 \
  || die "mosquitto / db / backend / station-1 containers failed to start"

API="http://localhost:3000/api"
HTTP_BODY="$(mktemp)"
SSE_OUT="$(mktemp)"
SSE_PID=""
cleanup_extra() { [ -n "$SSE_PID" ] && kill "$SSE_PID" 2>/dev/null || true; }
trap 'cleanup_extra; dcv down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

# psql runs INSIDE the db container — no host psql client dependency.
psql_q() {
  dcv exec -T db psql -U cpo -d cpo -tAc "$1" 2>/dev/null
}

# http_code <method> <path> [json-body]
# Echoes the HTTP status code; writes the response body to $HTTP_BODY.
http_code() {
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -s -o "$HTTP_BODY" -w '%{http_code}' -X "$method" \
      -H 'Content-Type: application/json' -d "$body" "$API$path"
  else
    curl -s -o "$HTTP_BODY" -w '%{http_code}' -X "$method" "$API$path"
  fi
}

# --- 1. Backend up: GET /api/stations returns 200 with 5 seeded stations -----
backend_ready() {
  [ "$(http_code GET /stations)" = "200" ] \
    && [ "$(grep -o '"station_id"' "$HTTP_BODY" | wc -l)" = "5" ]
}
poll_until 90 "GET /api/stations -> 200 with 5 stations" backend_ready || finish

# --- 2. Station detail + 404 envelope for an unknown id ----------------------
assert_eq "200" "$(http_code GET /stations/ST-001)" \
  "GET /api/stations/ST-001 -> 200"
assert_contains "$(cat "$HTTP_BODY")" '"station_id":"ST-001"' \
  "ST-001 detail body carries the station_id"

assert_eq "404" "$(http_code GET /stations/UNKNOWN)" \
  "GET /api/stations/UNKNOWN -> 404"
unknown_body="$(cat "$HTTP_BODY")"
assert_contains "$unknown_body" '"error"' "404 body uses the {error,code} envelope (error)"
assert_contains "$unknown_body" '"code"'  "404 body uses the {error,code} envelope (code)"

# --- 3. ST-001 reaches Available (retained status ingested) ------------------
# Seed leaves current_status='Offline'; the station's retained status message
# flips it to Available once the MQTT adapter ingests it.
st001_available() {
  http_code GET /stations/ST-001 >/dev/null
  grep -q '"status":"Available"' "$HTTP_BODY"
}
poll_until 60 "ST-001 reaches Available before the start command" \
  st001_available || finish

# --- 4. Open the SSE stream BEFORE the start/stop cycle ----------------------
curl -sN "$API/stream/events" >"$SSE_OUT" 2>/dev/null &
SSE_PID=$!
sleep 2  # let the stream connect and subscribe before commands flow

# --- 5. POST /start -> 202 -> station charges, session appears ---------------
assert_eq "202" "$(http_code POST /stations/ST-001/start '{}')" \
  "POST /api/stations/ST-001/start -> 202"

charging() {
  http_code GET /stations/ST-001 >/dev/null
  grep -q '"status":"Charging"' "$HTTP_BODY" \
    && grep -q '"active_session":{' "$HTTP_BODY"
}
poll_until 60 "ST-001 -> Charging with an active_session after start" \
  charging || finish

# Wait for the first meter reading before stopping: the simulator emits a meter
# sample every ~5 s (architektura 3.6), and the start/stop cycle would otherwise
# close the session before any meter tick fires — leaving no `meter` SSE frame
# in the capture window. This gate makes the meter assertion deterministic.
meter_recorded() {
  local n
  n="$(psql_q "SELECT count(*) FROM meter_readings mr \
               JOIN sessions s ON s.id = mr.session_id \
               WHERE s.station_id='ST-001'")"
  [ -n "$n" ] && [ "$n" != "0" ]
}
poll_until 40 "a meter reading recorded during charging (before stop)" \
  meter_recorded || finish

http_code GET /stations/ST-001/sessions >/dev/null
assert_contains "$(cat "$HTTP_BODY")" '"sessions":[{' \
  "GET /api/stations/ST-001/sessions lists the open session"

# --- 6. POST /start on a charging station -> 409 STATION_NOT_AVAILABLE -------
assert_eq "409" "$(http_code POST /stations/ST-001/start '{}')" \
  "POST /start on a charging station -> 409"
assert_contains "$(cat "$HTTP_BODY")" 'STATION_NOT_AVAILABLE' \
  "409 body carries code STATION_NOT_AVAILABLE"

# --- 7. POST /stop -> 202 -> session closed with totals ----------------------
assert_eq "202" "$(http_code POST /stations/ST-001/stop '{}')" \
  "POST /api/stations/ST-001/stop -> 202"

session_closed() {
  http_code GET /stations/ST-001/sessions >/dev/null
  grep -q '"end_reason":"completed"' "$HTTP_BODY"
}
poll_until 60 "ST-001 session closed via REST (end_reason=completed)" \
  session_closed || finish

closed_body="$(cat "$HTTP_BODY")"
assert_match "$closed_body" '"total_kwh":[0-9]'  "closed session has a numeric total_kwh"
assert_match "$closed_body" '"total_cost":[0-9]' "closed session has a numeric total_cost"
assert_eq "1" \
  "$(psql_q "SELECT count(*) FROM sessions \
             WHERE station_id='ST-001' AND end_reason='completed'")" \
  "closed session persisted in DB (MQTT status -> DB leg of the loop)"

# --- 8. POST /stop with no active session -> 409 NO_ACTIVE_SESSION -----------
assert_eq "409" "$(http_code POST /stations/ST-001/stop '{}')" \
  "POST /stop with no active session -> 409"
assert_contains "$(cat "$HTTP_BODY")" 'NO_ACTIVE_SESSION' \
  "409 body carries code NO_ACTIVE_SESSION"

# --- 9. SSE: the start/stop cycle produced the lifecycle events --------------
sleep 2  # let trailing frames flush before the stream is cut
kill "$SSE_PID" 2>/dev/null || true
SSE_PID=""
sse="$(cat "$SSE_OUT" 2>/dev/null || true)"
assert_contains "$sse" "event: status_changed"  "SSE emitted status_changed"
assert_contains "$sse" "event: meter"           "SSE emitted meter"
assert_contains "$sse" "event: session_started" "SSE emitted session_started"
assert_contains "$sse" "event: session_ended"   "SSE emitted session_ended"

# heartbeat is a soft, non-gating check: the heartbeat interval (~30 s + jitter,
# architektura 3.6) can exceed the start/stop capture window. The broadcast
# pipeline is already proven by the four events above — heartbeat rides the
# identical path.
echo "--- soft check: SSE heartbeat event (non-gating) ---"
if printf '%s' "$sse" | grep -qF "event: heartbeat"; then
  echo "INFO: SSE heartbeat event observed within the capture window"
else
  echo "INFO: no heartbeat in the window — ~30 s interval, not a failure"
fi

finish
