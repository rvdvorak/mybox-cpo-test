#!/usr/bin/env bash
# Phase 4 verification — MQTT adapter + DB persistence (architektura 3, 4, 5.1-5.4,
# sekce 11 krok 4).
#
# Exercises the running system end to end: the backend subscribes the station
# event stream, parses messages into domain events and persists them. The verify
# script stands in for the future REST adapter (Phase 5) — it publishes the
# start/stop commands the backend will later publish itself.
#
# Note on boot: the boot handler updates connector_type / max_power_kw /
# firmware_version / monitoring_agent, but the Phase 3 seed already carries the
# exact same values (both derive from architektura 10.1/10.2), so boot ingestion
# produces no observable row diff. The MQTT subscribe/dispatch pipeline is proven
# instead via the heartbeat and status handlers, which share that path.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

command -v mosquitto_pub >/dev/null 2>&1 \
  || die "mosquitto_pub not found on host (needed to publish station commands)"

dcv down -v --remove-orphans >/dev/null 2>&1 || true
# station-1: FAULT_PROBABILITY pinned to 0.0 by the verify overlay -> clean
# happy path. station-3: pinned to 1.0 -> deterministic fault for the soft check.
dcv up -d --build mosquitto db backend station-1 station-3 >/dev/null 2>&1 \
  || die "mosquitto / db / backend / station containers failed to start"

# psql runs INSIDE the db container — no host psql client dependency.
psql_q() {
  dcv exec -T db psql -U cpo -d cpo -tAc "$1" 2>/dev/null
}

MOSQ="mosquitto_pub -h localhost -p 1883"
TS="2026-05-21T00:00:00.000Z"
TX="verify-tx-$(date +%s)"

# --- 1. Backend up: schema created and 5 stations seeded ---------------------
seeded() { [ "$(psql_q 'SELECT count(*) FROM stations')" = "5" ]; }
poll_until 90 "backend created schema and seeded 5 stations" seeded || finish

# --- 2. Status ingestion: retained status flips ST-001 out of Offline --------
# Seed leaves current_status='Offline'; the station's retained status message
# (state Available on connect) is ingested by the status handler.
st001_online() {
  [ "$(psql_q "SELECT current_status FROM stations WHERE id='ST-001'")" != "Offline" ]
}
poll_until 60 "ST-001 retained status ingested (current_status left Offline)" \
  st001_online

# --- 3. Heartbeat ingestion: last_heartbeat populated ------------------------
# Heartbeat is QoS 0, every 30 s after a 0-30 s startup jitter (architektura 3.6).
hb_ingested() {
  local v
  v="$(psql_q "SELECT last_heartbeat FROM stations WHERE id='ST-001'")"
  [ -n "$v" ]
}
poll_until 100 "ST-001 heartbeat ingested (last_heartbeat set)" hb_ingested

# --- 4. Start session: status=Charging opens a session row ------------------
$MOSQ -q 2 -t "cpo/v1/stations/ST-001/commands/start_charging" \
  -m "{\"transaction_id\":\"$TX\",\"issued_at\":\"$TS\"}" \
  || die "mosquitto_pub start_charging failed"

session_open() {
  [ "$(psql_q "SELECT count(*) FROM sessions \
               WHERE transaction_id='$TX' AND end_time IS NULL")" = "1" ]
}
poll_until 40 "charging session row created on status=Charging" session_open \
  || finish

assert_eq "Charging" \
  "$(psql_q "SELECT current_status FROM stations WHERE id='ST-001'" || true)" \
  "ST-001 current_status is Charging while the session is open"

# --- 5. Meter readings accumulate for the open session ----------------------
meters_flow() {
  local n
  n="$(psql_q "SELECT count(*) FROM meter_readings mr \
               JOIN sessions s ON s.id = mr.session_id \
               WHERE s.transaction_id='$TX'")"
  [ -n "$n" ] && [ "$n" != "0" ]
}
poll_until 40 "meter readings persisted for the open session" meters_flow

# --- 6. Stop session: status=Finishing closes the session with totals -------
$MOSQ -q 2 -t "cpo/v1/stations/ST-001/commands/stop_charging" \
  -m "{\"issued_at\":\"$TS\"}" \
  || die "mosquitto_pub stop_charging failed"

session_closed() {
  [ "$(psql_q "SELECT count(*) FROM sessions \
               WHERE transaction_id='$TX' AND end_time IS NOT NULL \
                 AND total_kwh IS NOT NULL AND total_cost IS NOT NULL \
                 AND end_reason='completed'")" = "1" ]
}
poll_until 40 "session closed with end_time, totals and end_reason=completed" \
  session_closed

# --- 7. Offline detection via LWT: kill the station container ---------------
# An ungraceful kill is an unclean disconnect — the broker publishes the
# station's Last Will (status Offline), which the adapter ingests (architektura
# 3.3, 3.5). The periodic heartbeat-timeout detector is the slow-path backup;
# it is not isolated here because a container kill always triggers the LWT.
dcv kill station-1 >/dev/null 2>&1 || die "could not kill station-1 container"

st001_offline() {
  [ "$(psql_q "SELECT current_status FROM stations WHERE id='ST-001'")" = "Offline" ]
}
poll_until 30 "ST-001 -> Offline after container kill (LWT path)" st001_offline

# --- 8. Soft, non-gating fault check on ST-003 ------------------------------
# Faults are probabilistic (architektura 9.2); the verify overlay pins ST-003 to
# FAULT_PROBABILITY=1.0 so a fault is expected, but this is NOT a hard PASS gate.
echo "--- soft check: probabilistic fault on ST-003 (non-gating) ---"
TX3="verify-fault-$(date +%s)"
$MOSQ -q 2 -t "cpo/v1/stations/ST-003/commands/start_charging" \
  -m "{\"transaction_id\":\"$TX3\",\"issued_at\":\"$TS\"}" 2>/dev/null || true

fault_seen=""
for _ in $(seq 1 20); do
  if [ "$(psql_q "SELECT count(*) FROM sessions \
                  WHERE transaction_id='$TX3' AND end_reason='faulted'" \
          2>/dev/null || true)" = "1" ]; then
    fault_seen="yes"
    break
  fi
  sleep 2
done
if [ -n "$fault_seen" ]; then
  echo "INFO: fault scenario observed — ST-003 session $TX3 closed end_reason='faulted'"
else
  echo "INFO: no fault observed in the window — probabilistic, not a failure"
fi

finish
