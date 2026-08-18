#!/usr/bin/env sh
# SessionStart hook: injects the full i-have-adhd ruleset when the user has
# opted in by creating $CLAUDE_CONFIG_DIR/.i-have-adhd-always (default ~/.claude).
# Never blocks session start: any failure exits 0.
#
# POSIX fallback for environments where the default Node hook cannot run. It
# works with sh on macOS/Linux and Git Bash on Windows without a Node install.

claude_dir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
flag_path="$claude_dir/.i-have-adhd-always"

# Only fire when the user has opted in.
[ -f "$flag_path" ] || exit 0

# This event also fires on resume and compaction, so it re-injects mid-session.
# Without this check that re-injection re-asserts ADHD MODE ACTIVE after the user
# has said "stop adhd mode", reversing a choice the banner promises holds for the
# session. The UserPromptSubmit hook records the phrase as a marker named after
# the session. Only the id is read out of the payload, with a character class
# tight enough that no shell metacharacter can reach the path; an unreadable
# payload leaves no session to check and the ruleset is injected as before.
if [ ! -t 0 ]; then
  session_id=$(sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9._-]\{1,128\}\)".*/\1/p' | head -n 1)
  if [ -n "$session_id" ] && [ -f "$claude_dir/.i-have-adhd-off-$session_id" ]; then
    exit 0
  fi
fi

# $0 is the absolute script path substituted into hooks.json by Claude Code,
# so resolve SKILL.md relative to it instead of trusting an exported env var.
script_dir=$(dirname -- "$0")
skill_path="$script_dir/../skills/i-have-adhd/SKILL.md"
[ -f "$skill_path" ] || exit 0

# Strip a leading YAML frontmatter block (--- ... --- at the very top of file).
# An unterminated fence is not frontmatter, so the whole file is kept unless the
# closing delimiter exists (two passes; matches the Node and PowerShell hooks).
body=$(awk '
  NR == FNR {
    if (NR == 1 && $0 ~ /^---[[:space:]]*$/) { in_fm = 1; next }
    if (in_fm && $0 ~ /^---[[:space:]]*$/)   { in_fm = 0; closed = 1 }
    next
  }
  FNR == 1 { strip = closed }
  strip && FNR == 1 && $0 ~ /^---[[:space:]]*$/ { skipping = 1; next }
  skipping && $0 ~ /^---[[:space:]]*$/          { skipping = 0; next }
  !skipping { print }
' "$skill_path" "$skill_path") || exit 0

printf 'ADHD MODE ACTIVE (always-on). The ruleset below applies to every response. "stop adhd mode" turns it off for this session; delete %s to turn always-on off for good.\n\n%s\n' \
  "$flag_path" "$body"
