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

  Compatible with Windows PowerShell 5.1 and PowerShell 7+.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('list', 'save', 'snapshots', 'restore', 'config')]
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

    # Overrides, mainly for tests.
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

    # Newest first, with the session running the skill pinned to the top.
    $sorted = @($sessions | Sort-Object -Descending -Property @{ Expression = {
                if ($_.Contains('startedAt')) { $_.startedAt } else { $_.lastActive } } })
    $current = @($sorted | Where-Object { $_.isCurrent })
    $others = @($sorted | Where-Object { -not $_.isCurrent })
    return [ordered]@{ source = $source; sessions = @($current + $others); hiddenNonInteractive = $hidden }
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

function Invoke-List {
    $r = Get-LiveSessions ([bool]$IncludeNonInteractive)
    $data = Resolve-DataDir
    Write-Result ([ordered]@{
            ok                   = $true
            source               = $r.source
            sessions             = $r.sessions
            hiddenNonInteractive = $r.hiddenNonInteractive
            pendingSnapshot      = Get-PendingSnapshot $data
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
            $s = [ordered]@{ sessionId = $e.sessionId; cwd = $e.cwd; title = $e.title; lastPrompt = $e.lastPrompt
                shell = $null; shellPath = $null; host = $null }
            foreach ($k in @('shell', 'shellPath', 'host')) { if ($e.Contains($k)) { $s[$k] = $e[$k] } }
            $saved += $s
        } else { $missing += $id }
    }
    if ($saved.Count -eq 0) { Stop-WithError 'nothing-saved' 'None of the given sessions could be found.' }

    # Only one snapshot is kept. Never replace one with sessions still waiting to be restored unless told to.
    $pendingSnap = Get-PendingSnapshot $data
    if ($pendingSnap -and -not $Force) {
        Stop-WithError 'unrestored-snapshot' "The snapshot from $($pendingSnap.createdAt) still has $($pendingSnap.pending.Count) session(s) that were never restored. Pass -Force to replace it." @{ pendingSnapshot = $pendingSnap }
    }

    $now = Get-Date
    $path = Join-Path $data.snapshots ('snapshot-' + $now.ToString('yyyyMMdd-HHmmss') + '.json')
    Write-JsonFile $path ([ordered]@{
            version            = 1
            createdAt          = $now.ToUniversalTime().ToString('o')
            restoredAt         = $null
            restoredSessionIds = @()
            settledSessionIds  = @()
            sessions           = $saved
        })

    $replaced = 0
    foreach ($f in (Get-SnapshotFiles $data)) {
        if ($f.FullName -ne $path) { Remove-Item -LiteralPath $f.FullName -Force; $replaced++ }
    }

    Write-Result ([ordered]@{
            ok              = $true
            snapshot        = $path
            dataDir         = $data.dir
            dataDirFallback = $data.fallback
            saved           = $saved
            missing         = $missing
            replaced        = $replaced
        })
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
    $rx = '^(CLAUDECODE|CLAUDE_PID|CLAUDE_EFFORT|AI_AGENT|CLAUDE_CODE_(CHILD_SESSION|SESSION_.+|SESSION|MESSAGING_.+|ENTRYPOINT|EXECPATH|SSE_PORT|IDE_.+))$'
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
        for ($i = 0; $i -lt $wtRows.Count; $i += 10) {
            $chunk = @($wtRows[$i..([Math]::Min($i + 9, $wtRows.Count - 1))])
            $tabs = @($chunk | ForEach-Object { 'new-tab ' + $specs[$_.sessionId].wtTab })
            Start-Process -FilePath 'wt.exe' -ArgumentList ('-w new ' + ($tabs -join ' ; '))
        }
        foreach ($row in @($launch | Where-Object { $_.terminal -ne 'wt' })) {
            Start-Window $specs[$row.sessionId] $row.cwd
        }

        # Settled = opened now, or can never be opened; `save` may replace a snapshot once all are settled.
        $permanent = @($skipped | Where-Object { $_.reason -ne 'no-shell' } | ForEach-Object { $_.sessionId })
        $restored = @(@(Get-Prop $snap 'restoredSessionIds') | Where-Object { $_ }) + @($launch | ForEach-Object { $_.sessionId })
        $settled = @(@(Get-Prop $snap 'settledSessionIds') | Where-Object { $_ }) + $restored + $permanent
        if ($launch.Count -gt 0 -or $permanent.Count -gt 0) {
            $restoredAt = Get-Prop $snap 'restoredAt'
            if ($launch.Count -gt 0) { $restoredAt = (Get-Date).ToUniversalTime().ToString('o') }
            Write-JsonFile $snapPath ([ordered]@{
                    version            = Get-Prop $snap 'version'
                    createdAt          = Get-Prop $snap 'createdAt'
                    restoredAt         = $restoredAt
                    restoredSessionIds = @($restored | Select-Object -Unique)
                    settledSessionIds  = @($settled | Select-Object -Unique)
                    sessions           = @(Get-Prop $snap 'sessions')
                })
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
    }
} catch {
    Stop-WithError 'unexpected' $_.Exception.Message
}
