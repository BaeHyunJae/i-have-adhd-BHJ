// UserPromptSubmit hook: keeps "stop adhd mode" in force for the rest of the
// session.
//
// Why: the SessionStart hook's matcher covers `compact`, so a compaction
// re-injects the ruleset and re-asserts ADHD MODE ACTIVE. The banner
// promises the phrase turns the mode off "for this session", but nothing
// recorded that the user said it, so the promise held only until the next
// compaction silently reversed it. Recording the phrase is the only way the
// SessionStart hook can honour it — a hook that never sees a prompt cannot know.
//
// State is one marker file per session, so a session that turns the mode off
// never silences another one running beside it. A fresh session takes a new id
// and so cannot carry a marker, which is why there is no source branch here.
//
// Runs under Node for the same reason as always-on.mjs: no POSIX shell needed.
// Never blocks a prompt: any failure exits 0.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Markers older than this are swept on the next write. A session that ends
// without turning the mode back on leaves its marker behind, and nothing else
// ever deletes it.
const STALE_MARKER_MS = 7 * 24 * 60 * 60 * 1000;

// The phrases SKILL.md names as turning the ruleset off.
const OFF_PHRASES = /\b(?:stop adhd mode|normal mode)\b/i;
// Re-enabling is the skill's own invocation, the one way the docs describe.
// Claude Code wraps a user-invoked skill in a <command-name> envelope; a plain
// typed `/i-have-adhd` reaches the hook as itself.
const ON_PHRASES = /(?:^|\s)\/i-have-adhd\b|<command-name>\s*\/?i-have-adhd\s*<\/command-name>/i;

// A session id names a file, so refuse anything that is not the plain token
// shape Claude Code uses. Without this a crafted id could walk out of the
// config directory.
const SESSION_ID = /^[A-Za-z0-9._-]{1,128}$/;

function readPayload() {
  // A TTY means this was run by hand; there is no payload to read and a blocking
  // read would hang.
  if (process.stdin.isTTY) return null;
  try {
    const raw = fs.readFileSync(0, "utf8");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// Quoted and fenced text is discussion about the phrase, not the phrase. This
// hook's whole job is to believe the user, so it must not believe a code sample.
function stripQuotedText(prompt) {
  return prompt
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`[^`]*`/g, " ")
    .replace(/"[^"]*"/g, " ");
}

function removeMarker(markerPath) {
  try {
    fs.unlinkSync(markerPath);
  } catch {
    // Absent is the desired state; anything else is not worth blocking a prompt.
  }
}

function writeMarker(markerPath) {
  // The marker is a fact, not data: nothing reads its contents, so it is empty
  // and its own existence is the whole signal. `wx` is what makes that safe —
  // it fails rather than following a symlink someone else left at the path, and
  // fails again if the marker is already there, so neither case needs a branch.
  try {
    fs.writeFileSync(markerPath, "", { flag: "wx", mode: 0o600 });
  } catch {
    // Already recorded, a symlink, or an unwritable directory. Nothing to do.
  }
}

function sweepStaleMarkers(claudeDir, prefix) {
  try {
    const cutoff = Date.now() - STALE_MARKER_MS;
    for (const name of fs.readdirSync(claudeDir)) {
      if (!name.startsWith(prefix)) continue;
      const full = path.join(claudeDir, name);
      try {
        if (fs.lstatSync(full).mtimeMs < cutoff) fs.unlinkSync(full);
      } catch {
        // One unreadable entry must not stop the sweep.
      }
    }
  } catch {
    // No config directory to sweep.
  }
}

try {
  const payload = readPayload();
  const prompt = typeof payload?.prompt === "string" ? payload.prompt : "";
  const sessionId = typeof payload?.session_id === "string" ? payload.session_id : "";
  if (!SESSION_ID.test(sessionId)) process.exit(0);

  const claudeDir = process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
  const markerPrefix = ".i-have-adhd-off-";
  const markerPath = path.join(claudeDir, markerPrefix + sessionId);

  const spoken = stripQuotedText(prompt);
  if (ON_PHRASES.test(spoken)) {
    removeMarker(markerPath);
  } else if (OFF_PHRASES.test(spoken)) {
    sweepStaleMarkers(claudeDir, markerPrefix);
    writeMarker(markerPath);
  }
} catch {
  // Never block a prompt.
  process.exit(0);
}
