#!/bin/sh
# Session manager hook (SessionStart / SessionEnd), run by hooks/hooks.json.
# Exits at once while managing is off (no <data>/tracking flag file). Otherwise
# runs `track`, which reads the hook JSON on stdin: the PowerShell script on
# Windows (hooks run in Git Bash there), the Python one on Linux and macOS.
# Output is discarded: a SessionStart hook's stdout would be added to the
# session's context.
[ -f "$CLAUDE_PLUGIN_DATA/tracking" ] || exit 0
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$CLAUDE_PLUGIN_ROOT/scripts/sessions.ps1" track -DataDir "$CLAUDE_PLUGIN_DATA" ;;
  *)
    python3 "$CLAUDE_PLUGIN_ROOT/scripts/sessions.py" track -DataDir "$CLAUDE_PLUGIN_DATA" ;;
esac >/dev/null 2>&1
exit 0
