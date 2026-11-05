<#
  Self-contained tests for sessions.ps1 (no Pester needed).
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1 [-Launch]
  -Launch also runs a real end-to-end restore that opens (and auto-closes) terminal tabs.
#>
param([switch]$Launch)

$ErrorActionPreference = 'Stop'
# These tests may run inside a Claude session: don't let its process id leak into simulated hooks.
Remove-Item Env:CLAUDE_PID -ErrorAction SilentlyContinue
$script = Join-Path $PSScriptRoot '..\sessions.ps1'
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("sessions-test-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
$failures = 0
$passes = 0

function Assert($cond, [string]$name) {
    if ($cond) { $script:passes++; Write-Host "  ok   $name" }
    else { $script:failures++; Write-Host "  FAIL $name" -ForegroundColor Red; Write-Host "       last output: $script:lastOut" }
}

function Run([string[]]$argv) {
    $out = & powershell -NoProfile -ExecutionPolicy Bypass -File $script @argv
    $script:lastOut = $out -join "`n"
    return (($out -join "`n") | ConvertFrom-Json)
}

function Write-Utf8([string]$path, [string]$text) {
    New-Item -ItemType Directory -Force -Path (Split-Path $path) | Out-Null
    [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
}

function Write-Registry([string]$home_, [int]$procId, [string]$sid, [string]$cwd, [string]$procStart, [string]$kind, [long]$startedAt = 1793722012466) {
    $o = [ordered]@{ pid = $procId; sessionId = $sid; cwd = $cwd; startedAt = $startedAt; procStart = $procStart; kind = $kind; name = "reg-$($sid.Substring(0,4))"; status = 'idle' }
    Write-Utf8 (Join-Path $home_ "sessions\$procId.json") (ConvertTo-Json $o)
}

function Write-Transcript([string]$home_, [string]$sid, [string]$cwd, [string[]]$extra) {
    $cwdJson = ConvertTo-Json $cwd
    $lines = @(('{"type":"mode","mode":"normal","sessionId":"' + $sid + '"}'),
        ('{"type":"user","message":{"role":"user","content":"hi"},"cwd":' + $cwdJson + ',"sessionId":"' + $sid + '"}')) + @($extra | Where-Object { $_ })
    Write-Utf8 (Join-Path $home_ "projects\proj\$sid.jsonl") ($lines -join "`n")
}

$A = 'aaaaaaaa-0000-4000-8000-000000000001'   # live, interactive
$B = 'bbbbbbbb-0000-4000-8000-000000000002'   # live, non-interactive
$C = 'cccccccc-0000-4000-8000-000000000003'   # PID reused (procStart mismatch)
$D = 'dddddddd-0000-4000-8000-000000000004'   # dead PID
$E = 'eeeeeeee-0000-4000-8000-000000000005'   # ended, transcript only
$F = 'ffffffff-0000-4000-8000-000000000006'   # folder missing
$G = 'aaaabbbb-0000-4000-8000-000000000007'   # transcript missing
$U = '12345678-0000-4000-8000-00000000000f'   # unknown

$home1 = Join-Path $root 'claude'
$data = Join-Path $root 'data'
$projA = Join-Path $root "proj A's folder"   # space + quote exercise escaping
New-Item -ItemType Directory -Force -Path $projA | Out-Null

$helper = Start-Process powershell -ArgumentList '-NoProfile', '-Command', 'Start-Sleep 120' -WindowStyle Hidden -PassThru
try {
    $me = Get-Process -Id $PID
    Write-Registry $home1 $PID $A $projA ($me.StartTime.ToFileTimeUtc().ToString()) 'interactive'
    Write-Registry $home1 $helper.Id $B $projA ((Get-Process -Id $helper.Id).StartTime.ToFileTimeUtc().ToString()) 'sdk'
    # Same live PID as A but a different start time: must be treated as stale.
    $o = [ordered]@{ pid = 999998; sessionId = $C; cwd = $projA; procStart = '1'; kind = 'interactive' }
    Write-Utf8 (Join-Path $home1 'sessions\c.json') ((ConvertTo-Json $o) -replace '999998', "$PID")
    Write-Registry $home1 999999 $D $projA '1' 'interactive'
    Write-Utf8 (Join-Path $home1 'sessions\broken.json') '{"pid": 12, "sessio'

    Write-Transcript $home1 $A $projA @(
        ('{"type":"ai-title","aiTitle":"Old AI title","sessionId":"' + $A + '"}'),
        ('{"type":"custom-title","customTitle":"My named session","sessionId":"' + $A + '"}'),
        ('{"type":"ai-title","aiTitle":"Newer AI title","sessionId":"' + $A + '"}'),
        ('{"type":"last-prompt","lastPrompt":"fix   the\nbug","sessionId":"' + $A + '"}'))
    Write-Transcript $home1 $E $projA @('{"type":"ai-title","aiTitle":"Ended work","sessionId":"' + $E + '"}')
    Write-Transcript $home1 $F (Join-Path $root 'gone') @()

    Write-Host 'list'
    $r = Run @('list', '-ClaudeHome', $home1, '-CurrentSessionId', $A)
    Assert ($r.ok -and $r.source -eq 'registry') 'reads the live-session registry'
    Assert (@($r.sessions).Count -eq 1 -and $r.sessions[0].sessionId -eq $A) 'only live interactive session (stale, reused-PID, dead, broken skipped)'
    Assert ($r.hiddenNonInteractive -eq 1) 'counts hidden non-interactive session'
    Assert ($r.sessions[0].isCurrent -eq $true) 'flags current session'
    Assert ($r.sessions[0].title -eq 'My named session') 'custom title wins over AI title'
    Assert ($r.sessions[0].lastPrompt -eq 'fix the bug') 'last prompt collapsed to one line'
    Assert ($r.sessions[0].cwd -eq $projA) 'cwd round-trips with space and quote'

    $r = Run @('list', '-ClaudeHome', $home1, '-IncludeNonInteractive')
    Assert (@($r.sessions).Count -eq 2) '-IncludeNonInteractive adds the sdk session'
    $sdk = @($r.sessions | Where-Object { $_.sessionId -eq $B })[0]
    Assert ($sdk.title -eq 'reg-bbbb') 'falls back to registry name without transcript'
    Assert ($sdk.shell -eq 'powershell' -and $sdk.shellPath -like '*powershell.exe') 'detects the shell a session was started from'
    Assert ($null -eq $sdk.host) 'hidden window is not taken for a console window'

    # A "claude" (here: powershell) started from cmd in a standalone console window.
    $H = '99999999-0000-4000-8000-000000000009'
    $home3 = Join-Path $root 'claude3'
    $con = Start-Process "$env:SystemRoot\System32\conhost.exe" -ArgumentList 'cmd.exe /c powershell.exe -NoProfile -Command Start-Sleep 60' -WindowStyle Minimized -PassThru
    $inner = $null
    for ($i = 0; $i -lt 30 -and -not $inner; $i++) {
        Start-Sleep -Milliseconds 200
        $cmdP = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($con.Id) AND Name='cmd.exe'"
        if ($cmdP) { $inner = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($cmdP.ProcessId) AND Name='powershell.exe'" }
    }
    try {
        Write-Registry $home3 $inner.ProcessId $H $projA ((Get-Process -Id $inner.ProcessId).StartTime.ToFileTimeUtc().ToString()) 'interactive'
        $r = Run @('list', '-ClaudeHome', $home3)
        $conSession = @($r.sessions)[0]
        if ($env:GITHUB_ACTIONS -and (Get-Process -Id $cmdP.ProcessId).MainWindowHandle -eq [IntPtr]::Zero) {
            # Hosted CI runners have no visible desktop, so a console window gets no handle there.
            Write-Host '  note detects a standalone console window: skipped (no visible desktop on this runner)'
        } else {
            Assert ($conSession.sessionId -eq $H -and $conSession.shell -eq 'cmd' -and $conSession.host -eq 'console') 'detects a standalone console window'
        }
    } finally {
        Stop-Process -Id $con.Id -ErrorAction SilentlyContinue
        if ($inner) { Stop-Process -Id $inner.ProcessId -ErrorAction SilentlyContinue }
        if ($cmdP) { Stop-Process -Id $cmdP.ProcessId -ErrorAction SilentlyContinue }
    }

    Write-Host 'save'
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $data, '-Ids', "$A,$E,$U")
    Assert ($r.ok -and @($r.saved).Count -eq 2) 'saves live + ended-with-transcript sessions'
    Assert (@($r.missing).Count -eq 1 -and $r.missing[0] -eq $U) 'reports unknown id as missing'
    Assert (Test-Path -LiteralPath $r.snapshot) 'snapshot file written'
    $ended = @($r.saved | Where-Object { $_.sessionId -eq $E })[0]
    Assert ($ended.cwd -eq $projA -and $ended.title -eq 'Ended work') 'ended session takes cwd/title from transcript'

    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', '${CLAUDE_PLUGIN_DATA}', '-Ids', $A)
    Assert ($r.ok -and $r.dataDirFallback -and $r.dataDir -eq (Join-Path $home1 'plugins\data\sessions-vslipchenko')) 'unsubstituted data dir falls back'

    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $data, '-Ids', 'not-a-guid')
    Assert ($r.ok -eq $false -and $r.error -eq 'bad-id') 'rejects malformed ids'
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $data, '-Ids', $U)
    Assert ($r.ok -eq $false -and $r.error -eq 'nothing-saved') 'fails when nothing can be saved'

    Write-Host 'save: one snapshot, unrestored ones protected'
    $one = Join-Path $root 'one'
    $oneSnaps = Join-Path $one 'snapshots'
    function Count-Snaps { @(Get-ChildItem $oneSnaps -Filter 'snapshot-*.json').Count }
    function Write-OneSnap([string]$name, $extra) {
        $s = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @()
            sessions = @([ordered]@{ sessionId = $A; cwd = $projA; title = 'a' }, [ordered]@{ sessionId = $E; cwd = $projA; title = 'e' }) }
        foreach ($k in $extra.Keys) { $s[$k] = $extra[$k] }
        Write-Utf8 (Join-Path $oneSnaps $name) (ConvertTo-Json $s -Depth 5)
    }

    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $A)
    Assert ($r.ok -and $r.replaced -eq 0) 'first save writes the snapshot'
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $E)
    Assert ($r.ok -eq $false -and $r.error -eq 'unrestored-snapshot' -and @($r.pendingSnapshot.pending).Count -eq 1 -and $r.pendingSnapshot.pending[0].sessionId -eq $A) 'refuses to replace an unrestored snapshot'
    Assert ((Count-Snaps) -eq 1) 'refused save leaves the snapshot alone'
    $r = Run @('list', '-ClaudeHome', $home1, '-DataDir', $one)
    Assert ($r.ok -and $r.pendingSnapshot -and $r.pendingSnapshot.pending[0].title) 'list reports the unrestored snapshot'
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $E, '-Force')
    Assert ($r.ok -and $r.replaced -eq 1 -and (Count-Snaps) -eq 1) '-Force replaces it, one snapshot left'

    Get-ChildItem $oneSnaps | Remove-Item
    Write-OneSnap 'snapshot-20260101-000000.json' @{ restoredAt = '2026-01-01T01:00:00Z'; settledSessionIds = @($A, $E) }
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $A)
    Assert ($r.ok -and $r.replaced -eq 1 -and (Count-Snaps) -eq 1) 'fully restored snapshot is replaced silently'
    Get-ChildItem $oneSnaps | Remove-Item
    Write-OneSnap 'snapshot-20260101-000000.json' @{ restoredAt = '2026-01-01T01:00:00Z'; settledSessionIds = @($A) }
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $A)
    Assert ($r.ok -eq $false -and @($r.pendingSnapshot.pending).Count -eq 1 -and $r.pendingSnapshot.pending[0].sessionId -eq $E) 'partly restored snapshot protects the rest'

    Get-ChildItem $oneSnaps | Remove-Item
    1..3 | ForEach-Object { Write-OneSnap "snapshot-2026010$_-000000.json" @{ restoredAt = '2026-01-01T01:00:00Z' } }
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $A)
    Assert ($r.ok -and $r.replaced -eq 3 -and (Count-Snaps) -eq 1) 'older restored snapshots (earlier format) are cleaned up'

    # A restore where every session is either open or gone settles the snapshot without opening anything.
    Get-ChildItem $oneSnaps | Remove-Item
    $s = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @(); settledSessionIds = @()
        sessions = @([ordered]@{ sessionId = $A; cwd = $projA; title = 'a' }, [ordered]@{ sessionId = $F; cwd = (Join-Path $root 'gone'); title = 'f' }) }
    Write-Utf8 (Join-Path $oneSnaps 'snapshot-20260101-000000.json') (ConvertTo-Json $s -Depth 5)
    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $one, '-ClaudeExe', 'C:\x\claude.exe')
    Assert ($r.ok -and @($r.launched).Count -eq 0 -and @($r.skipped).Count -eq 2) 'restore with nothing to open'
    $r = Run @('save', '-ClaudeHome', $home1, '-DataDir', $one, '-Ids', $A)
    Assert ($r.ok -and (Count-Snaps) -eq 1) 'sessions that are open or gone count as settled'

    Write-Host 'clear'
    $clr = Join-Path $root 'clear'
    $clrSnaps = Join-Path $clr 'snapshots'
    $r = Run @('clear', '-ClaudeHome', $home1, '-DataDir', $clr)
    Assert ($r.ok -and @($r.removed).Count -eq 0 -and $r.removedSessions -eq 0) 'clear with nothing saved is a no-op'
    function Write-ClearSnap($extra) {
        $s = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @()
            sessions = @([ordered]@{ sessionId = $A; cwd = $projA; title = 'a' }, [ordered]@{ sessionId = $E; cwd = $projA; title = 'e' }) }
        foreach ($k in $extra.Keys) { $s[$k] = $extra[$k] }
        Write-Utf8 (Join-Path $clrSnaps 'snapshot-20260101-000000.json') (ConvertTo-Json $s -Depth 5)
    }
    Write-ClearSnap @{}
    Write-Utf8 (Join-Path $clr 'config.json') '{"restoreShell":"cmd","restoreTerminal":null}'
    $r = Run @('clear', '-ClaudeHome', $home1, '-DataDir', $clr)
    Assert ($r.ok -eq $false -and $r.error -eq 'unrestored-snapshot' -and @($r.pendingSnapshot.pending).Count -eq 2) 'clear refuses an unrestored snapshot'
    Assert (Test-Path (Join-Path $clrSnaps 'snapshot-20260101-000000.json')) 'refused clear keeps the snapshot'
    $r = Run @('clear', '-ClaudeHome', $home1, '-DataDir', $clr, '-Force')
    Assert ($r.ok -and @($r.removed).Count -eq 1 -and $r.removedSessions -eq 2) 'clear -Force deletes it'
    Assert ($r.configKept -and -not $r.configRemoved -and (Test-Path (Join-Path $clr 'config.json'))) 'clear keeps restore defaults'
    Write-ClearSnap @{ restoredAt = '2026-01-01T01:00:00Z'; settledSessionIds = @($A, $E) }
    $r = Run @('clear', '-ClaudeHome', $home1, '-DataDir', $clr, '-IncludeConfig')
    Assert ($r.ok -and @($r.removed).Count -eq 1 -and $r.configRemoved -and -not (Test-Path (Join-Path $clr 'config.json'))) 'restored snapshot clears without -Force; -IncludeConfig drops defaults'
    Assert (@(Get-ChildItem $clrSnaps).Count -eq 0) 'nothing left after clear'

    Write-Host 'original order'
    $homeOrd = Join-Path $root 'claude-order'
    # Opened first: this test process; opened second: the helper (both live, both interactive here).
    Write-Registry $homeOrd $PID $A $projA ($me.StartTime.ToFileTimeUtc().ToString()) 'interactive' 1793722000000
    Write-Registry $homeOrd $helper.Id $B $projA ((Get-Process -Id $helper.Id).StartTime.ToFileTimeUtc().ToString()) 'interactive' 1793722060000
    $r = Run @('list', '-ClaudeHome', $homeOrd, '-CurrentSessionId', $B)
    Assert ((@($r.sessions | ForEach-Object { $_.sessionId }) -join ',') -eq "$A,$B") 'list in opening order, current not pinned'
    $ordData = Join-Path $root 'order-data'
    $r = Run @('save', '-ClaudeHome', $homeOrd, '-DataDir', $ordData, '-Ids', "$B,$A")
    Assert ((@($r.saved | ForEach-Object { $_.sessionId }) -join ',') -eq "$A,$B" -and $r.saved[0].startedAt) 'saved in opening order, whatever the pick order'
    $H1 = '11111111-0000-4000-8000-0000000000a1'
    $H2 = '22222222-0000-4000-8000-0000000000a2'
    Write-Transcript $home1 $H1 $projA @()
    Write-Transcript $home1 $H2 $projA @()
    $ordSnap = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @(); sessions = @(
            [ordered]@{ sessionId = $H2; cwd = $projA; title = 'two'; startedAt = '2026-11-04T10:01:00.0000000+00:00' },
            [ordered]@{ sessionId = $H1; cwd = $projA; title = 'one'; startedAt = '2026-11-04T10:00:00Z' }) }
    Write-Utf8 (Join-Path $ordData 'snapshots\order.json') (ConvertTo-Json $ordSnap -Depth 5)
    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $ordData, '-DryRun', '-Snapshot', 'order', '-ClaudeExe', 'C:\x\claude.exe')
    Assert ((@($r.launched | ForEach-Object { $_.sessionId }) -join ',') -eq "$H1,$H2") 'restore reopens in opening order'
    $ordSnap.sessions = @([ordered]@{ sessionId = $H2; cwd = $projA; title = 'two' }, [ordered]@{ sessionId = $H1; cwd = $projA; title = 'one' })
    Write-Utf8 (Join-Path $ordData 'snapshots\order.json') (ConvertTo-Json $ordSnap -Depth 5)
    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $ordData, '-DryRun', '-Snapshot', 'order', '-ClaudeExe', 'C:\x\claude.exe')
    Assert ((@($r.launched | ForEach-Object { $_.sessionId }) -join ',') -eq "$H2,$H1") 'no start times: stored order kept'

    Write-Host 'manage / track'
    $homeTr = Join-Path $root 'claude-track'
    $mg = Join-Path $root 'manage'
    $mgSnaps = Join-Path $mg 'snapshots'
    # This process = an interactive session; the helper = a headless `claude -p` run.
    $o = [ordered]@{ pid = $PID; sessionId = $A; cwd = $projA; startedAt = 1793722000000; procStart = $me.StartTime.ToFileTimeUtc().ToString(); kind = 'interactive'; entrypoint = 'cli'; name = 'Session A' }
    Write-Utf8 (Join-Path $homeTr "sessions\$PID.json") (ConvertTo-Json $o)
    $o = [ordered]@{ pid = $helper.Id; sessionId = $B; cwd = $projA; startedAt = 1793722060000; procStart = (Get-Process -Id $helper.Id).StartTime.ToFileTimeUtc().ToString(); kind = 'interactive'; entrypoint = 'sdk-cli'; name = 'Headless' }
    Write-Utf8 (Join-Path $homeTr "sessions\$($helper.Id).json") (ConvertTo-Json $o)
    Write-Transcript $homeTr $E $projA @(('{"type":"ai-title","aiTitle":"Tracked E","sessionId":"' + $E + '"}'))

    function Track($json, [string]$procId) {
        $argv = @('track', '-ClaudeHome', $homeTr, '-DataDir', $mg)
        if ($procId) { $argv += @('-ClaudePid', $procId) }
        $out = $json | & powershell -NoProfile -ExecutionPolicy Bypass -File $script @argv
        $script:lastOut = $out -join "`n"
        return (($out -join "`n") | ConvertFrom-Json)
    }
    function Mg-Sessions {
        $snapObj = Get-Content -Raw (Get-ChildItem $mgSnaps -Filter 'snapshot-*.json')[0].FullName | ConvertFrom-Json
        # Each entry must be a session object (a nested array here would mean a broken write).
        foreach ($s in @($snapObj.sessions)) { if ($s -is [array]) { throw 'nested sessions array' }; $s }
    }
    $start = { param($sid, $src) '{"session_id":"' + $sid + '","cwd":"' + ($projA -replace '\\', '\\') + '","hook_event_name":"SessionStart","source":"' + $src + '"}' }
    $end = { param($sid, $why) '{"session_id":"' + $sid + '","hook_event_name":"SessionEnd","reason":"' + $why + '"}' }

    # Sessions of other apps on a live process (the helper): Claude Desktop and the VS Code extension.
    foreach ($x in @(@{ file = 'desk'; sid = $C; entry = 'claude-desktop' }, @{ file = 'vsc'; sid = $D; entry = 'claude-vscode' })) {
        $o = [ordered]@{ pid = $helper.Id; sessionId = $x.sid; cwd = $projA; startedAt = 1793722090000; procStart = (Get-Process -Id $helper.Id).StartTime.ToFileTimeUtc().ToString(); kind = 'interactive'; entrypoint = $x.entry; name = $x.file }
        Write-Utf8 (Join-Path $homeTr "sessions\$($x.file).json") (ConvertTo-Json $o)
    }
    $r = Run @('list', '-ClaudeHome', $homeTr)
    Assert ((@($r.sessions | ForEach-Object { $_.sessionId }) -join ',') -eq $A -and $r.hiddenNonInteractive -eq 3) 'only terminal (cli) sessions offered: headless, Claude Desktop, VS Code extension left out'
    Assert ($r.hiddenFrom.'Claude Desktop' -eq 1 -and $r.hiddenFrom.'VS Code extension' -eq 1 -and $r.hiddenFrom.'headless / SDK' -eq 1) 'left-out sessions counted per app'
    # An older session file without an entrypoint field still counts as a terminal session.
    $homeOld = Join-Path $root 'claude-old'
    $o = [ordered]@{ pid = $helper.Id; sessionId = $C; cwd = $projA; startedAt = 1793722090000; procStart = (Get-Process -Id $helper.Id).StartTime.ToFileTimeUtc().ToString(); kind = 'interactive' }
    Write-Utf8 (Join-Path $homeOld "sessions\$($helper.Id).json") (ConvertTo-Json $o)
    $r = Run @('list', '-ClaudeHome', $homeOld)
    Assert ((@($r.sessions | ForEach-Object { $_.sessionId }) -join ',') -eq $C) 'session file without entrypoint still listed'
    $r = Track (& $start $E 'startup') $PID
    Assert ($r.ok -and -not $r.tracked -and $r.why -eq 'not-managing') 'track does nothing while not managing'
    $r = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg)
    Assert ($r.ok -and -not $r.managing) 'status: not managing'
    $r = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Enable', '-Ids', $A)
    Assert ($r.ok -and $r.managing -and @($r.saved).Count -eq 1 -and (Test-Path (Join-Path $mg 'tracking'))) 'manage -Enable starts with the picked sessions'
    $r = Run @('list', '-ClaudeHome', $homeTr, '-DataDir', $mg)
    Assert ($r.managing -eq $true) 'list reports managing'
    $r = Run @('save', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Ids', $A)
    Assert ($r.ok -eq $false -and $r.error -eq 'managing') 'manual save refused while managing'

    $r = Track (& $start $E 'startup') $PID
    Assert ($r.tracked -and $r.action -eq 'upsert') 'new session added'
    $rawSnap = Get-Content -Raw (Get-ChildItem $mgSnaps -Filter 'snapshot-*.json')[0].FullName
    Assert ($rawSnap -match '"settledSessionIds":\s*\[' -and $rawSnap -notmatch '"(restored|settled)SessionIds":\s*\{') 'empty id lists stay arrays (not {})'
    $ss = Mg-Sessions
    Assert ((@($ss | ForEach-Object { $_.sessionId }) -join ',') -eq "$A,$E" -and @($ss | Where-Object { $_.sessionId -eq $E })[0].title -eq 'Tracked E') 'snapshot holds both, in opening order, with title'
    $firstStart = @($ss | Where-Object { $_.sessionId -eq $E })[0].startedAt
    $r = Track (& $start $E 'resume') $PID
    $ss = Mg-Sessions
    Assert (@($ss | Where-Object { $_.sessionId -eq $E }).Count -eq 1 -and [string]@($ss | Where-Object { $_.sessionId -eq $E })[0].startedAt -eq [string]$firstStart) 'resume updates in place, keeps opening time'
    $r = Track (& $start $G 'startup') ([string]$helper.Id)
    Assert (-not $r.tracked -and $r.why -eq 'non-interactive') 'headless session not tracked'
    # A hook firing inside Claude Desktop's own Claude Code.
    $o = [ordered]@{ pid = 999990; sessionId = $G; cwd = $projA; kind = 'interactive'; entrypoint = 'claude-desktop' }
    Write-Utf8 (Join-Path $homeTr 'sessions\999990.json') (ConvertTo-Json $o)
    $r = Track (& $start $G 'startup') '999990'
    Assert (-not $r.tracked -and $r.why -eq 'non-interactive' -and @(Mg-Sessions | Where-Object { $_.sessionId -eq $G }).Count -eq 0) 'Claude Desktop session not tracked'
    $r = Track (& $end $E 'other')
    Assert (-not $r.tracked -and @(Mg-Sessions | Where-Object { $_.sessionId -eq $E }).Count -eq 1) 'closed window / reboot keeps the session'
    $r = Track (& $end $E 'prompt_input_exit')
    Assert ($r.tracked -and $r.action -eq 'remove' -and @(Mg-Sessions | Where-Object { $_.sessionId -eq $E }).Count -eq 0) '/exit drops the session'
    $r = Track 'not json'
    Assert ($r.ok -and -not $r.tracked) 'bad hook input is ignored quietly'
    # The same process starting another session (e.g. after switching renderer) replaces its entry.
    $X = '30000000-0000-4000-8000-000000000001'
    $Y = '30000000-0000-4000-8000-000000000002'
    $null = Track (& $start $X 'startup') $PID
    $null = Track (& $start $Y 'startup') $PID
    $ids = @(Mg-Sessions | ForEach-Object { $_.sessionId })
    Assert (($ids -contains $Y) -and -not ($ids -contains $X) -and ($ids -contains $A)) 'new session in the same process replaces the old entry'
    $null = Track (& $end $Y 'prompt_input_exit')

    # Five sessions starting at once (as during a restore) must all land in the snapshot.
    $many = @('10000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000004', '10000000-0000-4000-8000-000000000005')
    $procs = foreach ($m in $many) {
        $in = Join-Path $root "in-$m.json"
        Write-Utf8 $in (& $start $m 'startup')
        Start-Process powershell -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$script`"", 'track', '-ClaudeHome', "`"$homeTr`"", '-DataDir', "`"$mg`"") -RedirectStandardInput $in -RedirectStandardOutput (Join-Path $root "out-$m.json") -WindowStyle Hidden -PassThru
    }
    $procs | ForEach-Object { $_.WaitForExit(30000) | Out-Null }
    $ids = @(Mg-Sessions | ForEach-Object { $_.sessionId })
    Assert (@($many | Where-Object { $ids -contains $_ }).Count -eq 5 -and -not (Test-Path (Join-Path $mg 'snapshot.lock'))) 'concurrent hooks: all five recorded, lock released'

    $r = Run @('clear', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Force')
    Assert ($r.ok -and $r.managing -eq $true) 'clear keeps managing on'
    $r = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Disable')
    Assert ($r.ok -and -not $r.managing -and $r.wasManaging -and -not (Test-Path (Join-Path $mg 'tracking'))) 'manage -Disable turns it off'
    $r = Track (& $start $E 'startup') $PID
    Assert (-not $r.tracked) 'nothing tracked after disabling'
    # Turning managing on over an unrestored hand-made snapshot needs confirmation.
    $null = Run @('save', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Ids', $A)
    $r = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Enable')
    Assert ($r.ok -eq $false -and $r.error -eq 'unrestored-snapshot') 'enable protects an unrestored snapshot'
    $r = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Enable', '-Force')
    Assert ($r.ok -and $r.managing -and @($r.saved).Count -eq 0 -and $r.replaced -eq 1) 'enable -Force with nothing picked starts empty'
    $null = Run @('manage', '-ClaudeHome', $homeTr, '-DataDir', $mg, '-Disable')

    Write-Host 'snapshots'
    $r = Run @('snapshots', '-ClaudeHome', $home1, '-DataDir', $data)
    Assert ($r.ok -and @($r.snapshots).Count -eq 1 -and $r.snapshots[0].count -eq 2) 'summarises snapshots'
    Assert (@($r.snapshots[0].sessions | Where-Object { $_.sessionId -eq $A }).Count -eq 1) 'summary includes session ids'

    Write-Host 'restore'
    $snapDir = Join-Path $data 'snapshots'
    $snap = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @(); sessions = @(
            [ordered]@{ sessionId = $A; cwd = $projA; title = 'a' },
            [ordered]@{ sessionId = $E; cwd = $projA; title = 'e "quoted"; title' },
            [ordered]@{ sessionId = $F; cwd = (Join-Path $root 'gone'); title = 'f' },
            [ordered]@{ sessionId = $G; cwd = $projA; title = 'g' }) }
    Write-Utf8 (Join-Path $snapDir 'snapshot-29990101-000000.json') (ConvertTo-Json $snap -Depth 5)

    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-DryRun', '-ClaudeExe', 'C:\x\claude.exe')
    Assert ($r.ok -and $r.snapshot -like '*snapshot-29990101-000000.json') 'defaults to newest snapshot'
    Assert (@($r.launched).Count -eq 1 -and $r.launched[0].sessionId -eq $E) 'launches only the resumable session'
    $reasons = @{}; foreach ($s in $r.skipped) { $reasons[$s.sessionId] = $s.reason }
    Assert ($reasons[$A] -eq 'already-running') 'skips already-running session'
    Assert ($reasons[$F] -eq 'folder-missing') 'skips missing folder'
    Assert ($reasons[$G] -eq 'transcript-missing') 'skips missing transcript'
    $expected = "Set-Location -LiteralPath '" + ($projA -replace "'", "''") + "'; & 'C:\x\claude.exe' --resume $E"
    Assert ($r.launched[0].command -eq $expected) 'builds escaped resume command'
    $after = Get-Content -Raw (Join-Path $snapDir 'snapshot-29990101-000000.json') | ConvertFrom-Json
    Assert ($null -eq $after.restoredAt) 'dry run does not mark the snapshot'

    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-DryRun', '-ClaudeExe', 'x', '-Ids', $G)
    Assert (@($r.launched).Count -eq 0 -and @($r.skipped).Count -eq 1) '-Ids restricts the restore'
    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-DryRun', '-ClaudeExe', 'x', '-Snapshot', 'nope')
    Assert ($r.ok -eq $false -and $r.error -eq 'snapshot-not-found') 'unknown snapshot name errors'
    $r = Run @('restore', '-ClaudeHome', $home1, '-DataDir', (Join-Path $root 'empty'), '-DryRun', '-ClaudeExe', 'x')
    Assert ($r.ok -eq $false -and $r.error -eq 'no-snapshots') 'no snapshots errors'

    Write-Host 'restore: shells and fallbacks'
    $realGit = $null
    $gitCmd = Get-Command git -ErrorAction SilentlyContinue
    if ($gitCmd -and $gitCmd.Source -match '^(.*\\Git)\\(cmd|bin|mingw64\\bin)\\git\.exe$') { $realGit = $Matches[1] }
    $noGit = Join-Path $root 'no-git'
    $gitNoMintty = Join-Path $root 'git-no-mintty'
    Write-Utf8 (Join-Path $gitNoMintty 'bin\bash.exe') ''
    $hasWt = [bool](Get-Command wt -ErrorAction SilentlyContinue)
    $claudeX = 'C:\x\claude.exe'

    function Plan($fields, [string[]]$more) {
        $entry = [ordered]@{ sessionId = $E; cwd = $projA; title = 'plan' }
        foreach ($k in $fields.Keys) { $entry[$k] = $fields[$k] }
        $s = [ordered]@{ version = 1; createdAt = '2026-01-01T00:00:00Z'; restoredAt = $null; restoredSessionIds = @(); sessions = @($entry) }
        Write-Utf8 (Join-Path $snapDir 'plan.json') (ConvertTo-Json $s -Depth 5)
        $argv = @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-DryRun', '-Snapshot', 'plan',
            '-ClaudeExe', $claudeX, '-PowerShellExe', 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe') + $more
        $r = Run $argv
        return @($r.launched)[0]
    }

    $p = Plan @{} @()
    Assert ($p.shell -eq 'powershell' -and -not $p.fallback) 'no saved shell -> Windows PowerShell'

    if ($realGit) {
        $p = Plan @{ shell = 'gitbash'; shellPath = "$realGit\usr\bin\bash.exe"; host = $null } @()
        $posix = '/' + $projA.Substring(0, 1).ToLower() + ($projA.Substring(2) -replace '\\', '/')
        $bashCwd = "'" + ($posix -replace "'", "'\''") + "'"
        Assert ($p.shell -eq 'gitbash' -and $p.terminal -eq 'window' -and -not $p.fallback) 'Git Bash session -> Git Bash window'
        Assert ($p.command -eq "cd $bashCwd && ('/c/x/claude.exe' --resume $E || :) && exec bash --login -i") 'builds bash resume command with POSIX paths'
        if ($hasWt) {
            $p = Plan @{ shell = 'gitbash'; shellPath = "$realGit\usr\bin\bash.exe"; host = 'wt' } @()
            Assert ($p.shell -eq 'gitbash' -and $p.terminal -eq 'wt') 'Git Bash in Windows Terminal -> wt tab'
        }
    }
    $p = Plan @{ shell = 'gitbash'; shellPath = 'C:\nowhere\Git\usr\bin\bash.exe' } @('-GitRoot', $noGit)
    Assert ($p.shell -eq 'powershell' -and $p.fallback -like '*Git Bash not found*') 'Git Bash missing -> falls back to PowerShell'
    if ($hasWt) {
        $p = Plan @{ shell = 'gitbash' } @('-GitRoot', $gitNoMintty)
        Assert ($p.shell -eq 'gitbash' -and $p.terminal -eq 'wt' -and $p.fallback -like '*mintty not found*') 'mintty missing -> Git Bash in Windows Terminal'
    }
    $p = Plan @{ shell = 'pwsh' } @()
    Assert ($p.shell -eq 'powershell' -and $p.fallback -like '*pwsh not found*') 'pwsh missing -> Windows PowerShell'
    $p = Plan @{ shell = 'cmd' } @('-Terminal', 'window')
    Assert ($p.shell -eq 'cmd' -and $p.terminal -eq 'window' -and $p.command -eq "/k $claudeX --resume $E") 'cmd session -> cmd /k resume'
    $p = Plan @{ shell = 'powershell'; host = 'console' } @()
    Assert ($p.shell -eq 'powershell' -and $p.terminal -eq 'window') 'console-window session -> console window'
    if ($hasWt) {
        $p = Plan @{ shell = 'powershell'; host = 'wt' } @()
        Assert ($p.terminal -eq 'wt') 'Windows Terminal session -> wt tab'
        $p = Plan @{ shell = 'powershell'; host = $null } @()
        Assert ($p.terminal -eq 'wt') 'unknown window -> wt tab'
    }
    $p = Plan @{ shell = 'gitbash' } @('-UseShell', 'cmd')
    Assert ($p.shell -eq 'cmd') '-UseShell overrides the saved shell'

    $r = Run @('config', '-ClaudeHome', $home1, '-DataDir', $data, '-UseShell', 'cmd', '-Terminal', 'window')
    Assert ($r.ok -and $r.config.restoreShell -eq 'cmd' -and $r.config.restoreTerminal -eq 'window') 'config stores defaults'
    $p = Plan @{ shell = 'powershell' } @()
    Assert ($p.shell -eq 'cmd' -and $p.terminal -eq 'window') 'saved defaults apply to restore'
    $r = Run @('config', '-ClaudeHome', $home1, '-DataDir', $data, '-Reset')
    Assert ($r.ok -and -not $r.config.restoreShell -and -not $r.config.restoreTerminal) 'config -Reset clears defaults'
    $p = Plan @{ shell = 'powershell' } @()
    Assert ($p.shell -eq 'powershell') 'cleared defaults stop applying'
    Remove-Item (Join-Path $snapDir 'plan.json')

    Write-Host 'transcript fallback'
    $home2 = Join-Path $root 'claude2'
    Write-Transcript $home2 $E $projA @('{"type":"ai-title","aiTitle":"Recent","sessionId":"' + $E + '"}')
    $r = Run @('list', '-ClaudeHome', $home2)
    Assert ($r.ok -and $r.source -eq 'transcripts' -and $r.sessions[0].sessionId -eq $E) 'falls back to recent transcripts without registry'

    if ($Launch) {
        Write-Host 'launch (opens terminal tabs/windows that close themselves)'
        # A fake claude.exe: records "<cwd>|<args>", then ends the shells that were started
        # for it (exit code 0, so mintty and Windows Terminal close the window/tab).
        $marker = Join-Path $root 'marker.txt'
        $fakeDir = Join-Path $root 'fake dir'
        New-Item -ItemType Directory -Force -Path $fakeDir | Out-Null
        $fake = Join-Path $fakeDir 'claude.exe'
        $since = (Get-Date).ToUniversalTime().Ticks
        $src = @"
using System; using System.IO; using System.Management; using System.Runtime.InteropServices; using System.Collections.Generic;
class FakeClaude {
  [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
  [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr h, uint code);
  static void Main(string[] args) {
    var leaked = new List<string>();
    foreach (string v in new[] { "CLAUDE_CODE_CHILD_SESSION", "CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET" })
      if (Environment.GetEnvironmentVariable(v) != null) leaked.Add(v);
    File.AppendAllText(@"$marker", Directory.GetCurrentDirectory() + "|" + string.Join(" ", args) + "|" + string.Join(",", leaked) + "\n");
    var shells = new List<int>();
    int pid = System.Diagnostics.Process.GetCurrentProcess().Id;
    for (int i = 0; i < 8; i++) {
      var q = new ManagementObjectSearcher("SELECT ParentProcessId FROM Win32_Process WHERE ProcessId=" + pid).Get();
      int parent = -1; foreach (ManagementObject o in q) parent = Convert.ToInt32(o["ParentProcessId"]);
      if (parent <= 0) break;
      System.Diagnostics.Process p;
      try { p = System.Diagnostics.Process.GetProcessById(parent); } catch { break; }
      string n = p.ProcessName.ToLowerInvariant();
      if (!(n == "bash" || n == "sh" || n == "cmd" || n == "powershell" || n == "pwsh")) break;
      if (p.StartTime.ToUniversalTime().Ticks < ${since}L) break;
      shells.Add(parent); pid = parent;
    }
    shells.Reverse();
    foreach (int s in shells) TerminateProcess(OpenProcess(1, false, s), 0);
  }
}
"@
        Add-Type -TypeDefinition $src -ReferencedAssemblies System.Management -OutputAssembly $fake -OutputType ConsoleApplication

        $cases = @(@{ shell = 'powershell'; term = 'window' }, @{ shell = 'cmd'; term = 'window' })
        if ($hasWt) { $cases += @(@{ shell = 'powershell'; term = 'wt' }, @{ shell = 'cmd'; term = 'wt' }) }
        if ($realGit) {
            $cases += @{ shell = 'gitbash'; term = 'window' }
            if ($hasWt) { $cases += @{ shell = 'gitbash'; term = 'wt' } }
        }
        # What a Claude Code tool shell passes down; none of it may reach a restored session.
        $env:CLAUDE_CODE_CHILD_SESSION = '1'; $env:CLAUDECODE = '1'
        $env:CLAUDE_CODE_SESSION_ID = 'parent'; $env:CLAUDE_CODE_MESSAGING_SOCKET = 'pipe'
        foreach ($c in $cases) {
            if (Test-Path $marker) { Remove-Item $marker }
            $null = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-ClaudeExe', $fake,
                '-UseShell', $c.shell, '-Terminal', $c.term, '-Ids', $E)
            $deadline = (Get-Date).AddSeconds(25)
            while (-not (Test-Path $marker) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
            Start-Sleep -Milliseconds 300
            $got = if (Test-Path $marker) { (Get-Content $marker -Raw).Trim() } else { '' }
            Assert ($got -eq "$projA|--resume $E|") "real launch: $($c.shell) in $($c.term) resumes in the right folder, no Claude session markers ($got)"
        }
        $after = Get-Content -Raw (Join-Path $snapDir 'snapshot-29990101-000000.json') | ConvertFrom-Json
        Assert ($after.restoredAt -and @($after.restoredSessionIds) -contains $E -and @($after.settledSessionIds) -contains $E) 'real restore marks the snapshot'
    }
} finally {
    Stop-Process -Id $helper.Id -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "$passes passed, $failures failed"
if ($failures -gt 0) { exit 1 }
