#!/usr/bin/env bash
# Phase 3 verification — backend domain layer + DB schema (architektura 5, 6,
# sekce 11 krok 3).
#
# The domain layer is pure logic with no running system to exercise, so this
# script verifies the DB layer and startup wiring instead: the backend lifespan
# must create the schema (architektura 6.1) and seed 5 stations (6.3). The
# backend has NO HTTP routes in Phase 3, so startup is detected by polling the
# database until the seed rows appear — not via a /health endpoint.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

dcv down -v --remove-orphans >/dev/null 2>&1 || true
dcv up -d --build db backend >/dev/null 2>&1 \
  || die "db / backend containers failed to start"

# psql runs INSIDE the db container — no host psql client dependency.
psql_q() {
  dcv exec -T db psql -U cpo -d cpo -tAc "$1" 2>/dev/null
}

# Startup is complete once the backend lifespan has created the schema and
# seeded the 5 stations. Errors before the table exists are swallowed -> retry.
seeded() { [ "$(psql_q 'SELECT count(*) FROM stations')" = "5" ]; }
poll_until 60 "backend created schema and seeded 5 stations" seeded || finish

# 1. Tables exist (architektura 6.1).
assert_eq "stations" "$(psql_q "SELECT to_regclass('public.stations')" || true)" \
  "table stations exists"
assert_eq "sessions" "$(psql_q "SELECT to_regclass('public.sessions')" || true)" \
  "table sessions exists"
assert_eq "meter_readings" \
  "$(psql_q "SELECT to_regclass('public.meter_readings')" || true)" \
  "table meter_readings exists"

# 2. Key columns per architektura 6.1.
cols() {
  psql_q "SELECT string_agg(column_name, ',') FROM information_schema.columns \
          WHERE table_name='$1'"
}
stations_cols="$(cols stations || true)"
assert_contains "$stations_cols" "current_status" "stations has current_status"
assert_contains "$stations_cols" "max_power_kw"   "stations has max_power_kw"
assert_contains "$stations_cols" "last_heartbeat" "stations has last_heartbeat"
assert_contains "$stations_cols" "last_meter_wh"  "stations has last_meter_wh"

sessions_cols="$(cols sessions || true)"
assert_contains "$sessions_cols" "transaction_id" "sessions has transaction_id"
assert_contains "$sessions_cols" "start_time"     "sessions has start_time"
assert_contains "$sessions_cols" "end_time"       "sessions has end_time"
assert_contains "$sessions_cols" "start_meter_wh" "sessions has start_meter_wh"
assert_contains "$sessions_cols" "total_kwh"      "sessions has total_kwh"
assert_contains "$sessions_cols" "total_cost"     "sessions has total_cost"
assert_contains "$sessions_cols" "end_reason"     "sessions has end_reason"

meter_cols="$(cols meter_readings || true)"
assert_contains "$meter_cols" "session_id" "meter_readings has session_id"
assert_contains "$meter_cols" "station_id" "meter_readings has station_id"
assert_contains "$meter_cols" "power_kw"   "meter_readings has power_kw"
assert_contains "$meter_cols" "energy_wh"  "meter_readings has energy_wh"

# 3. Seed — 5 stations ST-001..ST-005, all Offline (architektura 6.3, 10.2).
assert_eq "ST-001,ST-002,ST-003,ST-004,ST-005" \
  "$(psql_q "SELECT string_agg(id, ',' ORDER BY id) FROM stations" || true)" \
  "stations seeded with ST-001..ST-005"
assert_eq "5" \
  "$(psql_q "SELECT count(*) FROM stations WHERE current_status='Offline'" || true)" \
  "all 5 seeded stations have current_status='Offline'"

# 4. Partial index on sessions WHERE end_time IS NULL (architektura 6.1).
sessions_idx="$(psql_q "SELECT string_agg(indexdef, ' || ') FROM pg_indexes \
                        WHERE tablename='sessions'" || true)"
assert_contains "$sessions_idx" "end_time IS NULL" \
  "sessions has partial index WHERE end_time IS NULL"
assert_match "$sessions_idx" "station_id, start_time" \
  "sessions has (station_id, start_time DESC) index"

# 5. meter_readings indexes (architektura 6.1).
meter_idx="$(psql_q "SELECT string_agg(indexdef, ' || ') FROM pg_indexes \
                     WHERE tablename='meter_readings'" || true)"
assert_match "$meter_idx" "session_id, ts"      "meter_readings has (session_id, ts) index"
assert_match "$meter_idx" "station_id, ts DESC" "meter_readings has (station_id, ts DESC) index"

finish
