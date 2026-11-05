:; # Session manager hook (SessionStart / SessionEnd), run by hooks/hooks.json as
:; # `. "${CLAUDE_PLUGIN_ROOT}/hooks/track.cmd"`. One file, two languages, so the
:; # hook works in whichever shell Claude Code picks: sh on Linux and macOS, Git
:; # Bash on Windows, or PowerShell on Windows when Git Bash isn't installed.
:; #  - sh sources this file and runs the ":;" lines (":" is a no-op), then exits
:; #    before the batch part.
:; #  - PowerShell runs it with cmd.exe, which skips ":" lines as labels and runs
:; #    the batch part below.
:; # Both exit at once while managing is off (no <data>/tracking flag file), else
:; # run `track`, which reads the hook JSON on stdin. Output is discarded: a
:; # SessionStart hook's stdout would be added to the session's context.
:; [ -f "$CLAUDE_PLUGIN_DATA/tracking" ] || exit 0
:; case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$CLAUDE_PLUGIN_ROOT/scripts/sessions.ps1" track -DataDir "$CLAUDE_PLUGIN_DATA" ;; *) python3 "$CLAUDE_PLUGIN_ROOT/scripts/sessions.py" track -DataDir "$CLAUDE_PLUGIN_DATA" ;; esac >/dev/null 2>&1
:; exit 0
@echo off
if not exist "%CLAUDE_PLUGIN_DATA%\tracking" exit /b 0
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CLAUDE_PLUGIN_ROOT%\scripts\sessions.ps1" track -DataDir "%CLAUDE_PLUGIN_DATA%" >nul 2>&1
exit /b 0
