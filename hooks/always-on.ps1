# SessionStart hook fallback for Windows PowerShell. Injects the full
# i-have-adhd ruleset when the user has opted in by creating
# $CLAUDE_CONFIG_DIR/.i-have-adhd-always (default ~/.claude).
# Never blocks session start: any failure exits 0.

try {
  $claudeDir = if ($env:CLAUDE_CONFIG_DIR) {
    $env:CLAUDE_CONFIG_DIR
  } else {
    Join-Path ([Environment]::GetFolderPath("UserProfile")) ".claude"
  }
  $flagPath = Join-Path $claudeDir ".i-have-adhd-always"

  if (-not (Test-Path -LiteralPath $flagPath -PathType Leaf)) {
    exit 0
  }

  # This event also fires on resume and compaction, so it re-injects mid-session.
  # Without this check that re-injection re-asserts ADHD MODE ACTIVE after the user
  # has said "stop adhd mode", reversing a choice the banner promises holds for the
  # session. The UserPromptSubmit hook records the phrase as a marker named after
  # the session; an unreadable payload leaves no session to check and the ruleset
  # is injected as before.
  if ([Console]::IsInputRedirected) {
    $payload = [Console]::In.ReadToEnd()
    $sessionId = ""
    if ($payload) {
      try {
        $candidate = ($payload | ConvertFrom-Json).session_id
        if ($candidate -is [string] -and $candidate -match '^[A-Za-z0-9._-]{1,128}$') {
          $sessionId = $candidate
        }
      } catch {
        # A payload this hook cannot parse is one it cannot attribute.
      }
    }
    if ($sessionId) {
      $markerPath = Join-Path $claudeDir ".i-have-adhd-off-$sessionId"
      if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
        exit 0
      }
    }
  }

  $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  $skillPath = Join-Path $scriptDir "../skills/i-have-adhd/SKILL.md"
  if (-not (Test-Path -LiteralPath $skillPath -PathType Leaf)) {
    exit 0
  }

  $lines = [System.IO.File]::ReadAllLines($skillPath)
  $bodyStart = 0

  if ($lines.Length -gt 0 -and $lines[0] -match '^---\s*$') {
    # Only treat the block as frontmatter when the closing delimiter exists;
    # an unterminated fence is not frontmatter, so keep the whole file.
    for ($i = 1; $i -lt $lines.Length; $i++) {
      if ($lines[$i] -match '^---\s*$') {
        $bodyStart = $i + 1
        break
      }
    }
  }

  $body = if ($bodyStart -lt $lines.Length) {
    [string]::Join([Environment]::NewLine, $lines[$bodyStart..($lines.Length - 1)])
  } else {
    ""
  }

  $banner = 'ADHD MODE ACTIVE (always-on). The ruleset below applies to every response. ' +
    '"stop adhd mode" turns it off for this session; delete '
  [Console]::Out.Write($banner + $flagPath + " to turn always-on off for good.`n`n" + $body + "`n")
} catch {
  # Never block session start.
  exit 0
}
