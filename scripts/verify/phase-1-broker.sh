#!/usr/bin/env bash
# Phase 1 verification — Mosquitto broker (architektura 3.7, sekce 11 krok 1).
#
# Baseline check: the broker container starts and performs a pub/sub round-trip.
# Phases 1 and 2 are already done — this script is also a known-good baseline
# used to validate the verification infrastructure itself.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

dcv down -v --remove-orphans >/dev/null 2>&1 || true
dcv up -d mosquitto >/dev/null 2>&1 || die "mosquitto failed to start"

# Broker accepts connections on :1883.
poll_until 30 "broker accepts connections on :1883" \
  mosquitto_pub -h localhost -p 1883 -t 'cpo/verify/ping' -m up || finish

# Pub/sub round-trip: subscribe (1 message, 10 s timeout), publish, expect payload.
tmp="$(mktemp)"
mosquitto_sub -h localhost -p 1883 -t 'cpo/verify/roundtrip' -C 1 -W 10 >"$tmp" 2>/dev/null &
sub_pid=$!
sleep 1
mosquitto_pub -h localhost -p 1883 -t 'cpo/verify/roundtrip' -m 'hello-cpo'
wait "$sub_pid" 2>/dev/null || true
got="$(cat "$tmp")"
rm -f "$tmp"
assert_eq "hello-cpo" "$got" "pub/sub round-trip delivers the payload"

finish
