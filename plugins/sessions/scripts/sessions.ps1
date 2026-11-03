<#
.SYNOPSIS
  Discover, snapshot and restore live Claude Code sessions (Windows).

.DESCRIPTION
  Subcommands (all print one line of JSON to stdout):
    list       Live Claude Code sessions, read from <ClaudeHome>\sessions\<pid>.json
               (each entry verified against the running process), falling back
               to recently modified transcripts if that registry is unavailable.
    save       Write a snapshot of the sessions named in -Ids to <DataDir>\snapshots.
    snapshots  Summarise stored snapshots, newest first.
    restore    Open one terminal tab per session in a snapshot, each running
               `claude --resume <id>` in the session's folder.

  Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('list', 'save', 'snapshots', 'restore')]
    [string]$Command,

    # Plugin data dir (skills pass ${CLAUDE_PLUGIN_DATA}). Falls back when empty or unsubstituted.
    [string]$DataDir,

    # Session running the skill (skills pass ${CLAUDE_SESSION_ID}); flagged isCurrent in `list`.
    [string]$CurrentSessionId,

    # Comma-separated session ids (save: what to store; restore: optional subset).
    [string]$Ids,

    # Snapshot file name or path for `restore` (default: newest).
    [string]$Snapshot,

    [switch]$IncludeNonInteractive,
    [switch]$DryRun,

    # Snapshots kept after a save; older ones are deleted.
    [int]$Keep = 20,

    # Transcript fallback window for `list` when the live-session registry is unavailable.
    [int]$SinceHours = 12,

    [ValidateSet('auto', 'wt', 'window')]
    [string]$Terminal = 'auto',

    # Overrides, mainly for tests.
    [string]$ClaudeHome,
    [string]$ClaudeExe,
    [string]$Shell
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

$GuidRx = '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if (-not $ClaudeHome) {
    if ($env:CLAUDE_CONFIG_DIR) { $ClaudeHome = $env:CLAUDE_CONFIG_DIR }
    else { $ClaudeHome = Join-Path $env:USERPROFILE '.claude' }
}

# ---------------------------------------------------------------- helpers

function Write-Result($obj) {
    [Console]::Out.WriteLine((ConvertTo-Json -InputObject $obj -Depth 8 -Compress))
}

function Stop-WithError([string]$code, [string]$message) {
    Write-Result ([ordered]@{ ok = $false; error = $code; message = $message })
    exit 1
}

function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

function ConvertFrom-JsonSafe([string]$text) {
    try { return ($text | ConvertFrom-Json) } catch { return $null }
}

# Reads a file another process may be appending to; for big files only the tail.
function Read-SharedLines([string]$path, [long]$maxBytes = 8MB) {
    $fs = New-Object System.IO.FileStream($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read,
        ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
    try {
        $partial = $false
        if ($fs.Length -gt $maxBytes) { [void]$fs.Seek(-$maxBytes, [System.IO.SeekOrigin]::End); $partial = $true }
        $reader = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
        $lines = $reader.ReadToEnd() -split "`r?`n"
    } finally { $fs.Dispose() }
    if ($partial -and $lines.Count -gt 0) { $lines = $lines[1..($lines.Count - 1)] }
    return $lines
}

function Read-JsonFile([string]$path) {
    for ($i = 0; $i -lt 2; $i++) {
        try {
            $text = (Read-SharedLines $path) -join "`n"
            $o = ConvertFrom-JsonSafe $text
            if ($null -ne $o) { return $o }
        } catch { }
        Start-Sleep -Milliseconds 100   # file may be mid-write
    }
    return $null
}

function Write-JsonFile([string]$path, $obj) {
    $tmp = "$path.tmp"
    [System.IO.File]::WriteAllText($tmp, (ConvertTo-Json -InputObject $obj -Depth 8), $Utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $path -Force
}

function Format-Short([string]$text, [int]$max) {
    if (-not $text) { return $null }
    $t = ($text -replace '\s+', ' ').Trim()
    if ($t.Length -gt $max) { $t = $t.Substring(0, $max - 3) + '...' }
    return $t
}

function ConvertTo-PsLiteral([string]$s) { return "'" + ($s -replace "'", "''") + "'" }

function Get-IdList {
    $list = @()
    if ($Ids) {
        foreach ($id in ($Ids -split '[,\s]+')) {
            if (-not $id) { continue }
            if ($id -notmatch $GuidRx) { Stop-WithError 'bad-id' "Not a session id: $id" }
            $list += $id.ToLowerInvariant()
        }
    }
    return , $list
}

function Resolve-DataDir {
    $dir = $DataDir
    $fallback = $false
    if (-not $dir -or $dir -match '\$\{') {
        # Same folder Claude Code assigns as ${CLAUDE_PLUGIN_DATA} for sessions@vslipchenko,
        # so running the script by hand sees the same snapshots.
        $dir = Join-Path $ClaudeHome 'plugins\data\sessions-vslipchenko'
        $fallback = $true
    }
    $snap = Join-Path $dir 'snapshots'
    if (-not (Test-Path -LiteralPath $snap)) { New-Item -ItemType Directory -Path $snap -Force | Out-Null }
    return [ordered]@{ dir = $dir; snapshots = $snap; fallback = $fallback }
}

# ---------------------------------------------------------------- transcripts

$script:ProjectDirs = $null
function Find-Transcript([string]$sessionId) {
    if ($null -eq $script:ProjectDirs) {
        $proj = Join-Path $ClaudeHome 'projects'
        if (Test-Path -LiteralPath $proj) { $script:ProjectDirs = @(Get-ChildItem -LiteralPath $proj -Directory) }
        else { $script:ProjectDirs = @() }
    }
    foreach ($d in $script:ProjectDirs) {
        $p = Join-Path $d.FullName "$sessionId.jsonl"
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}

# Title / last prompt / cwd from a transcript, taking the latest record of each kind.
function Get-TranscriptInfo([string]$path) {
    $info = [ordered]@{ customTitle = $null; aiTitle = $null; lastPrompt = $null; cwd = $null }
    if (-not $path) { return $info }
    try { $lines = Read-SharedLines $path } catch { return $info }
    foreach ($line in $lines) {
        if (-not $line) { continue }
        if ($line.Contains('"type":"custom-title"')) {
            $v = Get-Prop (ConvertFrom-JsonSafe $line) 'customTitle'; if ($v) { $info.customTitle = $v }
        } elseif ($line.Contains('"type":"ai-title"')) {
            $v = Get-Prop (ConvertFrom-JsonSafe $line) 'aiTitle'; if ($v) { $info.aiTitle = $v }
        } elseif ($line.Contains('"type":"last-prompt"')) {
            $v = Get-Prop (ConvertFrom-JsonSafe $line) 'lastPrompt'; if ($v) { $info.lastPrompt = $v }
        }
        if ($line.Contains('"cwd":"')) {
            $m = [regex]::Match($line, '"cwd":("(?:[^"\\]|\\.)*")')
            if ($m.Success) { $v = ConvertFrom-JsonSafe $m.Groups[1].Value; if ($v) { $info.cwd = [string]$v } }
        }
    }
    return $info
}

function New-SessionEntry([string]$sessionId, [string]$cwd, [string]$registryName, $extra) {
    $transcript = Find-Transcript $sessionId
    $ti = Get-TranscriptInfo $transcript
    if (-not $cwd) { $cwd = $ti.cwd }
    $title = $ti.customTitle
    if (-not $title) { $title = $ti.aiTitle }
    if (-not $title) { $title = $registryName }
    if (-not $title -and $cwd) { $title = Split-Path -Leaf $cwd }
    $e = [ordered]@{
        sessionId  = $sessionId
        cwd        = $cwd
        title      = Format-Short $title 60
        lastPrompt = Format-Short $ti.lastPrompt 100
        transcript = [bool]$transcript
        isCurrent  = ($CurrentSessionId -and $sessionId -eq $CurrentSessionId.ToLowerInvariant())
    }
    foreach ($k in $extra.Keys) { $e[$k] = $extra[$k] }
    return $e
}

# ---------------------------------------------------------------- discovery

function Test-ProcessLive($procId, $procStart) {
    $p = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    if ($procStart) {
        # procStart is the process start time as a Windows FILETIME; a mismatch means the PID was reused.
        try { return ($p.StartTime.ToFileTimeUtc().ToString() -eq [string]$procStart) } catch { }
    }
    return ($p.ProcessName -match '^(claude|node|bun)')
}

function Get-LiveSessions([bool]$includeNonInteractive) {
    $sessions = New-Object System.Collections.ArrayList
    $seen = @{}
    $hidden = 0
    $usable = 0
    $regDir = Join-Path $ClaudeHome 'sessions'

    if (Test-Path -LiteralPath $regDir) {
        foreach ($f in @(Get-ChildItem -LiteralPath $regDir -Filter '*.json' -File)) {
            $o = Read-JsonFile $f.FullName
            $sid = [string](Get-Prop $o 'sessionId')
            $cwd = Get-Prop $o 'cwd'
            $procId = Get-Prop $o 'pid'
            if (-not $sid -or -not $cwd -or -not $procId -or $sid -notmatch $GuidRx) { continue }
            $usable++
            if (-not (Test-ProcessLive $procId (Get-Prop $o 'procStart'))) { continue }
            $kind = Get-Prop $o 'kind'
            if ($kind -and $kind -ne 'interactive' -and -not $includeNonInteractive) { $hidden++; continue }
            $sid = $sid.ToLowerInvariant()
            if ($seen.ContainsKey($sid)) { continue }
            $seen[$sid] = $true
            $started = $null
            $ms = Get-Prop $o 'startedAt'
            if ($ms) { $started = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$ms).ToString('o') }
            [void]$sessions.Add((New-SessionEntry $sid $cwd (Get-Prop $o 'name') ([ordered]@{
                pid = [int]$procId; kind = $kind; status = (Get-Prop $o 'status'); startedAt = $started
            })))
        }
    }

    $source = 'registry'
    if ($usable -eq 0) {
        # Registry missing or in an unknown format: fall back to recently written transcripts.
        $source = 'transcripts'
        $proj = Join-Path $ClaudeHome 'projects'
        $cutoff = (Get-Date).AddHours(-$SinceHours)
        if (Test-Path -LiteralPath $proj) {
            $files = @(Get-ChildItem -LiteralPath $proj -Directory | ForEach-Object {
                    Get-ChildItem -LiteralPath $_.FullName -Filter '*.jsonl' -File
                } | Where-Object { $_.LastWriteTime -ge $cutoff -and $_.BaseName -match $GuidRx } |
                Sort-Object LastWriteTime -Descending)
            foreach ($f in $files) {
                $sid = $f.BaseName.ToLowerInvariant()
                if ($seen.ContainsKey($sid)) { continue }
                $seen[$sid] = $true
                $e = New-SessionEntry $sid $null $null ([ordered]@{ lastActive = $f.LastWriteTime.ToUniversalTime().ToString('o') })
                if ($e.cwd) { [void]$sessions.Add($e) }
            }
        }
    }

    # Newest first, with the session running the skill pinned to the top.
    $sorted = @($sessions | Sort-Object -Descending -Property @{ Expression = {
                if ($_.Contains('startedAt')) { $_.startedAt } else { $_.lastActive } } })
    $current = @($sorted | Where-Object { $_.isCurrent })
    $others = @($sorted | Where-Object { -not $_.isCurrent })
    return [ordered]@{ source = $source; sessions = @($current + $others); hiddenNonInteractive = $hidden }
}

# ---------------------------------------------------------------- commands

function Invoke-List {
    $r = Get-LiveSessions ([bool]$IncludeNonInteractive)
    Write-Result ([ordered]@{
            ok                   = $true
            source               = $r.source
            sessions             = $r.sessions
            hiddenNonInteractive = $r.hiddenNonInteractive
        })
}

function Invoke-Save {
    $idList = Get-IdList
    if ($idList.Count -eq 0) { Stop-WithError 'no-ids' 'Pass the session ids to save with -Ids.' }
    $data = Resolve-DataDir
    $live = Get-LiveSessions $true
    $byId = @{}
    foreach ($s in $live.sessions) { $byId[$s.sessionId] = $s }

    $saved = @()
    $missing = @()
    foreach ($id in $idList) {
        $e = $null
        if ($byId.ContainsKey($id)) { $e = $byId[$id] }
        else {
            # Ended between `list` and `save`: still resumable if its transcript exists.
            $t = New-SessionEntry $id $null $null @{}
            if ($t.transcript -and $t.cwd) { $e = $t }
        }
        if ($e) {
            $saved += [ordered]@{ sessionId = $e.sessionId; cwd = $e.cwd; title = $e.title; lastPrompt = $e.lastPrompt }
        } else { $missing += $id }
    }
    if ($saved.Count -eq 0) { Stop-WithError 'nothing-saved' 'None of the given sessions could be found.' }

    $now = Get-Date
    $base = 'snapshot-' + $now.ToString('yyyyMMdd-HHmmss')
    $path = Join-Path $data.snapshots "$base.json"
    $n = 2
    while (Test-Path -LiteralPath $path) { $path = Join-Path $data.snapshots "$base-$n.json"; $n++ }
    Write-JsonFile $path ([ordered]@{
            version            = 1
            createdAt          = $now.ToUniversalTime().ToString('o')
            restoredAt         = $null
            restoredSessionIds = @()
            sessions           = $saved
        })

    $pruned = 0
    if ($Keep -gt 0) {
        $old = @(Get-ChildItem -LiteralPath $data.snapshots -Filter 'snapshot-*.json' -File |
            Sort-Object Name -Descending | Select-Object -Skip $Keep)
        foreach ($f in $old) { Remove-Item -LiteralPath $f.FullName -Force; $pruned++ }
    }

    Write-Result ([ordered]@{
            ok              = $true
            snapshot        = $path
            dataDir         = $data.dir
            dataDirFallback = $data.fallback
            saved           = $saved
            missing         = $missing
            pruned          = $pruned
        })
}

function Get-SnapshotFiles($data) {
    return @(Get-ChildItem -LiteralPath $data.snapshots -Filter 'snapshot-*.json' -File | Sort-Object Name -Descending)
}

function Invoke-Snapshots {
    $data = Resolve-DataDir
    $list = @()
    foreach ($f in (Get-SnapshotFiles $data)) {
        $o = Read-JsonFile $f.FullName
        if (-not $o) { continue }
        $items = @(Get-Prop $o 'sessions')
        $list += [ordered]@{
            file       = $f.Name
            createdAt  = Get-Prop $o 'createdAt'
            restoredAt = Get-Prop $o 'restoredAt'
            count      = $items.Count
            sessions   = @($items | ForEach-Object { [ordered]@{
                        sessionId = (Get-Prop $_ 'sessionId'); title = (Get-Prop $_ 'title'); cwd = (Get-Prop $_ 'cwd')
                        lastPrompt = (Get-Prop $_ 'lastPrompt') } })
        }
    }
    Write-Result ([ordered]@{ ok = $true; dataDir = $data.dir; snapshots = $list })
}

function Resolve-Exe([string]$override, [string[]]$names) {
    if ($override) { return $override }
    foreach ($n in $names) {
        $c = Get-Command $n -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) { return $c.Source }
    }
    return $null
}

function Invoke-Restore {
    $data = Resolve-DataDir

    if ($Snapshot) {
        if ([System.IO.Path]::IsPathRooted($Snapshot)) { $snapPath = $Snapshot }
        else {
            $name = $Snapshot
            if (-not $name.EndsWith('.json')) { $name += '.json' }
            $snapPath = Join-Path $data.snapshots $name
        }
        if (-not (Test-Path -LiteralPath $snapPath)) { Stop-WithError 'snapshot-not-found' "No snapshot at $snapPath" }
    } else {
        $files = @(Get-SnapshotFiles $data)
        if ($files.Count -eq 0) { Stop-WithError 'no-snapshots' 'No saved snapshots yet.' }
        $snapPath = $files[0].FullName
    }
    $snap = Read-JsonFile $snapPath
    if (-not $snap) { Stop-WithError 'bad-snapshot' "Could not read $snapPath" }

    $idList = Get-IdList
    $items = @(Get-Prop $snap 'sessions')
    if ($idList.Count -gt 0) { $items = @($items | Where-Object { $idList -contains ([string](Get-Prop $_ 'sessionId')).ToLowerInvariant() }) }

    $claude = Resolve-Exe $ClaudeExe @('claude')
    if (-not $claude) { Stop-WithError 'claude-not-found' 'The claude executable is not on PATH.' }
    $shellExe = Resolve-Exe $Shell @('pwsh', 'powershell')
    $mode = $Terminal
    if ($mode -eq 'auto') {
        if (Get-Command wt -ErrorAction SilentlyContinue) { $mode = 'wt' } else { $mode = 'window' }
    }

    $live = Get-LiveSessions $true
    $liveIds = @{}
    if ($live.source -eq 'registry') { foreach ($s in $live.sessions) { $liveIds[$s.sessionId] = $true } }

    $launch = @()
    $skipped = @()
    foreach ($it in $items) {
        $sid = ([string](Get-Prop $it 'sessionId')).ToLowerInvariant()
        $cwd = [string](Get-Prop $it 'cwd')
        $title = [string](Get-Prop $it 'title')
        $row = [ordered]@{ sessionId = $sid; title = $title; cwd = $cwd }
        $reason = $null
        if ($sid -notmatch $GuidRx) { $reason = 'bad-id' }
        elseif ($liveIds.ContainsKey($sid)) { $reason = 'already-running' }
        elseif (-not $cwd -or -not (Test-Path -LiteralPath $cwd -PathType Container)) { $reason = 'folder-missing' }
        elseif (-not (Find-Transcript $sid)) { $reason = 'transcript-missing' }
        if ($reason) { $row.reason = $reason; $skipped += $row; continue }

        $row.command = "Set-Location -LiteralPath $(ConvertTo-PsLiteral $cwd); & $(ConvertTo-PsLiteral $claude) --resume $sid"
        $launch += $row
    }

    $tabTitle = {
        param($t)
        $t = ($t -replace '["`;]', '').Trim().TrimEnd('\')
        if (-not $t) { $t = 'claude' }
        if ($t.Length -gt 40) { $t = $t.Substring(0, 40) }
        return $t
    }

    if (-not $DryRun -and $launch.Count -gt 0) {
        if ($mode -eq 'wt') {
            # One window per 10 tabs keeps the command line well under the 32K limit.
            for ($i = 0; $i -lt $launch.Count; $i += 10) {
                $chunk = @($launch[$i..([Math]::Min($i + 9, $launch.Count - 1))])
                $tabs = @($chunk | ForEach-Object {
                        $enc = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($_.command))
                        'new-tab --title "{0}" "{1}" -NoExit -EncodedCommand {2}' -f (& $tabTitle $_.title), $shellExe, $enc
                    })
                Start-Process -FilePath 'wt.exe' -ArgumentList ('-w new ' + ($tabs -join ' ; '))
            }
        } else {
            foreach ($l in $launch) {
                $enc = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($l.command))
                Start-Process -FilePath $shellExe -ArgumentList @('-NoExit', '-EncodedCommand', $enc)
            }
        }

        $restored = @(@(Get-Prop $snap 'restoredSessionIds') | Where-Object { $_ }) + @($launch | ForEach-Object { $_.sessionId })
        Write-JsonFile $snapPath ([ordered]@{
                version            = Get-Prop $snap 'version'
                createdAt          = Get-Prop $snap 'createdAt'
                restoredAt         = (Get-Date).ToUniversalTime().ToString('o')
                restoredSessionIds = @($restored | Select-Object -Unique)
                sessions           = @(Get-Prop $snap 'sessions')
            })
    }

    Write-Result ([ordered]@{
            ok        = $true
            snapshot  = $snapPath
            terminal  = $mode
            dryRun    = [bool]$DryRun
            launched  = $launch
            skipped   = $skipped
        })
}

try {
    switch ($Command) {
        'list' { Invoke-List }
        'save' { Invoke-Save }
        'snapshots' { Invoke-Snapshots }
        'restore' { Invoke-Restore }
    }
} catch {
    Stop-WithError 'unexpected' $_.Exception.Message
}
