#!/usr/bin/env bash
# Phase 7 verification — Docker Compose finalization (architektura sekce 11
# krok 7). Phase 7 added healthchecks, depends_on startup ordering and a
# persistent Postgres volume to docker-compose.yml. This script exercises the
# REAL docker-compose.yml (the verify override only pins FAULT_PROBABILITY —
# healthchecks/depends_on/volumes live in the base file) and gates three things:
#   1. every healthchecked service (mosquitto, db, backend, frontend) reaches
#      `healthy` — implicitly proving depends_on ordering, since backend and
#      frontend can only go healthy after their service_healthy dependencies;
#   2. the Postgres named volume persists data across `docker compose down`
#      (without -v) + `up` — a real session row written before down survives;
#   3. station-1..5 carry NO healthcheck (simulator has no in-container health
#      signal — see TASK.md: healthchecks welcome, not a hard requirement).

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

command -v curl >/dev/null 2>&1 \
  || die "curl not found on host (needed to drive the REST API)"

dcv down -v --remove-orphans >/dev/null 2>&1 || true

API="http://localhost:3000/api"
HTTP_BODY="$(mktemp)"

# psql runs INSIDE the db container — no host psql client dependency.
psql_q() {
  dcv exec -T db psql -U cpo -d cpo -tAc "$1" 2>/dev/null
}

# health_of <service>: container health status reported by Docker.
health_of() {
  docker inspect --format '{{.State.Health.Status}}' \
    "$(dcv ps -q "$1" 2>/dev/null)" 2>/dev/null
}
svc_healthy() { [ "$(health_of "$1")" = "healthy" ]; }

# --- 1. Build + start the whole stack ----------------------------------------
dcv up -d --build >/dev/null 2>&1 \
  || die "docker compose up -d --build failed for the full stack"

# --- 2. Every healthchecked service reaches `healthy` ------------------------
# backend/frontend can only go healthy after their service_healthy deps came
# up first — so reaching healthy implicitly confirms depends_on ordering.
poll_until 150 "mosquitto healthcheck -> healthy" svc_healthy mosquitto || finish
poll_until 150 "db healthcheck -> healthy"        svc_healthy db        || finish
poll_until 150 "backend healthcheck -> healthy"   svc_healthy backend   || finish
poll_until 150 "frontend healthcheck -> healthy"  svc_healthy frontend  || finish

# --- 3. Stations carry NO healthcheck ----------------------------------------
# A service without a healthcheck reports an empty health status.
station_health="$(health_of station-1 || true)"
assert_eq "" "$station_health" \
  "station-1 has no healthcheck (empty health status)"

# --- 4. Volume persistence: a real session row survives down + up ------------
# ST-001 has FAULT_PROBABILITY pinned to 0.0 by docker-compose.verify.yml, so
# the start is deterministic. POST /start only publishes an MQTT command; the
# session row appears only after the round-trip (command -> station -> Preparing
# 2s -> Charging -> status event -> MQTT adapter -> start_session -> commit).
http_code="$(curl -s -o "$HTTP_BODY" -w '%{http_code}' -X POST \
  -H 'Content-Type: application/json' -d '{}' "$API/stations/ST-001/start")"
assert_eq "202" "$http_code" "POST /api/stations/ST-001/start -> 202"

TX="$(grep -o '"transaction_id":"[^"]*"' "$HTTP_BODY" \
  | head -1 | sed 's/.*:"//;s/"$//')"
[ -n "$TX" ] || die "no transaction_id in the /start 202 response body"

# Gate before `down`: wait until the session row is actually committed.
# Without this gate `down` could race ahead of the commit -> false FAIL.
session_committed() {
  [ "$(psql_q "SELECT count(*) FROM sessions WHERE transaction_id='$TX'")" = "1" ]
}
poll_until 40 "session row committed to DB before down" \
  session_committed || finish

# Restart the stack WITHOUT -v: containers go, the named volume stays.
dcv down --remove-orphans >/dev/null 2>&1 \
  || die "docker compose down (without -v) failed"
dcv up -d >/dev/null 2>&1 \
  || die "docker compose up -d failed after the volume-persistence restart"

poll_until 150 "backend healthy again after restart" svc_healthy backend || finish

# The same row must still be there — it predates the down, so it proves the
# Postgres volume persisted (re-seedable station rows would not prove this).
assert_eq "1" \
  "$(psql_q "SELECT count(*) FROM sessions WHERE transaction_id='$TX'")" \
  "session row survived 'compose down' (Postgres volume persists)"

finish
