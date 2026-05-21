# Shared helpers for scripts/verify/*.sh phase verification scripts.
#
# This file is SOURCED, not executed. It provides a deterministic PASS/FAIL
# contract (see scripts/verify/README.md):
#   exit 0 = PASS   (every assertion passed)
#   exit 1 = FAIL   (at least one assertion failed)
#   exit 2 = ERROR  (environment/setup problem — docker down, port bound, ...)
# The final stdout line is always "RESULT: PASS|FAIL|ERROR" and must agree with
# the exit code — the e2e-runner subagent checks both.

_VERIFY_FAILURES=0

REPO_ROOT="$(git rev-parse --show-toplevel)"

# All verification runs use a dedicated compose project, isolated from the
# developer's interactive stack, and layer the verify-only override that pins
# probabilistic faults to deterministic values (see docker-compose.verify.yml).
VERIFY_PROJECT="cpo-verify"
VERIFY_OVERRIDE="$REPO_ROOT/scripts/verify/docker-compose.verify.yml"

# dcv: docker compose scoped to the isolated verification project.
dcv() {
  docker compose -p "$VERIFY_PROJECT" \
    -f "$REPO_ROOT/docker-compose.yml" \
    -f "$VERIFY_OVERRIDE" "$@"
}

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1 (expected ${2:-?}, got ${3:-?})"; _VERIFY_FAILURES=$((_VERIFY_FAILURES + 1)); }

# assert_eq <expected> <actual> <description>
assert_eq() {
  if [ "$1" = "$2" ]; then pass "$3"; else fail "$3" "'$1'" "'$2'"; fi
}

# assert_contains <haystack> <needle> <description>
assert_contains() {
  if printf '%s' "$1" | grep -qF -- "$2"; then
    pass "$3"
  else
    fail "$3" "to contain '$2'" "absent"
  fi
}

# assert_match <haystack> <extended-regex> <description>
assert_match() {
  if printf '%s' "$1" | grep -Eq -- "$2"; then
    pass "$3"
  else
    fail "$3" "to match /$2/" "no match"
  fi
}

# poll_until <timeout_sec> <description> <command...>
# Runs the command repeatedly until it succeeds or the deadline passes.
# Counts as one assertion. Returns non-zero on timeout so callers can short-circuit.
poll_until() {
  local timeout="$1" desc="$2"; shift 2
  local deadline=$((SECONDS + timeout))
  until "$@" >/dev/null 2>&1; do
    if [ "$SECONDS" -ge "$deadline" ]; then
      fail "$desc" "success within ${timeout}s" "timeout"
      return 1
    fi
    sleep 2
  done
  pass "$desc"
  return 0
}

# finish: print the RESULT line and exit with the matching code. Call last.
finish() {
  if [ "$_VERIFY_FAILURES" -eq 0 ]; then
    echo "RESULT: PASS"
    exit 0
  fi
  echo "RESULT: FAIL"
  exit 1
}

# die <msg>: environment/setup error — exit 2, distinct from an assertion failure.
die() {
  echo "ERROR: $1"
  echo "RESULT: ERROR"
  exit 2
}

# compose_down_trap: tear down the verify stack on script exit (PASS/FAIL/ERROR).
compose_down_trap() {
  trap 'dcv down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
}
