<#
.SYNOPSIS
  Discover, snapshot and restore live Claude Code sessions (Windows).

.DESCRIPTION
  Subcommands (all print one line of JSON to stdout):
    list       Live Claude Code sessions, read from <ClaudeHome>\sessions\<pid>.json
               (each entry verified against the running process), falling back
               to recently modified transcripts if that registry is unavailable.
               Each live session also records the shell it was started from
               (gitbash / pwsh / powershell / cmd) and, when detectable, its window
               program (wt / console / mintty / vscode / jetbrains).
    save       Write a snapshot of the sessions named in -Ids to <DataDir>\snapshots,
               replacing the previous one. Refuses (error unrestored-snapshot) while
               the previous one has sessions not yet restored, unless -Force.
    snapshots  Summarise the stored snapshot (normally just one).
    restore    Reopen each session of a snapshot with `claude --resume <id>` in its
               folder, in the shell it ran in. If that shell is missing, falls back
               to PowerShell 7, Windows PowerShell, then cmd.
    config     Show or set the default restore shell/terminal (-UseShell, -Terminal, -Reset).
    manage     -Enable: start a new snapshot with the sessions in -Ids (may be empty) and
               turn on automatic tracking; -Disable: turn it off (the snapshot stays);
               neither: status. Refuses to replace a snapshot with unrestored
               sessions unless -Force.
    track      Hook entry point (SessionStart / SessionEnd JSON on stdin): while
               tracking is on, adds or updates the session, or drops it when it was
               exited on purpose (/exit, logout, /clear, /resume to another session).
    clear      Delete the saved snapshot (the list of sessions, not the conversations).
               Refuses (unrestored-snapshot) while it has sessions not yet restored,
               unless -Force; -IncludeConfig also deletes the restore defaults.

  Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('list', 'save', 'snapshots', 'restore', 'config', 'clear', 'manage', 'track')]
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

    # save: replace the snapshot even if it has sessions that were never restored.
    [switch]$Force,

    # Transcript fallback window for `list` when the live-session registry is unavailable.
    [int]$SinceHours = 12,

    # restore: shell / terminal to use instead of what each session ran in.
    # config: the saved default for these ('auto' clears it).
    [ValidateSet('', 'auto', 'gitbash', 'pwsh', 'powershell', 'cmd')]
    [string]$UseShell = '',
    [ValidateSet('', 'auto', 'wt', 'window')]
    [string]$Terminal = '',
    [switch]$Reset,

    # clear: also delete the saved restore defaults (config.json).
    [switch]$IncludeConfig,

    # manage: turn automatic tracking on (with -Ids as the starting list) or off; neither = status.
    [switch]$Enable,
    [switch]$Disable,

    # Overrides, mainly for tests.
    [string]$ClaudePid,
    [string]$ClaudeHome,
    [string]$ClaudeExe,
    [string]$PowerShellExe,
    [string]$GitRoot
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

function Stop-WithError([string]$code, [string]$message, $extra = @{}) {
    $r = [ordered]@{ ok = $false; error = $code; message = $message }
    foreach ($k in $extra.Keys) { $r[$k] = $extra[$k] }
    Write-Result $r
    exit 1
}

function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    if ($obj -is [System.Collections.IDictionary]) {
        if ($obj.Contains($name)) { return $obj[$name] }
        return $null
    }
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

# A session someone works in at a terminal: entrypoint "cli" (or none, in older files).
# Everything else belongs to another app and can't be reopened with `claude --resume` in a
# terminal — Claude Desktop ("claude-desktop", Cowork "local-agent"), the VS Code
# extension panel ("claude-vscode"), headless runs ("sdk-…", which report kind
# "interactive" too), remote and integration sessions.
function Test-InteractiveEntry($o) {
    $kind = [string](Get-Prop $o 'kind')
    $entry = [string](Get-Prop $o 'entrypoint')
    if ($kind -and $kind -ne 'interactive') { return $false }
    if ($entry -and $entry -ne 'cli') { return $false }
    return $true
}

# Which app a non-terminal session belongs to, for "N sessions from … left out".
function Get-EntrySource($o) {
    $entry = [string](Get-Prop $o 'entrypoint')
    if ($entry -in @('claude-desktop', 'claude-desktop-3p', 'remote_desktop')) { return 'Claude Desktop' }
    if ($entry -in @('local-agent', 'local_agent', 'remote_cowork')) { return 'Cowork (Claude Desktop)' }
    if ($entry -eq 'claude-vscode') { return 'VS Code extension' }
    if ($entry -like 'sdk*') { return 'headless / SDK' }
    if ($entry) { return "other ($entry)" }
    return 'background'
}

function Test-ProcessLive($procId, $procStart) {
    $p = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
    if (-not $p) { return $false }
    if ($procStart) {
        # procStart is the process start time as a Windows FILETIME; a mismatch means the PID was reused.
        try { return ($p.StartTime.ToFileTimeUtc().ToString() -eq [string]$procStart) } catch { }
    }
    return ($p.ProcessName -match '^(claude|node|bun)')
}

$script:ProcMap = $null
function Get-ProcMap {
    if ($null -eq $script:ProcMap) {
        $script:ProcMap = @{}
        foreach ($p in @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name, ExecutablePath)) {
            $script:ProcMap[[int]$p.ProcessId] = $p
        }
    }
    return $script:ProcMap
}

# Walks a Claude process's ancestors: the nearest shell is what it was started
# from; a window program further up is where it was shown. Either may be $null
# (e.g. Git Bash re-launches bash, so its chain usually stops before mintty).
function Get-LaunchInfo([int]$procId) {
    $map = Get-ProcMap
    $info = [ordered]@{ shell = $null; shellPath = $null; host = $null }
    $seen = @{}
    $cur = $map[$procId]
    for ($i = 0; $i -lt 12 -and $cur; $i++) {
        $parentId = [int]$cur.ParentProcessId
        if ($seen.ContainsKey($parentId)) { break }
        $seen[$parentId] = $true
        $cur = $map[$parentId]
        if (-not $cur) { break }
        $name = ([string]$cur.Name).ToLowerInvariant()
        $path = [string]$cur.ExecutablePath
        if (-not $info.shell) {
            $shell = $null
            switch -Regex ($name) {
                '^(bash|sh)\.exe$' { if ($path -match '\\Git\\') { $shell = 'gitbash' } }
                '^pwsh\.exe$' { $shell = 'pwsh' }
                '^powershell\.exe$' { $shell = 'powershell' }
                '^cmd\.exe$' { $shell = 'cmd' }
            }
            if ($shell) {
                $info.shell = $shell; $info.shellPath = $path
                # A shell in a standalone console window (conhost) owns a visible window;
                # inside Windows Terminal, an editor or mintty (pseudo-console) it does not.
                # Checked first: such a window may have been started from a Windows Terminal tab.
                if ($shell -ne 'gitbash') {
                    $sp = Get-Process -Id $parentId -ErrorAction SilentlyContinue
                    if ($sp -and $sp.MainWindowHandle -ne [IntPtr]::Zero) { $info.host = 'console'; break }
                }
            }
            continue
        }
        $hostName = $null
        switch -Regex ($name) {
            '^windowsterminal\.exe$' { $hostName = 'wt' }
            '^mintty\.exe$' { $hostName = 'mintty' }
            '^(code|code - insiders|cursor|windsurf)\.exe$' { $hostName = 'vscode' }
            '^(idea|webstorm|pycharm|rider|goland|phpstorm|clion|rubymine|datagrip)64\.exe$' { $hostName = 'jetbrains' }
            '^explorer\.exe$' { break }
        }
        if ($hostName) { $info.host = $hostName; break }
        if ($name -eq 'explorer.exe') { break }
    }
    return $info
}

function Get-LiveSessions([bool]$includeNonInteractive) {
    $sessions = New-Object System.Collections.ArrayList
    $seen = @{}
    $hidden = 0
    $hiddenFrom = [ordered]@{}
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
            if (-not (Test-InteractiveEntry $o) -and -not $includeNonInteractive) {
                $hidden++
                $src = Get-EntrySource $o
                if ($hiddenFrom.Contains($src)) { $hiddenFrom[$src]++ } else { $hiddenFrom[$src] = 1 }
                continue
            }
            $sid = $sid.ToLowerInvariant()
            if ($seen.ContainsKey($sid)) { continue }
            $seen[$sid] = $true
            $started = $null
            $ms = Get-Prop $o 'startedAt'
            if ($ms) { $started = [DateTimeOffset]::FromUnixTimeMilliseconds([long]$ms).ToString('o') }
            $launch = Get-LaunchInfo ([int]$procId)
            [void]$sessions.Add((New-SessionEntry $sid $cwd (Get-Prop $o 'name') ([ordered]@{
                pid = [int]$procId; kind = $kind; status = (Get-Prop $o 'status'); startedAt = $started
                shell = $launch.shell; shellPath = $launch.shellPath; host = $launch.host
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

    # In the order they were opened (oldest first), like the user's tabs and windows.
    $sorted = Sort-ByOpened @($sessions) { param($s) if ($s.Contains('startedAt')) { $s.startedAt } else { $s.lastActive } }
    return [ordered]@{ source = $source; sessions = $sorted; hiddenNonInteractive = $hidden; hiddenFrom = $hiddenFrom }
}

# Stable sort, oldest first, by an ISO-8601 time; entries without one keep their
# relative order after the dated ones. (Sort-Object isn't stable in PowerShell 5.1.)
function Sort-ByOpened($items, [scriptblock]$timeOf) {
    $rows = @()
    $i = 0
    foreach ($it in $items) {
        $t = & $timeOf $it
        $key = 1
        $when = [DateTimeOffset]::MaxValue
        if ($t -is [datetime]) { $when = [DateTimeOffset]$t; $key = 0 }   # PowerShell 7's ConvertFrom-Json parses dates
        elseif ($t) {
            try { $when = [DateTimeOffset]::Parse([string]$t, [Globalization.CultureInfo]::InvariantCulture); $key = 0 } catch { }
        }
        $rows += [pscustomobject]@{ item = $it; key = $key; when = $when; index = $i }
        $i++
    }
    return , @($rows | Sort-Object key, when, index | ForEach-Object { $_.item })
}

# ---------------------------------------------------------------- commands

function Get-SnapshotFiles($data) {
    return @(Get-ChildItem -LiteralPath $data.snapshots -Filter 'snapshot-*.json' -File | Sort-Object Name -Descending)
}

# Sessions of a snapshot that a restore hasn't dealt with yet. A session counts as
# settled once restore opened it or found it can never be opened (already running,
# folder or conversation gone). Snapshots from before settledSessionIds existed
# count as fully settled once restoredAt is set.
function Get-PendingSessions($snap) {
    $items = @(Get-Prop $snap 'sessions')
    $settledProp = $snap.PSObject.Properties['settledSessionIds']
    if (-not $settledProp) {
        if (Get-Prop $snap 'restoredAt') { return , @() }
        return , $items
    }
    $settled = @($settledProp.Value | Where-Object { $_ } | ForEach-Object { ([string]$_).ToLowerInvariant() })
    return , @($items | Where-Object { $settled -notcontains ([string](Get-Prop $_ 'sessionId')).ToLowerInvariant() })
}

# The snapshot that would be replaced, if it still holds sessions not yet restored.
function Get-PendingSnapshot($data) {
    foreach ($f in (Get-SnapshotFiles $data)) {
        $o = Read-JsonFile $f.FullName
        if (-not $o) { continue }
        $pending = Get-PendingSessions $o
        if ($pending.Count -eq 0) { continue }
        return [ordered]@{
            file      = $f.Name
            createdAt = Get-Prop $o 'createdAt'
            count     = @(Get-Prop $o 'sessions').Count
            pending   = @($pending | ForEach-Object { [ordered]@{
                        sessionId = (Get-Prop $_ 'sessionId'); title = (Get-Prop $_ 'title'); cwd = (Get-Prop $_ 'cwd') } })
        }
    }
    return $null
}

function Test-Tracking($data) { return (Test-Path -LiteralPath (Join-Path $data.dir 'tracking')) }

# Serialises read-modify-write of the snapshot between this script, hooks of other
# sessions (several can start at once during a restore) and restore itself.
function Enter-SnapshotLock($data) {
    $path = Join-Path $data.dir 'snapshot.lock'
    for ($i = 0; $i -lt 100; $i++) {
        try {
            $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
            $fs.Dispose()
            return $path
        } catch {
            # A lock left behind by a killed process.
            try {
                $age = (Get-Date) - (Get-Item -LiteralPath $path -ErrorAction Stop).LastWriteTime
                if ($age.TotalSeconds -gt 30) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
            } catch { }
            Start-Sleep -Milliseconds 100
        }
    }
    Stop-WithError 'locked' 'The snapshot is busy (another session is updating it); try again.'
}

function Exit-SnapshotLock($path) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }

function Invoke-List {
    $r = Get-LiveSessions ([bool]$IncludeNonInteractive)
    $data = Resolve-DataDir
    Write-Result ([ordered]@{
            ok                   = $true
            source               = $r.source
            sessions             = $r.sessions
            hiddenNonInteractive = $r.hiddenNonInteractive
            hiddenFrom           = $r.hiddenFrom
            pendingSnapshot      = Get-PendingSnapshot $data
            managing             = (Test-Tracking $data)
        })
}

# Snapshot entries for the given ids (live, or ended but still resumable), in opening order.
function Get-SnapshotEntries($idList) {
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
        if ($e) { $saved += (ConvertTo-SnapshotEntry $e) } else { $missing += $id }
    }
    # Stored in the order the sessions were opened, whatever order they were picked in.
    $saved = Sort-ByOpened $saved { param($s) $s.startedAt }
    return [ordered]@{ saved = $saved; missing = $missing }
}

function ConvertTo-SnapshotEntry($e) {
    $s = [ordered]@{ sessionId = $e.sessionId; cwd = $e.cwd; title = $e.title; lastPrompt = $e.lastPrompt
        shell = $null; shellPath = $null; host = $null; startedAt = $null }
    foreach ($k in @('shell', 'shellPath', 'host', 'startedAt')) { if ($e.Contains($k)) { $s[$k] = $e[$k] } }
    return $s
}

# Writes a new snapshot (the only one kept) and removes all others.
function Write-NewSnapshot($data, $saved, [bool]$managed) {
    $now = Get-Date
    $path = Join-Path $data.snapshots ('snapshot-' + $now.ToString('yyyyMMdd-HHmmss') + '.json')
    $snap = [ordered]@{
        version            = 1
        createdAt          = $now.ToUniversalTime().ToString('o')
        restoredAt         = $null
        restoredSessionIds = @()
        settledSessionIds  = @()
        sessions           = @($saved)
    }
    if ($managed) { $snap.managed = $true }
    $replaced = 0
    if (Test-Path -LiteralPath $path) { $replaced = 1 }   # an older snapshot from the same second
    Write-JsonFile $path $snap
    foreach ($f in (Get-SnapshotFiles $data)) {
        if ($f.FullName -ne $path) { Remove-Item -LiteralPath $f.FullName -Force; $replaced++ }
    }
    return [ordered]@{ path = $path; replaced = $replaced }
}

function Assert-NoPendingSnapshot($data, [string]$verb) {
    # Never replace a snapshot with sessions still waiting to be restored unless told to.
    $pendingSnap = Get-PendingSnapshot $data
    if ($pendingSnap -and -not $Force) {
        Stop-WithError 'unrestored-snapshot' "The snapshot from $($pendingSnap.createdAt) still has $($pendingSnap.pending.Count) session(s) that were never restored. Pass -Force to $verb it anyway." @{ pendingSnapshot = $pendingSnap }
    }
}

function Invoke-Save {
    $idList = Get-IdList
    if ($idList.Count -eq 0) { Stop-WithError 'no-ids' 'Pass the session ids to save with -Ids.' }
    $data = Resolve-DataDir
    if (Test-Tracking $data) {
        Stop-WithError 'managing' 'Sessions are being managed (saved automatically). Turn that off first (manage -Disable) to save a list by hand.'
    }
    $entries = Get-SnapshotEntries $idList
    if ($entries.saved.Count -eq 0) { Stop-WithError 'nothing-saved' 'None of the given sessions could be found.' }
    Assert-NoPendingSnapshot $data 'replace'

    $lock = Enter-SnapshotLock $data
    try { $w = Write-NewSnapshot $data $entries.saved $false } finally { Exit-SnapshotLock $lock }
    Write-Result ([ordered]@{
            ok              = $true
            snapshot        = $w.path
            dataDir         = $data.dir
            dataDirFallback = $data.fallback
            saved           = $entries.saved
            missing         = $entries.missing
            replaced        = $w.replaced
        })
}

function Get-SnapshotSummary($data) {
    $files = @(Get-SnapshotFiles $data)
    if ($files.Count -eq 0) { return $null }
    $o = Read-JsonFile $files[0].FullName
    if (-not $o) { return $null }
    $items = @(Get-Prop $o 'sessions')
    return [ordered]@{
        file      = $files[0].Name
        createdAt = Get-Prop $o 'createdAt'
        managed   = [bool](Get-Prop $o 'managed')
        count     = $items.Count
        sessions  = @($items | ForEach-Object { [ordered]@{ sessionId = (Get-Prop $_ 'sessionId'); title = (Get-Prop $_ 'title'); cwd = (Get-Prop $_ 'cwd') } })
    }
}

function Invoke-Manage {
    $data = Resolve-DataDir
    $flag = Join-Path $data.dir 'tracking'
    if ($Enable -and $Disable) { Stop-WithError 'bad-args' 'Pass -Enable or -Disable, not both.' }
    if ($Enable) {
        $idList = Get-IdList
        $entries = [ordered]@{ saved = @(); missing = @() }
        if ($idList.Count -gt 0) { $entries = Get-SnapshotEntries $idList }
        # Re-enabling while already managing keeps going with a fresh list; otherwise protect unrestored work.
        if (-not (Test-Tracking $data)) { Assert-NoPendingSnapshot $data 'replace' }
        $lock = Enter-SnapshotLock $data
        try {
            $w = Write-NewSnapshot $data $entries.saved $true
            [System.IO.File]::WriteAllText($flag, (Get-Date).ToUniversalTime().ToString('o'), $Utf8NoBom)
        } finally { Exit-SnapshotLock $lock }
        Write-Result ([ordered]@{ ok = $true; managing = $true; snapshot = $w.path; saved = $entries.saved
                missing = $entries.missing; replaced = $w.replaced; dataDir = $data.dir })
        return
    }
    if ($Disable) {
        $was = Test-Path -LiteralPath $flag
        Remove-Item -LiteralPath $flag -Force -ErrorAction SilentlyContinue
        Write-Result ([ordered]@{ ok = $true; managing = $false; wasManaging = $was; snapshot = (Get-SnapshotSummary $data) })
        return
    }
    $since = $null
    if (Test-Path -LiteralPath $flag) { $since = ([System.IO.File]::ReadAllText($flag)).Trim() }
    Write-Result ([ordered]@{ ok = $true; managing = [bool]$since; since = $since; snapshot = (Get-SnapshotSummary $data) })
}

# The list without one id, always as an array (an empty array passed through the
# pipeline would come back as $null and be written as {} in PowerShell 5.1).
function Remove-IdFromList($list, [string]$sid) {
    $kept = New-Object System.Collections.ArrayList
    foreach ($x in @($list)) { if ($x -and ([string]$x).ToLowerInvariant() -ne $sid) { [void]$kept.Add([string]$x) } }
    return , $kept.ToArray()
}

# Hook entry point. Never fails loudly: a hook must not disturb the session.
function Invoke-Track {
    $data = Resolve-DataDir
    if (-not (Test-Tracking $data)) { Write-Result ([ordered]@{ ok = $true; tracked = $false; why = 'not-managing' }); return }
    $raw = [Console]::In.ReadToEnd()
    $ev = ConvertFrom-JsonSafe $raw
    $sid = ([string](Get-Prop $ev 'session_id')).ToLowerInvariant()
    $event = [string](Get-Prop $ev 'hook_event_name')
    if ($sid -notmatch $GuidRx) { Write-Result ([ordered]@{ ok = $true; tracked = $false; why = 'no-session' }); return }

    $action = $null
    $entry = $null
    if ($event -eq 'SessionStart') {
        $procId = $ClaudePid
        if (-not $procId) { $procId = $env:CLAUDE_PID }
        $reg = $null
        if ($procId) { $reg = Read-JsonFile (Join-Path $ClaudeHome "sessions\$procId.json") }
        if ($reg -and -not (Test-InteractiveEntry $reg)) {
            Write-Result ([ordered]@{ ok = $true; tracked = $false; why = 'non-interactive' }); return
        }
        $cwd = [string](Get-Prop $ev 'cwd')
        if (-not $cwd -and $reg) { $cwd = [string](Get-Prop $reg 'cwd') }
        $extra = [ordered]@{ startedAt = (Get-Date).ToUniversalTime().ToString('o') }
        if ($reg -and (Get-Prop $reg 'startedAt')) { $extra.startedAt = [DateTimeOffset]::FromUnixTimeMilliseconds([long](Get-Prop $reg 'startedAt')).ToString('o') }
        if ($procId) {
            $li = Get-LaunchInfo ([int]$procId)
            $extra.shell = $li.shell; $extra.shellPath = $li.shellPath; $extra.host = $li.host
        }
        $name = $null
        if ($reg) { $name = Get-Prop $reg 'name' }
        $entry = ConvertTo-SnapshotEntry (New-SessionEntry $sid $cwd $name $extra)
        # Which process runs it: a process that later starts another session (e.g. after
        # switching renderer) replaces its earlier entry, which never sends a SessionEnd.
        if ($procId) {
            $entry.pid = [int]$procId
            $entry.procStart = [string](Get-Prop $reg 'procStart')
        }
        $action = 'upsert'
    } elseif ($event -eq 'SessionEnd') {
        # Exited on purpose (or replaced by /clear or /resume): drop it. A closed window, killed
        # process, reboot or crash ("other", or no hook at all) keeps it.
        if (@('prompt_input_exit', 'logout', 'clear', 'resume') -contains [string](Get-Prop $ev 'reason')) { $action = 'remove' }
    }
    if (-not $action) { Write-Result ([ordered]@{ ok = $true; tracked = $false; why = 'kept' }); return }

    $lock = Enter-SnapshotLock $data
    try {
        $files = @(Get-SnapshotFiles $data)
        $snap = $null
        if ($files.Count -gt 0) { $snap = Read-JsonFile $files[0].FullName; $path = $files[0].FullName }
        if (-not $snap) {
            if ($action -eq 'remove') { Write-Result ([ordered]@{ ok = $true; tracked = $false; why = 'no-snapshot' }); return }
            $w = Write-NewSnapshot $data @() $true
            $path = $w.path
            $snap = Read-JsonFile $path
        }
        $items = @(@(Get-Prop $snap 'sessions') | Where-Object { ([string](Get-Prop $_ 'sessionId')).ToLowerInvariant() -ne $sid })
        if ($action -eq 'upsert' -and $entry.Contains('pid')) {
            $items = @($items | Where-Object {
                    -not ((Get-Prop $_ 'pid') -and [string](Get-Prop $_ 'pid') -eq [string]$entry.pid -and
                        [string](Get-Prop $_ 'procStart') -eq [string]$entry.procStart) })
        }
        if ($action -eq 'upsert') {
            # Keep the original opening time of a session that is resumed.
            $old = @(@(Get-Prop $snap 'sessions') | Where-Object { ([string](Get-Prop $_ 'sessionId')).ToLowerInvariant() -eq $sid })
            if ($old.Count -gt 0 -and (Get-Prop $old[0] 'startedAt')) { $entry.startedAt = [string](Get-Prop $old[0] 'startedAt') }
            $items += $entry
        }
        # A session (re)added by its own start is live again: it counts as pending, not settled.
        # (Sort-ByOpened already returns an array; wrapping it in @() again would nest it.)
        $sortedItems = Sort-ByOpened $items { param($s) Get-Prop $s 'startedAt' }
        $out = [ordered]@{
            version            = Get-Prop $snap 'version'
            createdAt          = Get-Prop $snap 'createdAt'
            restoredAt         = Get-Prop $snap 'restoredAt'
            restoredSessionIds = Remove-IdFromList (Get-Prop $snap 'restoredSessionIds') $sid
            settledSessionIds  = Remove-IdFromList (Get-Prop $snap 'settledSessionIds') $sid
            sessions           = $sortedItems
        }
        $out.managed = $true
        Write-JsonFile $path $out
    } finally { Exit-SnapshotLock $lock }
    Write-Result ([ordered]@{ ok = $true; tracked = $true; action = $action; sessionId = $sid; snapshot = $path })
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
            pending    = (Get-PendingSessions $o).Count
            sessions   = @($items | ForEach-Object { [ordered]@{
                        sessionId = (Get-Prop $_ 'sessionId'); title = (Get-Prop $_ 'title'); cwd = (Get-Prop $_ 'cwd')
                        lastPrompt = (Get-Prop $_ 'lastPrompt') } })
        }
    }
    Write-Result ([ordered]@{ ok = $true; dataDir = $data.dir; snapshots = $list })
}

# Deletes the saved list of sessions (never the conversations themselves).
function Invoke-Clear {
    $data = Resolve-DataDir
    $pendingSnap = Get-PendingSnapshot $data
    if ($pendingSnap -and -not $Force) {
        Stop-WithError 'unrestored-snapshot' "The snapshot from $($pendingSnap.createdAt) still has $($pendingSnap.pending.Count) session(s) that were never restored. Pass -Force to delete it anyway." @{ pendingSnapshot = $pendingSnap }
    }
    $removed = @()
    $sessionCount = 0
    $lock = Enter-SnapshotLock $data
    try {
        foreach ($f in (Get-SnapshotFiles $data)) {
            $o = Read-JsonFile $f.FullName
            if ($o) { $sessionCount += @(Get-Prop $o 'sessions').Count }
            Remove-Item -LiteralPath $f.FullName -Force
            $removed += $f.Name
        }
        # Leftovers of an interrupted write.
        foreach ($f in @(Get-ChildItem -LiteralPath $data.snapshots -Filter '*.tmp' -File)) { Remove-Item -LiteralPath $f.FullName -Force }
    } finally { Exit-SnapshotLock $lock }
    $configRemoved = $false
    $cfgPath = Join-Path $data.dir 'config.json'
    if ($IncludeConfig -and (Test-Path -LiteralPath $cfgPath)) { Remove-Item -LiteralPath $cfgPath -Force; $configRemoved = $true }
    Write-Result ([ordered]@{
            ok              = $true
            dataDir         = $data.dir
            removed         = $removed
            removedSessions = $sessionCount
            configRemoved   = $configRemoved
            configKept      = (-not $IncludeConfig) -and (Test-Path -LiteralPath $cfgPath)
            # Clearing doesn't stop managing: new and resumed sessions keep being added.
            managing        = (Test-Tracking $data)
        })
}

function Resolve-Exe([string]$override, [string[]]$names) {
    if ($override) { return $override }
    foreach ($n in $names) {
        $c = Get-Command $n -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($c) { return $c.Source }
    }
    return $null
}

function Read-Config($data) {
    $path = Join-Path $data.dir 'config.json'
    $cfg = [ordered]@{ restoreShell = $null; restoreTerminal = $null }
    if (Test-Path -LiteralPath $path) {
        $o = Read-JsonFile $path
        foreach ($k in @('restoreShell', 'restoreTerminal')) { $v = Get-Prop $o $k; if ($v) { $cfg[$k] = [string]$v } }
    }
    return $cfg
}

function Invoke-Config {
    $data = Resolve-DataDir
    $cfg = Read-Config $data
    $changed = $false
    if ($Reset) { $cfg.restoreShell = $null; $cfg.restoreTerminal = $null; $changed = $true }
    if ($UseShell) { $cfg.restoreShell = $(if ($UseShell -eq 'auto') { $null } else { $UseShell }); $changed = $true }
    if ($Terminal) { $cfg.restoreTerminal = $(if ($Terminal -eq 'auto') { $null } else { $Terminal }); $changed = $true }
    if ($changed) { Write-JsonFile (Join-Path $data.dir 'config.json') $cfg }
    Write-Result ([ordered]@{ ok = $true; config = $cfg; changed = $changed })
}

# Folder of a Git for Windows install (holds bin\bash.exe, usr\bin\mintty.exe).
function Find-GitRoot([string]$savedShellPath) {
    $candidates = @()
    if ($GitRoot) { $candidates += $GitRoot }
    else {
        if ($savedShellPath -and $savedShellPath -match '^(.*\\Git)\\(usr\\)?bin\\[^\\]+$') { $candidates += $Matches[1] }
        $git = Get-Command git -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($git -and $git.Source -match '^(.*\\Git)\\(cmd|bin|mingw64\\bin)\\git\.exe$') { $candidates += $Matches[1] }
        foreach ($pf in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs'))) {
            if ($pf) { $candidates += (Join-Path $pf 'Git') }
        }
    }
    foreach ($c in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $c 'bin\bash.exe')) { return $c }
    }
    return $null
}

function ConvertTo-PosixPath([string]$p) {
    if ($p -match '^([A-Za-z]):[\\/]?(.*)$') {
        $rest = ($Matches[2] -replace '\\', '/').TrimEnd('/')
        return '/' + $Matches[1].ToLowerInvariant() + '/' + $rest
    }
    return ($p -replace '\\', '/')
}

function ConvertTo-BashLiteral([string]$s) { return "'" + ($s -replace "'", "'\''") + "'" }

function Get-TabTitle([string]$t) {
    $t = ($t -replace '["`;]', '').Trim().TrimEnd('\')
    if (-not $t) { $t = 'claude' }
    if ($t.Length -gt 40) { $t = $t.Substring(0, 40) }
    return $t
}

# Which shells exist on this machine right now.
function Get-ShellAvailability {
    $wsRoot = $env:SystemRoot
    $ps = Resolve-Exe $PowerShellExe @('powershell')
    if (-not $ps -and $wsRoot) {
        $p = Join-Path $wsRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        if (Test-Path -LiteralPath $p) { $ps = $p }
    }
    $cmd = $env:ComSpec
    if (-not $cmd -or -not (Test-Path -LiteralPath $cmd)) { $cmd = Join-Path $wsRoot 'System32\cmd.exe' }
    $pwsh = $null
    if (-not $PowerShellExe) { $pwsh = Resolve-Exe $null @('pwsh') }
    $conhost = Join-Path $wsRoot 'System32\conhost.exe'
    if (-not (Test-Path -LiteralPath $conhost)) { $conhost = $null }
    return @{
        pwsh       = $pwsh
        powershell = $ps
        cmd        = $cmd
        wt         = [bool](Get-Command wt -ErrorAction SilentlyContinue)
        conhost    = $conhost
    }
}

# Opens a console program in a classic console window even when Windows is set to
# hand console apps to Windows Terminal; falls back to a plain start.
function Set-WindowLaunch($spec, [string]$exe, [string]$argLine) {
    if ($script:Avail.conhost) {
        $spec.exe = $script:Avail.conhost
        $spec.args = '"' + $exe + '" ' + $argLine
    } else {
        $spec.exe = $exe
        $spec.args = $argLine
    }
}

# Claude Code marks the shells it runs tools in as belonging to its session
# (CLAUDE_CODE_CHILD_SESSION, CLAUDE_CODE_SESSION_ID, messaging socket, ...).
# A restored session inheriting them would think it is a child of the session
# running `restore` and turn transcript saving off, so drop them before launching.
# Variables the user set at User/Machine level are kept.
function Clear-ClaudeSessionEnv {
    # Also: colour switches Claude Code sets for its tool shells (NO_COLOR=1 makes restored
    # sessions colourless), and variables describing the terminal `restore` runs in (TERM,
    # TERM_PROGRAM, WT_SESSION, ...): each new terminal describes itself.
    $rx = '^(CLAUDECODE|CLAUDE_PID|CLAUDE_EFFORT|AI_AGENT|CLAUDE_CODE_(CHILD_SESSION|SESSION_.+|SESSION|MESSAGING_.+|ENTRYPOINT|EXECPATH|SSE_PORT|IDE_.+)' +
        '|NO_COLOR|FORCE_COLOR|TERM|TERM_PROGRAM|TERM_PROGRAM_VERSION|TERM_SESSION_ID|COLORTERM|WT_SESSION|WT_PROFILE_ID' +
        '|ITERM_SESSION_ID|KITTY_WINDOW_ID|WEZTERM_PANE|ALACRITTY_WINDOW_ID|ALACRITTY_SOCKET|VTE_VERSION|TMUX|TMUX_PANE)$'
    $removed = @()
    foreach ($item in @(Get-ChildItem Env:)) {
        if ($item.Name -notmatch $rx) { continue }
        if ([Environment]::GetEnvironmentVariable($item.Name, 'User') -or [Environment]::GetEnvironmentVariable($item.Name, 'Machine')) { continue }
        Remove-Item -LiteralPath "Env:$($item.Name)" -ErrorAction SilentlyContinue
        $removed += $item.Name
    }
    return , $removed
}

# Decide shell + terminal for one session. Tries the wanted shell, then
# PowerShell 7, Windows PowerShell and cmd, so a missing shell never blocks a restore.
function Resolve-LaunchTarget($item, $avail, [string]$shellPref, [string]$termPref) {
    $savedShell = [string](Get-Prop $item 'shell')
    $savedHost = [string](Get-Prop $item 'host')
    $wanted = $shellPref
    if (-not $wanted) { $wanted = $savedShell }
    if (-not $wanted) { $wanted = 'powershell' }

    $order = @($wanted) + @('pwsh', 'powershell', 'cmd' | Where-Object { $_ -ne $wanted })
    $notes = @()
    foreach ($shell in $order) {
        $target = $null
        if ($shell -eq 'gitbash') {
            $root = Find-GitRoot ([string](Get-Prop $item 'shellPath'))
            if (-not $root) { $notes += 'Git Bash not found'; continue }
            $hasMintty = (Test-Path -LiteralPath (Join-Path $root 'usr\bin\mintty.exe')) -and
                (Test-Path -LiteralPath (Join-Path $root 'usr\bin\bash.exe'))
            $term = $termPref
            if (-not $term -or $term -eq 'auto') {
                if ($savedShell -eq 'gitbash' -and $savedHost -in @('wt', 'vscode', 'jetbrains')) { $term = 'wt' } else { $term = 'window' }
            }
            if ($term -eq 'window' -and -not $hasMintty) { $notes += 'mintty not found'; $term = 'wt' }
            if ($term -eq 'wt' -and -not $avail.wt) {
                if ($hasMintty) { $notes += 'Windows Terminal not found'; $term = 'window' }
                else { $notes += 'no terminal for Git Bash'; continue }
            }
            $target = @{ shell = 'gitbash'; terminal = $term; root = $root }
        } else {
            $exe = $avail[$shell]
            if (-not $exe) {
                if ($shell -eq $wanted) { $notes += "$shell not found" }
                continue
            }
            $term = $termPref
            if (-not $term -or $term -eq 'auto') {
                # Standalone console window stays one; everything else prefers Windows Terminal.
                if ($savedHost -eq 'console' -and $savedShell -eq $shell) { $term = 'window' }
                elseif ($avail.wt) { $term = 'wt' } else { $term = 'window' }
            }
            if ($term -eq 'wt' -and -not $avail.wt) { $notes += 'Windows Terminal not found'; $term = 'window' }
            $target = @{ shell = $shell; terminal = $term; exe = $exe }
        }
        $fallback = $null
        if ($target.shell -ne $wanted -or $notes.Count -gt 0) { $fallback = ($notes | Select-Object -Unique) -join '; ' }
        $target.fallback = $fallback
        return $target
    }
    return $null
}

# Builds the command line(s) for one session.
function New-LaunchSpec($target, [string]$sid, [string]$cwd, [string]$title, [string]$claude) {
    $t = Get-TabTitle $title
    $spec = @{ wtTab = $null; exe = $null; args = $null; env = @{}; command = $null }
    switch ($target.shell) {
        'gitbash' {
            $bashCmd = 'cd ' + (ConvertTo-BashLiteral (ConvertTo-PosixPath $cwd)) + ' && (' +
                (ConvertTo-BashLiteral (ConvertTo-PosixPath $claude)) + " --resume $sid || :) && exec bash --login -i"
            $spec.command = $bashCmd
            $root = $target.root
            if ($target.terminal -eq 'wt') {
                # bin\bash.exe sets up the Git Bash environment itself; `;` must be escaped for wt.
                $spec.wtTab = ('--title "{0}" "{1}" --login -i -c "{2}"' -f $t, (Join-Path $root 'bin\bash.exe'), $bashCmd) -replace ';', '\;'
            } else {
                # Same way git-bash.exe opens its window.
                $spec.exe = Join-Path $root 'usr\bin\mintty.exe'
                $spec.args = '-o AppID=GitForWindows.Bash -o AppName="Git Bash" -i "{0}" -t "{1}" -- /usr/bin/bash --login -i -c "{2}"' -f (Join-Path $root 'git-bash.exe'), $t, $bashCmd
                $spec.env = @{ MSYSTEM = 'MINGW64'; CHERE_INVOKING = '1' }
            }
        }
        'cmd' {
            # cmd keeps the quotes in `/k "<exe>" args` only when the path has no &()^@ etc.;
            # prefer the 8.3 short path (no spaces, no quotes needed) when it exists.
            $exePath = $claude
            if ($exePath -match '[\s&()^@,;=!%]') {
                try {
                    $short = (New-Object -ComObject Scripting.FileSystemObject).GetFile($exePath).ShortPath
                    if ($short -and $short -notmatch '[\s&()^@,;=!%]') { $exePath = $short }
                } catch { }
            }
            if ($exePath -match '\s') { $exePath = '"' + $exePath + '"' }
            $inner = '{0} --resume {1}' -f $exePath, $sid
            $spec.command = "/k $inner"
            if ($target.terminal -eq 'wt') {
                $dir = $cwd
                if ($dir.EndsWith('\')) { $dir += '.' }
                $spec.wtTab = ('--title "{0}" -d "{1}" "{2}" /k {3}' -f $t, $dir, $target.exe, $inner) -replace ';', '\;'
            } else {
                Set-WindowLaunch $spec $target.exe "/k $inner"
            }
        }
        default {
            $text = "Set-Location -LiteralPath $(ConvertTo-PsLiteral $cwd); & $(ConvertTo-PsLiteral $claude) --resume $sid"
            $spec.command = $text
            $enc = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($text))
            if ($target.terminal -eq 'wt') {
                $spec.wtTab = '--title "{0}" "{1}" -NoExit -EncodedCommand {2}' -f $t, $target.exe, $enc
            } else {
                Set-WindowLaunch $spec $target.exe "-NoExit -EncodedCommand $enc"
            }
        }
    }
    return $spec
}

function Start-Window($spec, [string]$cwd) {
    $saved = @{}
    foreach ($k in $spec.env.Keys) { $saved[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $spec.env[$k]) }
    try {
        Start-Process -FilePath $spec.exe -ArgumentList $spec.args -WorkingDirectory $cwd
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
    }
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
    # Reopen in the order they were originally opened (snapshots without start times keep their stored order).
    $items = Sort-ByOpened $items { param($s) Get-Prop $s 'startedAt' }

    $claude = Resolve-Exe $ClaudeExe @('claude')
    if (-not $claude) { Stop-WithError 'claude-not-found' 'The claude executable is not on PATH.' }

    # Per-run flags win over the saved preference, which wins over what each session ran in.
    $cfg = Read-Config $data
    $shellPref = $UseShell
    if (-not $shellPref) { $shellPref = $cfg.restoreShell }
    if ($shellPref -eq 'auto') { $shellPref = $null }
    $termPref = $Terminal
    if (-not $termPref) { $termPref = $cfg.restoreTerminal }
    $avail = Get-ShellAvailability
    $script:Avail = $avail

    $live = Get-LiveSessions $true
    $liveIds = @{}
    if ($live.source -eq 'registry') { foreach ($s in $live.sessions) { $liveIds[$s.sessionId] = $true } }

    $launch = @()
    $skipped = @()
    $specs = @{}
    foreach ($it in $items) {
        $sid = ([string](Get-Prop $it 'sessionId')).ToLowerInvariant()
        $cwd = [string](Get-Prop $it 'cwd')
        $title = [string](Get-Prop $it 'title')
        $row = [ordered]@{ sessionId = $sid; title = $title; cwd = $cwd }
        $reason = $null
        $target = $null
        if ($sid -notmatch $GuidRx) { $reason = 'bad-id' }
        elseif ($liveIds.ContainsKey($sid)) { $reason = 'already-running' }
        elseif (-not $cwd -or -not (Test-Path -LiteralPath $cwd -PathType Container)) { $reason = 'folder-missing' }
        elseif (-not (Find-Transcript $sid)) { $reason = 'transcript-missing' }
        else {
            $target = Resolve-LaunchTarget $it $avail $shellPref $termPref
            if (-not $target) { $reason = 'no-shell' }
        }
        if ($reason) { $row.reason = $reason; $skipped += $row; continue }

        $spec = New-LaunchSpec $target $sid $cwd $title $claude
        $row.shell = $target.shell
        $row.savedShell = Get-Prop $it 'shell'
        $row.terminal = $target.terminal
        $row.fallback = $target.fallback
        $row.command = $spec.command
        $specs[$sid] = $spec
        $launch += $row
    }

    $clearedEnv = @()
    if (-not $DryRun) {
        if ($launch.Count -gt 0) { $clearedEnv = Clear-ClaudeSessionEnv }
        $wtRows = @($launch | Where-Object { $_.terminal -eq 'wt' })
        # One Windows Terminal window per 10 tabs keeps the command line well under the 32K limit.
        # In the saved order: Windows Terminal tabs go left to right in one window (opened when
        # the first of them comes up); separate windows open one by one, with a pause so they
        # appear (and line up in the taskbar) in that order.
        $wtDone = $false
        $windowsLeft = @($launch | Where-Object { $_.terminal -ne 'wt' }).Count
        foreach ($row in $launch) {
            if ($row.terminal -eq 'wt') {
                if ($wtDone) { continue }
                $wtDone = $true
                for ($i = 0; $i -lt $wtRows.Count; $i += 10) {
                    $chunk = @($wtRows[$i..([Math]::Min($i + 9, $wtRows.Count - 1))])
                    $tabs = @($chunk | ForEach-Object { 'new-tab ' + $specs[$_.sessionId].wtTab })
                    Start-Process -FilePath 'wt.exe' -ArgumentList ('-w new ' + ($tabs -join ' ; '))
                }
                if ($windowsLeft -gt 0) { Start-Sleep -Milliseconds 700 }
                continue
            }
            Start-Window $specs[$row.sessionId] $row.cwd
            $windowsLeft--
            if ($windowsLeft -gt 0) { Start-Sleep -Milliseconds 700 }
        }

        # Settled = opened now, or can never be opened; `save` may replace a snapshot once all are settled.
        $permanent = @($skipped | Where-Object { $_.reason -ne 'no-shell' } | ForEach-Object { $_.sessionId })
        if ($launch.Count -gt 0 -or $permanent.Count -gt 0) {
            # Re-read under the lock: while sessions start, their hooks may already be updating it.
            $lock = Enter-SnapshotLock $data
            try {
                $cur = Read-JsonFile $snapPath
                if ($cur) { $snap = $cur }
                $restored = @(@(Get-Prop $snap 'restoredSessionIds') | Where-Object { $_ }) + @($launch | ForEach-Object { $_.sessionId })
                $settled = @(@(Get-Prop $snap 'settledSessionIds') | Where-Object { $_ }) + $restored + $permanent
                $restoredAt = Get-Prop $snap 'restoredAt'
                if ($launch.Count -gt 0) { $restoredAt = (Get-Date).ToUniversalTime().ToString('o') }
                $out = [ordered]@{
                    version            = Get-Prop $snap 'version'
                    createdAt          = Get-Prop $snap 'createdAt'
                    restoredAt         = $restoredAt
                    restoredSessionIds = @($restored | Select-Object -Unique)
                    settledSessionIds  = @($settled | Select-Object -Unique)
                    sessions           = @(Get-Prop $snap 'sessions')
                }
                if (Get-Prop $snap 'managed') { $out.managed = $true }
                Write-JsonFile $snapPath $out
            } finally { Exit-SnapshotLock $lock }
        }
    }

    Write-Result ([ordered]@{
            ok       = $true
            snapshot = $snapPath
            dryRun   = [bool]$DryRun
            launched = $launch
            skipped  = $skipped
            clearedEnv = $clearedEnv
        })
}

try {
    switch ($Command) {
        'list' { Invoke-List }
        'save' { Invoke-Save }
        'snapshots' { Invoke-Snapshots }
        'restore' { Invoke-Restore }
        'config' { Invoke-Config }
        'clear' { Invoke-Clear }
        'manage' { Invoke-Manage }
        'track' { Invoke-Track }
    }
} catch {
    Stop-WithError 'unexpected' $_.Exception.Message
}
