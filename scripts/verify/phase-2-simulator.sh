#!/usr/bin/env bash
# Phase 2 verification — station simulator (architektura 4.2, 9, sekce 11 krok 2).
#
# Baseline check: a station boots, publishes retained boot + status, and emits
# heartbeats. Phases 1 and 2 are already done — this script doubles as the
# known-good baseline that validates the verification infrastructure itself.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

dcv down -v --remove-orphans >/dev/null 2>&1 || true
dcv up -d --build mosquitto station-1 station-3 >/dev/null 2>&1 \
  || die "mosquitto / station containers failed to start"

poll_until 30 "broker reachable" \
  mosquitto_pub -h localhost -p 1883 -t 'cpo/verify/ping' -m up || finish

# Retained boot + status are delivered immediately to a fresh subscriber
# (architektura 3.3). Collect every retained event topic for ~8 s.
retained="$(mosquitto_sub -h localhost -p 1883 -t 'cpo/v1/stations/+/events/+' \
            -W 8 -v 2>/dev/null || true)"
assert_contains "$retained" "cpo/v1/stations/ST-001/events/boot"   "ST-001 boot is retained"
assert_contains "$retained" "cpo/v1/stations/ST-001/events/status" "ST-001 status is retained"
assert_contains "$retained" "max_power_kw"     "boot payload carries max_power_kw"
assert_contains "$retained" "firmware_version" "boot payload carries firmware_version"
assert_match    "$retained" 'cpo/v1/stations/ST-[0-9]{3}/events/' "station IDs match ST-XXX"

# Heartbeats are QoS 0, not retained, first emitted within the jitter window
# (0-30 s) then every 30 s (architektura 3.6, 4.2). A 40 s window catches one.
heartbeats="$(mosquitto_sub -h localhost -p 1883 \
              -t 'cpo/v1/stations/+/events/heartbeat' -W 40 -v 2>/dev/null || true)"
assert_contains "$heartbeats" "events/heartbeat" "at least one heartbeat within 40 s"

finish
