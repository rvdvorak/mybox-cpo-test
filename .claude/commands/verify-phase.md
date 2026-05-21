---
description: Manually re-run deterministic phase verification via the e2e-runner subagent.
argument-hint: <phase-number 3-9>
---

Manually verify implementation phase **$1** of the Mini CPO Platform.

The primary path is automatic — the `e2e-runner` subagent runs as the last step
of every phase (CLAUDE.md § "Verifikace mezi fázemi"). Use this command to
**re-run** verification after fixing a `FAIL` or addressing a `DEVIATION`.

Steps:

1. Dispatch the `e2e-runner` subagent (the Task tool, `subagent_type: e2e-runner`).
   Do **not** run verification commands inline — delegation keeps this context clean.
2. Pass it: phase number **$1**, and the approved pre-implementation plan for
   phase $1 (the plan file in `~/.claude/plans/`, or its content if you still
   have it in context). Instruct it to do Stage 1 (conformance vs the plan) and
   Stage 2 (the deterministic E2E script).
3. Relay its verdict:
   - `STATUS: PASS` → report "Fáze $1 ověřena (PASS), k inspekci a commitu."
   - `STATUS: DEVIATION` → report the divergences verbatim; ask the developer
     whether each was an approved deviation. Do not proceed on your own.
   - `STATUS: FAIL` → report the failing assertions verbatim. Do **not** try to
     fix them in this turn — return to the developer for direction (pravidlo 2).
   - `STATUS: ERROR` → report it as an environment/setup problem, not a code failure.

Never stage or commit — that is the developer's step (pravidlo 6).
