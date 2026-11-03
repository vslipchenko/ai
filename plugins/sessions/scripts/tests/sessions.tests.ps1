<#
  Self-contained tests for sessions.ps1 (no Pester needed).
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\sessions.tests.ps1 [-Launch]
  -Launch also runs a real end-to-end restore that opens (and auto-closes) terminal tabs.
#>
param([switch]$Launch)

$ErrorActionPreference = 'Stop'
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

function Write-Registry([string]$home_, [int]$procId, [string]$sid, [string]$cwd, [string]$procStart, [string]$kind) {
    $o = [ordered]@{ pid = $procId; sessionId = $sid; cwd = $cwd; startedAt = 1793722012466; procStart = $procStart; kind = $kind; name = "reg-$($sid.Substring(0,4))"; status = 'idle' }
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

    $pr = Join-Path $root 'prune'
    1..3 | ForEach-Object { $null = Run @('save', '-ClaudeHome', $home1, '-DataDir', $pr, '-Ids', $A, '-Keep', '2') }
    Assert (@(Get-ChildItem (Join-Path $pr 'snapshots') -Filter 'snapshot-*.json').Count -eq 2) 'keeps only -Keep newest snapshots'

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

    Write-Host 'transcript fallback'
    $home2 = Join-Path $root 'claude2'
    Write-Transcript $home2 $E $projA @('{"type":"ai-title","aiTitle":"Recent","sessionId":"' + $E + '"}')
    $r = Run @('list', '-ClaudeHome', $home2)
    Assert ($r.ok -and $r.source -eq 'transcripts' -and $r.sessions[0].sessionId -eq $E) 'falls back to recent transcripts without registry'

    if ($Launch) {
        Write-Host 'launch (opens terminal tabs that close themselves)'
        $marker = Join-Path $root 'marker.txt'
        $fake = Join-Path $root 'fake claude.ps1'
        Write-Utf8 $fake ("Add-Content -LiteralPath '$marker' -Value (`"`$PWD|`" + (`$args -join ' ')); [Environment]::Exit(0)")
        foreach ($mode in @('wt', 'window')) {
            if ($mode -eq 'wt' -and -not (Get-Command wt -ErrorAction SilentlyContinue)) { continue }
            if (Test-Path $marker) { Remove-Item $marker }
            $null = Run @('restore', '-ClaudeHome', $home1, '-DataDir', $data, '-ClaudeExe', $fake, '-Terminal', $mode, '-Shell', 'powershell.exe')
            $deadline = (Get-Date).AddSeconds(20)
            while (-not (Test-Path $marker) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
            $got = if (Test-Path $marker) { (Get-Content $marker -Raw).Trim() } else { '' }
            Assert ($got -eq "$projA|--resume $E") "real launch via $mode resumes in the right folder"
        }
        $after = Get-Content -Raw (Join-Path $snapDir 'snapshot-29990101-000000.json') | ConvertFrom-Json
        Assert ($after.restoredAt -and @($after.restoredSessionIds) -contains $E) 'real restore marks the snapshot'
    }
} finally {
    Stop-Process -Id $helper.Id -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "$passes passed, $failures failed"
if ($failures -gt 0) { exit 1 }
