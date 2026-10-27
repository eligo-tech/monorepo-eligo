#!/usr/bin/env bash
# Inject the agent bootstrap rule into context at session start.
#
# Availability is not adherence: a rule file that exists but is never read
# changes nothing. This hook makes the bootstrap arrive deterministically, at
# startup and again after /clear and after compaction — the three moments an
# agent would otherwise forget it.
#
# It only ever READS one file in this repo and prints JSON. It must never fail
# the session: a broken hook that blocks startup is worse than no hook.
set -uo pipefail

# The script lives at <root>/.claude/hooks/, so its own location identifies the
# repo even when CLAUDE_PROJECT_DIR is unset and the cwd is somewhere else.
# Falling back to `pwd` would silently load nothing, which is the one failure
# mode worth engineering against: rules that quietly don't apply.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
ROOT="${CLAUDE_PROJECT_DIR:-${HERE%/.claude/hooks}}"
RULE="$ROOT/.claude/skills/using-superpowers/SKILL.md"
EMPTY='{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":""}}'

if [ ! -r "$RULE" ]; then
  printf '%s\n' "$EMPTY"
  exit 0
fi

RULE="$RULE" python3 -c '
import json, os, sys
try:
    body = open(os.environ["RULE"], encoding="utf-8").read()
except Exception:
    body = ""
if body:
    body = (
        "The following project rules were loaded automatically from the "
        "using-superpowers skill. They are binding for this repository and "
        "take precedence over default working habits. The eight skills they "
        "dispatch to are invocable by name.\n\n"
    ) + body
json.dump({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": body,
}}, sys.stdout)
sys.stdout.write("\n")
' 2>/dev/null || printf '%s\n' "$EMPTY"
