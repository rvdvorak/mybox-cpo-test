#!/usr/bin/env bash
# PreToolUse hook (matcher: Bash) — defense-in-depth destructive-command guard.
#
# .claude/settings.json `deny` already blocks direct git-mutating / `rm -rf`
# calls. This hook adds one thing deny CANNOT do: when a verification script is
# run as `bash scripts/verify/<x>.sh`, deny only sees the outer `bash` call and
# never inspects the file. A prompt-injected edit to a verify script could hide
# a destructive command there. This hook greps the script's *contents*.
#
# Exit 0 = allow. Exit 2 = block (stderr is shown to Claude).

set -euo pipefail

input="$(cat)"

# Extract the bash command from the tool-input JSON (python3 is always present).
command="$(HOOK_INPUT="$input" python3 -c '
import json, os, sys
try:
    data = json.loads(os.environ.get("HOOK_INPUT", ""))
    sys.stdout.write(data.get("tool_input", {}).get("command", ""))
except Exception:
    pass
' 2>/dev/null || true)"

[ -z "$command" ] && exit 0

# Destructive / git-mutating patterns that must never run — directly or hidden
# inside a verification script. Read-only git (diff/status/log) is NOT matched.
DESTRUCTIVE='(^|[^[:alnum:]_])git[[:space:]]+(reset|rebase|clean|add|commit)([^[:alnum:]_]|$)|git[[:space:]]+checkout[[:space:]]+--[[:space:]]|(^|[^[:alnum:]_])rm[[:space:]]+-[a-zA-Z]*r'

block() {
  echo "guard-destructive: blocked — $1" >&2
  exit 2
}

# 1. Inspect the literal command.
if printf '%s' "$command" | grep -Eq "$DESTRUCTIVE"; then
  block "command contains a destructive or git-mutating operation"
fi

# 2. If the command runs a verification script, inspect that script's contents.
for token in $command; do
  case "$token" in
    scripts/verify/*.sh | */scripts/verify/*.sh)
      if [ -f "$token" ] && grep -Eq "$DESTRUCTIVE" "$token"; then
        block "verification script '$token' contains a destructive or git-mutating operation"
      fi
      ;;
  esac
done

exit 0
