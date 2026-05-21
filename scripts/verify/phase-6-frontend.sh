#!/usr/bin/env bash
# Phase 6 verification — Frontend SPA (architektura sekce 8, sekce 11 krok 6).
#
# The frontend is a browser SPA; without a headless browser only container-level
# health can be checked deterministically. Real UI behaviour (live SSE updates,
# clicking) is covered by the README manual scenarios (Phase 8) and the
# end-to-end test (Phase 9). This script gates three things:
#   1. the image builds — `npm install` succeeds;
#   2. the Vite dev server answers on :8080 with the SPA HTML shell;
#   3. TypeScript compiles clean (`tsc --noEmit`) — catches broken imports and
#      type errors, the most valuable no-browser gate.
# No backend / db is needed here — frontend<->backend integration is Phase 9.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
# shellcheck source=scripts/verify/_lib.sh
source scripts/verify/_lib.sh
compose_down_trap

command -v curl >/dev/null 2>&1 \
  || die "curl not found on host (needed to probe the dev server)"

dcv down -v --remove-orphans >/dev/null 2>&1 || true

# --- 1. Image builds + container starts --------------------------------------
dcv up -d --build frontend >/dev/null 2>&1 \
  || die "frontend image failed to build or container failed to start"

# --- 2. Vite dev server answers on :8080 with the SPA HTML shell -------------
HTTP_BODY="$(mktemp)"
dev_server_ready() {
  [ "$(curl -s -o "$HTTP_BODY" -w '%{http_code}' http://localhost:8080)" = "200" ]
}
poll_until 90 "Vite dev server -> 200 on :8080" dev_server_ready || finish

html="$(cat "$HTTP_BODY")"
assert_contains "$html" 'id="root"'      "served HTML carries the SPA root div"
assert_contains "$html" 'type="module"'  "served HTML loads an ES module script"
assert_contains "$html" '/src/main.tsx'  "served HTML bootstraps from main.tsx"

# --- 3. TypeScript compiles clean (tsc --noEmit) -----------------------------
# Run inside the verify-project container via `dcv exec` — NOT `docker compose
# exec`, which would target the default project / interactive stack.
if dcv exec -T frontend npm run typecheck >/tmp/phase6-tsc.log 2>&1; then
  pass "tsc --noEmit: TypeScript compiles with no type errors"
else
  fail "tsc --noEmit: TypeScript compiles with no type errors" "clean" "errors"
  echo "--- tsc output ---"
  cat /tmp/phase6-tsc.log
fi

finish
