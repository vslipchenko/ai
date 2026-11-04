#!/usr/bin/env python3
"""Discover, snapshot and restore live Claude Code sessions (Linux).

Linux counterpart of sessions.ps1: same subcommands, flags and JSON output
(one line on stdout), same snapshot files.

  list       Live Claude Code sessions from <ClaudeHome>/sessions/<pid>.json, each
             checked against the running process via /proc, falling back to
             recently written transcripts if that registry is unavailable. Each
             session records its shell (bash / zsh / fish / sh / ...) and, when
             detectable, its terminal (gnome-terminal, konsole, kitty, tmux, wt, ...).
  save       Write a snapshot of the sessions in -Ids, replacing the previous one.
             Refuses (unrestored-snapshot) while the previous one has sessions not
             yet restored, unless -Force.
  snapshots  Summarise the stored snapshot (normally just one).
  restore    Reopen each session with `claude --resume <id>` in its folder, in the
             shell and terminal it ran in. Missing shell -> bash -> sh; missing
             terminal -> Windows Terminal (WSL) / system default / any installed
             terminal -> a detached tmux session.
  config     Show or set the default restore shell/terminal (-UseShell, -Terminal, -Reset).
  clear      Delete the saved snapshot (the list of sessions, not the conversations).
             Refuses (unrestored-snapshot) while it has sessions not yet restored,
             unless -Force; -IncludeConfig also deletes the restore defaults.

Standard library only; Python 3.8+.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

GUID_RX = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
# Variables Claude Code puts on the shells it runs tools in. A restored session that
# inherits them thinks it is a child of the session running `restore` and turns
# transcript saving off.
MARKER_RX = re.compile(r'^(CLAUDECODE|CLAUDE_PID|CLAUDE_EFFORT|AI_AGENT|CLAUDE_CODE_(CHILD_SESSION|SESSION_.+|SESSION|MESSAGING_.+|ENTRYPOINT|EXECPATH|SSE_PORT|IDE_.+))$')

TYPE_RX = re.compile(r'"type":\s*"(custom-title|ai-title|last-prompt)"')
TYPE_KEYS = {'custom-title': 'customTitle', 'ai-title': 'aiTitle', 'last-prompt': 'lastPrompt'}

SHELL_NAMES = {'bash': 'bash', 'zsh': 'zsh', 'fish': 'fish', 'sh': 'sh', 'dash': 'sh', 'ksh': 'ksh',
               'mksh': 'ksh', 'tcsh': 'tcsh', 'csh': 'tcsh', 'nu': 'nu', 'pwsh': 'pwsh', 'elvish': 'elvish',
               'xonsh': 'xonsh'}
RESTORABLE_SHELLS = ('bash', 'zsh', 'fish', 'sh')

# Terminal (or multiplexer / editor) a process tree can lead to: process name -> host.
HOST_NAMES = {
    'gnome-terminal-': 'gnome-terminal', 'gnome-terminal-server': 'gnome-terminal', 'gnome-terminal': 'gnome-terminal',
    'ptyxis': 'ptyxis', 'ptyxis-agent': 'ptyxis', 'kgx': 'kgx', 'gnome-console': 'kgx',
    'konsole': 'konsole', 'xfce4-terminal': 'xfce4-terminal', 'tilix': 'tilix', 'terminator': 'terminator',
    'kitty': 'kitty', 'wezterm-gui': 'wezterm', 'wezterm': 'wezterm', 'alacritty': 'alacritty',
    'foot': 'foot', 'footclient': 'foot', 'xterm': 'xterm', 'uxterm': 'xterm',
    'tmux: server': 'tmux', 'tmux': 'tmux', 'screen': 'screen', 'SCREEN': 'screen',
    'code': 'vscode', 'code-oss': 'vscode', 'codium': 'vscode', 'cursor': 'vscode', 'windsurf': 'vscode',
    'sshd': 'ssh', 'sshd-session': 'ssh',
}
# Restore preference among installed graphical terminals when the saved one can't be used.
GUI_TERMINALS = ['gnome-terminal', 'ptyxis', 'kgx', 'konsole', 'xfce4-terminal', 'tilix', 'kitty',
                 'wezterm', 'alacritty', 'foot', 'terminator', 'xterm']
TERMINAL_CHOICES = ['', 'auto', 'wt', 'tmux', 'x-terminal-emulator'] + GUI_TERMINALS


# ---------------------------------------------------------------- output

def write_result(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def fail(code, message, extra=None):
    r = {'ok': False, 'error': code, 'message': message}
    r.update(extra or {})
    write_result(r)
    sys.exit(1)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- files

def read_text(path, max_bytes=8 * 1024 * 1024):
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        partial = size > max_bytes
        f.seek(size - max_bytes if partial else 0)
        data = f.read().decode('utf-8', 'replace')
    lines = re.split(r'\r?\n', data)
    if partial and lines:
        lines = lines[1:]
    return lines


def read_json(path):
    for _ in range(2):
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        except (OSError, ValueError):
            time.sleep(0.1)  # may be mid-write
    return None


def write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def short(text, n):
    if not text:
        return None
    t = re.sub(r'\s+', ' ', str(text)).strip()
    return t[:n - 3] + '...' if len(t) > n else t


def posix_quote(s):
    # Single quotes only (no double quotes), so the string also survives Windows
    # command-line quoting on the way through wt.exe / wsl.exe.
    return "'" + str(s).replace("'", "'\\''") + "'"


def fish_quote(s):
    return "'" + str(s).replace('\\', '\\\\').replace("'", "\\'") + "'"


# ---------------------------------------------------------------- context

class Ctx:
    def __init__(self, a):
        self.a = a
        self.home = a.ClaudeHome or os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
        self._project_dirs = None
        self._boot = None

    # -- ids / data dir
    def id_list(self):
        out = []
        for i in re.split(r'[,\s]+', self.a.Ids or ''):
            if not i:
                continue
            if not GUID_RX.match(i):
                fail('bad-id', 'Not a session id: %s' % i)
            out.append(i.lower())
        return out

    def data_dir(self):
        d = self.a.DataDir
        fallback = False
        if not d or '${' in d:
            # Same folder Claude Code assigns as ${CLAUDE_PLUGIN_DATA} for sessions@vslipchenko.
            d = os.path.join(self.home, 'plugins', 'data', 'sessions-vslipchenko')
            fallback = True
        snaps = os.path.join(d, 'snapshots')
        os.makedirs(snaps, exist_ok=True)
        return {'dir': d, 'snapshots': snaps, 'fallback': fallback}

    # -- transcripts
    def find_transcript(self, sid):
        if self._project_dirs is None:
            proj = os.path.join(self.home, 'projects')
            self._project_dirs = [p for p in glob.glob(os.path.join(glob.escape(proj), '*')) if os.path.isdir(p)]
        for d in self._project_dirs:
            p = os.path.join(d, sid + '.jsonl')
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def transcript_info(path):
        info = {'customTitle': None, 'aiTitle': None, 'lastPrompt': None, 'cwd': None}
        if not path:
            return info
        try:
            lines = read_text(path)
        except OSError:
            return info
        for line in lines:
            if not line:
                continue
            m = TYPE_RX.search(line)
            key = TYPE_KEYS.get(m.group(1)) if m else None
            if key:
                try:
                    v = json.loads(line).get(key)
                except ValueError:
                    v = None
                if v:
                    info[key] = v
            if '"cwd"' in line:
                m = re.search(r'"cwd":\s*("(?:[^"\\]|\\.)*")', line)
                if m:
                    try:
                        info['cwd'] = json.loads(m.group(1))
                    except ValueError:
                        pass
        return info

    def session_entry(self, sid, cwd, registry_name, extra):
        transcript = self.find_transcript(sid)
        ti = self.transcript_info(transcript)
        cwd = cwd or ti['cwd']
        title = ti['customTitle'] or ti['aiTitle'] or registry_name or (os.path.basename(cwd.rstrip('/')) if cwd else None)
        cur = (self.a.CurrentSessionId or '').lower()
        e = {'sessionId': sid, 'cwd': cwd, 'title': short(title, 60), 'lastPrompt': short(ti['lastPrompt'], 100),
             'transcript': bool(transcript), 'isCurrent': bool(cur) and sid == cur}
        e.update(extra)
        return e

    # -- processes (/proc)
    def boot_time(self):
        if self._boot is None:
            self._boot = 0
            try:
                with open('/proc/stat') as f:
                    for line in f:
                        if line.startswith('btime '):
                            self._boot = int(line.split()[1])
            except OSError:
                pass
        return self._boot

    @staticmethod
    def proc_stat(pid):
        try:
            with open('/proc/%d/stat' % int(pid), 'rb') as f:
                data = f.read().decode('utf-8', 'replace')
        except (OSError, ValueError):
            return None
        r = data.rfind(')')
        rest = data[r + 2:].split()
        try:
            return {'comm': data[data.find('(') + 1:r], 'ppid': int(rest[1]), 'start': int(rest[19])}
        except (IndexError, ValueError):
            return None

    @staticmethod
    def proc_exe(pid):
        try:
            return os.readlink('/proc/%d/exe' % pid)
        except OSError:
            return None

    @staticmethod
    def proc_environ(pid):
        try:
            with open('/proc/%d/environ' % pid, 'rb') as f:
                raw = f.read().decode('utf-8', 'replace')
        except OSError:
            return {}
        env = {}
        for item in raw.split('\0'):
            k, sep, v = item.partition('=')
            if sep:
                env[k] = v
        return env

    def process_live(self, pid, proc_start):
        st = self.proc_stat(pid)
        if not st:
            return False
        is_claude = st['comm'].startswith(('claude', 'node', 'bun'))
        if proc_start in (None, ''):
            return is_claude
        s = str(proc_start)
        if s == str(st['start']):
            return True
        try:
            v = float(s)
        except ValueError:
            return is_claude
        # Also accept the start time expressed as epoch seconds or milliseconds.
        started = self.boot_time() + st['start'] / float(os.sysconf('SC_CLK_TCK'))
        if abs(v - started) < 2 or abs(v / 1000.0 - started) < 2:
            return True
        # A start-time format we don't know: trust a matching process name rather than
        # hide every session; a different program on a reused PID is still rejected.
        return is_claude

    def launch_info(self, pid):
        """Nearest shell above the Claude process, and the terminal hosting it."""
        info = {'shell': None, 'shellPath': None, 'host': None, 'tmuxSession': None}
        from_windows = False
        seen = set()
        cur = self.proc_stat(pid)
        for _ in range(16):
            if not cur or cur['ppid'] <= 1 or cur['ppid'] in seen:
                break
            ppid = cur['ppid']
            seen.add(ppid)
            cur = self.proc_stat(ppid)
            if not cur:
                break
            if cur['comm'].startswith('Relay(') or cur['comm'] == 'SessionLeader':
                # WSL's init helpers: this shell was started from Windows by wsl.exe, so
                # its window is a Windows one (Windows Terminal on Windows 11).
                from_windows = True
                break
            exe = self.proc_exe(ppid)
            names = [cur['comm'], os.path.basename(exe) if exe else '']
            if not info['shell']:
                shell = next((SHELL_NAMES[n] for n in names if n in SHELL_NAMES), None)
                if shell:
                    info['shell'] = shell
                    info['shellPath'] = exe or shutil.which(cur['comm'])
                    continue
            host = next((HOST_NAMES[n] for n in names if n in HOST_NAMES), None)
            if host:
                info['host'] = host
                break
        env = self.proc_environ(pid)
        if not info['host']:
            # Hints the terminal leaves in the environment, e.g. Windows Terminal running WSL
            # (the window itself is outside Linux, so the process tree ends at WSL's init).
            tp = env.get('TERM_PROGRAM', '')
            if env.get('TMUX'):
                info['host'] = 'tmux'
            elif tp == 'vscode':
                info['host'] = 'vscode'
            elif tp == 'WezTerm' or env.get('WEZTERM_PANE'):
                info['host'] = 'wezterm'
            elif env.get('KITTY_WINDOW_ID'):
                info['host'] = 'kitty'
            elif env.get('KONSOLE_VERSION'):
                info['host'] = 'konsole'
            elif env.get('GNOME_TERMINAL_SCREEN'):
                info['host'] = 'gnome-terminal'
            elif env.get('ALACRITTY_WINDOW_ID') or env.get('ALACRITTY_SOCKET'):
                info['host'] = 'alacritty'
            elif env.get('TILIX_ID'):
                info['host'] = 'tilix'
            elif env.get('TERMINATOR_UUID'):
                info['host'] = 'terminator'
            elif env.get('WT_SESSION') or from_windows:
                info['host'] = 'wt'
        if info['host'] == 'tmux' and env.get('TMUX') and shutil.which('tmux'):
            socket = env['TMUX'].split(',')[0]
            argv = ['tmux', '-S', socket, 'display-message', '-p']
            if env.get('TMUX_PANE'):
                argv += ['-t', env['TMUX_PANE']]
            try:
                r = subprocess.run(argv + ['#{session_name}'], capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    info['tmuxSession'] = r.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return info

    def live_sessions(self, include_non_interactive):
        sessions, seen = [], set()
        hidden = usable = 0
        reg = os.path.join(self.home, 'sessions')
        if os.path.isdir(reg):
            for f in sorted(glob.glob(os.path.join(glob.escape(reg), '*.json'))):
                o = read_json(f)
                if not isinstance(o, dict):
                    continue
                sid, cwd, pid = str(o.get('sessionId') or ''), o.get('cwd'), o.get('pid')
                if not sid or not cwd or not pid or not GUID_RX.match(sid):
                    continue
                usable += 1
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    continue
                if not self.process_live(pid, o.get('procStart')):
                    continue
                kind = o.get('kind')
                if kind and kind != 'interactive' and not include_non_interactive:
                    hidden += 1
                    continue
                sid = sid.lower()
                if sid in seen:
                    continue
                seen.add(sid)
                started = None
                if o.get('startedAt'):
                    try:
                        started = datetime.fromtimestamp(float(o['startedAt']) / 1000.0, timezone.utc).isoformat()
                    except (TypeError, ValueError, OverflowError):
                        pass
                li = self.launch_info(pid)
                extra = {'pid': pid, 'kind': kind, 'status': o.get('status'), 'startedAt': started}
                extra.update(li)
                sessions.append(self.session_entry(sid, cwd, o.get('name'), extra))
        source = 'registry'
        if usable == 0:
            # Registry missing or in an unknown format: fall back to recently written transcripts.
            source = 'transcripts'
            cutoff = time.time() - self.a.SinceHours * 3600
            files = []
            for p in glob.glob(os.path.join(glob.escape(os.path.join(self.home, 'projects')), '*', '*.jsonl')):
                base = os.path.basename(p)[:-6]
                try:
                    m = os.path.getmtime(p)
                except OSError:
                    continue
                if m >= cutoff and GUID_RX.match(base):
                    files.append((m, base.lower()))
            for m, sid in sorted(files, reverse=True):
                if sid in seen:
                    continue
                seen.add(sid)
                e = self.session_entry(sid, None, None, {'lastActive': datetime.fromtimestamp(m, timezone.utc).isoformat()})
                if e['cwd']:
                    sessions.append(e)
        sessions.sort(key=lambda e: e.get('startedAt') or e.get('lastActive') or '', reverse=True)
        sessions = [e for e in sessions if e['isCurrent']] + [e for e in sessions if not e['isCurrent']]
        return {'source': source, 'sessions': sessions, 'hiddenNonInteractive': hidden}

    # -- snapshots
    @staticmethod
    def snapshot_files(data):
        return sorted(glob.glob(os.path.join(glob.escape(data['snapshots']), 'snapshot-*.json')), reverse=True)

    @staticmethod
    def pending_sessions(snap):
        items = snap.get('sessions') or []
        if 'settledSessionIds' not in snap:
            return [] if snap.get('restoredAt') else list(items)
        settled = {str(s).lower() for s in (snap.get('settledSessionIds') or []) if s}
        return [i for i in items if str(i.get('sessionId', '')).lower() not in settled]

    def pending_snapshot(self, data):
        for f in self.snapshot_files(data):
            o = read_json(f)
            if not isinstance(o, dict):
                continue
            pending = self.pending_sessions(o)
            if not pending:
                continue
            return {'file': os.path.basename(f), 'createdAt': o.get('createdAt'), 'count': len(o.get('sessions') or []),
                    'pending': [{'sessionId': p.get('sessionId'), 'title': p.get('title'), 'cwd': p.get('cwd')} for p in pending]}
        return None

    def read_config(self, data):
        cfg = {'restoreShell': None, 'restoreTerminal': None}
        o = read_json(os.path.join(data['dir'], 'config.json'))
        if isinstance(o, dict):
            for k in cfg:
                if o.get(k):
                    cfg[k] = str(o[k])
        return cfg


# ---------------------------------------------------------------- commands

def cmd_list(c):
    r = c.live_sessions(c.a.IncludeNonInteractive)
    data = c.data_dir()
    write_result({'ok': True, 'source': r['source'], 'sessions': r['sessions'],
                  'hiddenNonInteractive': r['hiddenNonInteractive'], 'pendingSnapshot': c.pending_snapshot(data)})


def cmd_save(c):
    ids = c.id_list()
    if not ids:
        fail('no-ids', 'Pass the session ids to save with -Ids.')
    data = c.data_dir()
    by_id = {s['sessionId']: s for s in c.live_sessions(True)['sessions']}
    saved, missing = [], []
    for sid in ids:
        e = by_id.get(sid)
        if not e:
            # Ended between `list` and `save`: still resumable if its transcript exists.
            t = c.session_entry(sid, None, None, {})
            e = t if t['transcript'] and t['cwd'] else None
        if e:
            saved.append({k: e.get(k) for k in ('sessionId', 'cwd', 'title', 'lastPrompt', 'shell', 'shellPath', 'host', 'tmuxSession')})
        else:
            missing.append(sid)
    if not saved:
        fail('nothing-saved', 'None of the given sessions could be found.')

    pending = c.pending_snapshot(data)
    if pending and not c.a.Force:
        fail('unrestored-snapshot', 'The snapshot from %s still has %d session(s) that were never restored. Pass -Force to replace it.'
             % (pending['createdAt'], len(pending['pending'])), {'pendingSnapshot': pending})

    path = os.path.join(data['snapshots'], 'snapshot-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.json')
    write_json(path, {'version': 1, 'createdAt': now_iso(), 'restoredAt': None, 'restoredSessionIds': [],
                      'settledSessionIds': [], 'sessions': saved})
    replaced = 0
    for f in c.snapshot_files(data):
        if os.path.abspath(f) != os.path.abspath(path):
            os.remove(f)
            replaced += 1
    write_result({'ok': True, 'snapshot': path, 'dataDir': data['dir'], 'dataDirFallback': data['fallback'],
                  'saved': saved, 'missing': missing, 'replaced': replaced})


def cmd_snapshots(c):
    data = c.data_dir()
    out = []
    for f in c.snapshot_files(data):
        o = read_json(f)
        if not isinstance(o, dict):
            continue
        items = o.get('sessions') or []
        out.append({'file': os.path.basename(f), 'createdAt': o.get('createdAt'), 'restoredAt': o.get('restoredAt'),
                    'count': len(items), 'pending': len(c.pending_sessions(o)),
                    'sessions': [{k: i.get(k) for k in ('sessionId', 'title', 'cwd', 'lastPrompt')} for i in items]})
    write_result({'ok': True, 'dataDir': data['dir'], 'snapshots': out})


def cmd_clear(c):
    """Deletes the saved list of sessions (never the conversations themselves)."""
    data = c.data_dir()
    pending = c.pending_snapshot(data)
    if pending and not c.a.Force:
        fail('unrestored-snapshot', 'The snapshot from %s still has %d session(s) that were never restored. Pass -Force to delete it anyway.'
             % (pending['createdAt'], len(pending['pending'])), {'pendingSnapshot': pending})
    removed, count = [], 0
    for f in c.snapshot_files(data):
        o = read_json(f)
        if isinstance(o, dict):
            count += len(o.get('sessions') or [])
        os.remove(f)
        removed.append(os.path.basename(f))
    for f in glob.glob(os.path.join(glob.escape(data['snapshots']), '*.tmp')):  # interrupted writes
        os.remove(f)
    cfg = os.path.join(data['dir'], 'config.json')
    config_removed = False
    if c.a.IncludeConfig and os.path.isfile(cfg):
        os.remove(cfg)
        config_removed = True
    write_result({'ok': True, 'dataDir': data['dir'], 'removed': removed, 'removedSessions': count,
                  'configRemoved': config_removed, 'configKept': not c.a.IncludeConfig and os.path.isfile(cfg)})


def cmd_config(c):
    data = c.data_dir()
    cfg = c.read_config(data)
    changed = False
    if c.a.Reset:
        cfg = {'restoreShell': None, 'restoreTerminal': None}
        changed = True
    if c.a.UseShell:
        cfg['restoreShell'] = None if c.a.UseShell == 'auto' else c.a.UseShell
        changed = True
    if c.a.Terminal:
        cfg['restoreTerminal'] = None if c.a.Terminal == 'auto' else c.a.Terminal
        changed = True
    if changed:
        write_json(os.path.join(data['dir'], 'config.json'), cfg)
    write_result({'ok': True, 'config': cfg, 'changed': changed})


# ---------------------------------------------------------------- restore

def in_wsl():
    if os.environ.get('WSL_DISTRO_NAME'):
        return True
    try:
        with open('/proc/version') as f:
            return 'microsoft' in f.read().lower()
    except OSError:
        return False


def find_windows_exe(name):
    p = shutil.which(name)
    if p:
        return p
    for cand in [os.path.join('/mnt/c/Windows/System32', name)] + glob.glob('/mnt/c/Users/*/AppData/Local/Microsoft/WindowsApps/' + name):
        if os.path.isfile(cand):
            return cand
    return None


def availability(c):
    a = c.a
    gui = bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    if a.Shells is not None or a.Terminals is not None:
        # Test overrides: pretend exactly these shells / terminals are installed.
        listed_shells = set(s for s in (a.Shells or '').split(',') if s)
        listed_terms = set(t for t in (a.Terminals or '').split(',') if t)
        shells = {s: (shutil.which(s) or '/bin/' + s) if s in listed_shells else None for s in RESTORABLE_SHELLS}
        terms = {t: shutil.which(t) or '/usr/bin/' + t for t in GUI_TERMINALS + ['x-terminal-emulator', 'tmux']
                 if t in listed_terms}
        wsl = 'wt' in listed_terms
        if wsl:
            terms.update({'wt': 'wt.exe', '_wsl': 'wsl.exe', '_distro': os.environ.get('WSL_DISTRO_NAME') or 'Ubuntu'})
        return {'shells': shells, 'terms': terms, 'wsl': wsl, 'gui': True}

    shells = {s: shutil.which(s) for s in RESTORABLE_SHELLS}
    terms = {}
    if gui:
        for t in GUI_TERMINALS + ['x-terminal-emulator']:
            exe = shutil.which(t)
            if exe:
                terms[t] = exe
    if shutil.which('tmux'):
        terms['tmux'] = shutil.which('tmux')
    wsl = in_wsl()
    if wsl:
        wt, wslexe = find_windows_exe('wt.exe'), find_windows_exe('wsl.exe')
        distro = os.environ.get('WSL_DISTRO_NAME')
        if wt and wslexe and distro:
            # wt.exe runs the tab's command on the Windows side, so name wsl.exe the Windows
            # way (it's always in System32), not by its /mnt/c path.
            terms.update({'wt': wt, '_wsl': 'wsl.exe', '_distro': distro})
    return {'shells': shells, 'terms': terms, 'wsl': wsl, 'gui': gui}


def resolve_target(item, avail, shell_pref, term_pref):
    saved_shell = item.get('shell')
    saved_host = item.get('host')
    notes = []

    wanted_shell = shell_pref or saved_shell or os.path.basename(os.environ.get('SHELL') or '') or 'bash'
    if wanted_shell not in RESTORABLE_SHELLS:
        notes.append('%s is not supported for restoring' % wanted_shell)
        wanted_shell = 'bash'
    shell = None
    for s in [wanted_shell] + [x for x in ('bash', 'sh') if x != wanted_shell]:
        if avail['shells'].get(s):
            shell = s
            break
        if s == wanted_shell:
            notes.append('%s not found' % s)
    if not shell:
        return None

    terms = avail['terms']
    wanted_terms = []
    if term_pref and term_pref != 'auto':
        wanted_terms.append(term_pref)
    elif saved_host:
        wanted_terms.append(saved_host)
    fallbacks = []
    if avail['wsl']:
        fallbacks.append('wt')
    fallbacks += ['x-terminal-emulator'] + GUI_TERMINALS + ['tmux']
    chosen = None
    for t in wanted_terms + [f for f in fallbacks if f not in wanted_terms]:
        if t in terms and not t.startswith('_'):
            chosen = t
            break
    if not chosen:
        return None
    for w in wanted_terms:
        if w != chosen:
            if w in ('vscode', 'screen', 'ssh'):
                notes.append({'vscode': "editor terminals can't be opened from outside",
                              'screen': 'screen sessions are not restored',
                              'ssh': 'it ran over SSH'}[w])
            else:
                notes.append('%s not available' % w)
    fallback = '; '.join(dict.fromkeys(notes)) if notes else None
    return {'shell': shell, 'shellExe': avail['shells'][shell], 'terminal': chosen, 'fallback': fallback}


def tab_title(t):
    t = re.sub(r'["`;]', '', t or '').strip().rstrip('\\')
    return (t or 'claude')[:40]


def build_spec(target, sid, cwd, title, claude, avail):
    shell, shell_exe = target['shell'], target['shellExe']
    if shell == 'fish':
        cmd = 'cd %s && %s --resume %s; exec %s -l' % (fish_quote(cwd), fish_quote(claude), sid, fish_quote(shell_exe))
    else:
        # No `;` so the command needs no escaping on its way through Windows Terminal.
        cmd = 'cd %s && (%s --resume %s || :) && exec %s -l' % (posix_quote(cwd), posix_quote(claude), sid, posix_quote(shell_exe))
    run = [shell_exe, '-l', '-c', cmd]
    t = tab_title(title)
    term = target['terminal']
    terms = avail['terms']
    exe = terms.get(term)
    spec = {'command': cmd, 'argv': None, 'wtTab': None, 'tmux': None}
    if term == 'wt':
        tab = ['new-tab', '--title', t, terms['_wsl'], '-d', terms['_distro'], '--cd', cwd, '-e'] + run
        spec['wtTab'] = [x.replace(';', '\\;') for x in tab]
    elif term == 'tmux':
        spec['tmux'] = {'session': None, 'window': t, 'shell': ' '.join(posix_quote(x) for x in run)}
    elif term == 'gnome-terminal':
        spec['argv'] = [exe, '--working-directory=' + cwd, '--'] + run
    elif term == 'ptyxis':
        spec['argv'] = [exe, '--new-window', '--working-directory=' + cwd, '--'] + run
    elif term == 'kgx':
        spec['argv'] = [exe, '--working-directory=' + cwd, '--'] + run
    elif term == 'konsole':
        spec['argv'] = [exe, '--workdir', cwd, '-p', 'tabtitle=' + t, '-e'] + run
    elif term == 'xfce4-terminal':
        spec['argv'] = [exe, '--working-directory', cwd, '--title', t, '-x'] + run
    elif term == 'tilix':
        spec['argv'] = [exe, '-w', cwd, '-t', t, '-e', ' '.join(posix_quote(x) for x in run)]
    elif term == 'terminator':
        spec['argv'] = [exe, '--working-directory', cwd, '-T', t, '-x'] + run
    elif term == 'kitty':
        spec['argv'] = [exe, '--directory', cwd, '--title', t] + run
    elif term == 'wezterm':
        spec['argv'] = [exe, 'start', '--cwd', cwd, '--'] + run
    elif term == 'alacritty':
        spec['argv'] = [exe, '--working-directory', cwd, '--title', t, '-e'] + run
    elif term == 'foot':
        spec['argv'] = [exe, '-D', cwd, '-T', t] + run
    elif term == 'xterm':
        spec['argv'] = [exe, '-T', t, '-e'] + run
    else:  # x-terminal-emulator: Debian's generic `-e command args...`
        spec['argv'] = [exe, '-e'] + run
    return spec


def clean_env():
    env = {k: v for k, v in os.environ.items() if not MARKER_RX.match(k)}
    removed = sorted(k for k in os.environ if MARKER_RX.match(k))
    return env, removed


def spawn(argv, cwd, env):
    subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def tmux_has_session(tmux, name, env):
    return subprocess.run([tmux, 'has-session', '-t', '=' + name], env=env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def cmd_restore(c):
    a = c.a
    data = c.data_dir()
    if a.Snapshot:
        name = a.Snapshot if a.Snapshot.endswith('.json') else a.Snapshot + '.json'
        snap_path = a.Snapshot if os.path.isabs(a.Snapshot) else os.path.join(data['snapshots'], name)
        if not os.path.isfile(snap_path):
            fail('snapshot-not-found', 'No snapshot at %s' % snap_path)
    else:
        files = c.snapshot_files(data)
        if not files:
            fail('no-snapshots', 'No saved snapshots yet.')
        snap_path = files[0]
    snap = read_json(snap_path)
    if not isinstance(snap, dict):
        fail('bad-snapshot', 'Could not read %s' % snap_path)

    ids = c.id_list()
    items = snap.get('sessions') or []
    if ids:
        items = [i for i in items if str(i.get('sessionId', '')).lower() in ids]

    claude = a.ClaudeExe or shutil.which('claude')
    if not claude:
        local = os.path.join(os.path.expanduser('~'), '.local', 'bin', 'claude')
        claude = local if os.path.isfile(local) else None
    if not claude:
        fail('claude-not-found', 'The claude executable was not found (PATH or ~/.local/bin).')

    # Per-run flags win over the saved preference, which wins over what each session ran in.
    cfg = c.read_config(data)
    shell_pref = a.UseShell or cfg['restoreShell']
    if shell_pref == 'auto' or shell_pref not in (None,) + RESTORABLE_SHELLS:
        shell_pref = None
    term_pref = a.Terminal or cfg['restoreTerminal']
    if term_pref not in TERMINAL_CHOICES:
        term_pref = None
    avail = availability(c)

    live = c.live_sessions(True)
    live_ids = {s['sessionId'] for s in live['sessions']} if live['source'] == 'registry' else set()

    launch, skipped, specs = [], [], {}
    for it in items:
        sid = str(it.get('sessionId') or '').lower()
        cwd = it.get('cwd') or ''
        title = it.get('title') or ''
        row = {'sessionId': sid, 'title': title, 'cwd': cwd}
        reason = None
        target = None
        if not GUID_RX.match(sid):
            reason = 'bad-id'
        elif sid in live_ids:
            reason = 'already-running'
        elif not cwd or not os.path.isdir(cwd):
            reason = 'folder-missing'
        elif not c.find_transcript(sid):
            reason = 'transcript-missing'
        else:
            target = resolve_target(it, avail, shell_pref, term_pref)
            if not target:
                reason = 'no-terminal'
        if reason:
            row['reason'] = reason
            skipped.append(row)
            continue
        spec = build_spec(target, sid, cwd, title, claude, avail)
        if spec['tmux']:
            spec['tmux']['session'] = it.get('tmuxSession') or 'claude-sessions'
        row.update({'shell': target['shell'], 'savedShell': it.get('shell'), 'terminal': target['terminal'],
                    'fallback': target['fallback'], 'command': spec['command']})
        if spec['tmux']:
            row['tmuxSession'] = spec['tmux']['session']
        specs[sid] = spec
        launch.append(row)

    cleared = []
    if not a.DryRun:
        env, cleared = clean_env() if launch else (None, [])
        wt_rows = [r for r in launch if r['terminal'] == 'wt']
        for i in range(0, len(wt_rows), 10):
            argv = [avail['terms']['wt'], '-w', 'new']
            for j, r in enumerate(wt_rows[i:i + 10]):
                if j:
                    argv.append(';')
                argv += specs[r['sessionId']]['wtTab']
            spawn(argv, '/mnt/c' if os.path.isdir('/mnt/c') else None, env)
        for r in launch:
            spec = specs[r['sessionId']]
            if r['terminal'] == 'wt':
                continue
            if spec['tmux']:
                tm = avail['terms']['tmux']
                t = spec['tmux']
                if tmux_has_session(tm, t['session'], env):
                    argv = [tm, 'new-window', '-t', '=' + t['session'] + ':', '-c', r['cwd'], '-n', t['window'], t['shell']]
                else:
                    argv = [tm, 'new-session', '-d', '-s', t['session'], '-c', r['cwd'], '-n', t['window'], t['shell']]
                subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                spawn(spec['argv'], r['cwd'], env)

        # Settled = opened now, or can never be opened; `save` may replace a snapshot once all are settled.
        permanent = [s['sessionId'] for s in skipped if s['reason'] != 'no-terminal']
        restored = [x for x in (snap.get('restoredSessionIds') or []) if x] + [r['sessionId'] for r in launch]
        settled = [x for x in (snap.get('settledSessionIds') or []) if x] + restored + permanent
        if launch or permanent:
            write_json(snap_path, {'version': snap.get('version'), 'createdAt': snap.get('createdAt'),
                                   'restoredAt': now_iso() if launch else snap.get('restoredAt'),
                                   'restoredSessionIds': list(dict.fromkeys(restored)),
                                   'settledSessionIds': list(dict.fromkeys(settled)),
                                   'sessions': snap.get('sessions') or []})

    write_result({'ok': True, 'snapshot': snap_path, 'dryRun': bool(a.DryRun), 'launched': launch,
                  'skipped': skipped, 'clearedEnv': cleared})


# ---------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog='sessions.py', allow_abbrev=False)
    p.add_argument('Command', choices=['list', 'save', 'snapshots', 'restore', 'config', 'clear'])
    p.add_argument('-DataDir', default='')
    p.add_argument('-CurrentSessionId', default='')
    p.add_argument('-Ids', default='')
    p.add_argument('-Snapshot', default='')
    p.add_argument('-IncludeNonInteractive', action='store_true')
    p.add_argument('-DryRun', action='store_true')
    p.add_argument('-Force', action='store_true')
    p.add_argument('-SinceHours', type=int, default=12)
    p.add_argument('-UseShell', default='', choices=('', 'auto') + RESTORABLE_SHELLS)
    p.add_argument('-Terminal', default='', choices=TERMINAL_CHOICES)
    p.add_argument('-Reset', action='store_true')
    p.add_argument('-IncludeConfig', action='store_true')
    # Overrides, mainly for tests.
    p.add_argument('-ClaudeHome', default='')
    p.add_argument('-ClaudeExe', default='')
    p.add_argument('-Terminals', default=None, help=argparse.SUPPRESS)
    p.add_argument('-Shells', default=None, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    c = Ctx(a)
    try:
        {'list': cmd_list, 'save': cmd_save, 'snapshots': cmd_snapshots, 'restore': cmd_restore,
         'config': cmd_config, 'clear': cmd_clear}[a.Command](c)
    except SystemExit:
        raise
    except Exception as e:  # report, never a traceback
        fail('unexpected', '%s: %s' % (type(e).__name__, e))


if __name__ == '__main__':
    main()
