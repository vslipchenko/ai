"""Tests for sessions.py (Linux). Standard library only.

    python3 -I scripts/tests/test_sessions.py            # fast
    SESSIONS_LAUNCH=1 python3 -I scripts/tests/test_sessions.py   # + real launches in every
                                                         # installed terminal (windows close themselves)
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), 'sessions.py')
LAUNCH = os.environ.get('SESSIONS_LAUNCH') == '1'

A = 'aaaaaaaa-0000-4000-8000-000000000001'  # live, interactive (a real process)
B = 'bbbbbbbb-0000-4000-8000-000000000002'  # live, non-interactive
C = 'cccccccc-0000-4000-8000-000000000003'  # PID reused by another program
D = 'dddddddd-0000-4000-8000-000000000004'  # dead PID
E = 'eeeeeeee-0000-4000-8000-000000000005'  # ended, transcript only
F = 'ffffffff-0000-4000-8000-000000000006'  # folder missing
G = 'aaaabbbb-0000-4000-8000-000000000007'  # transcript missing
U = '12345678-0000-4000-8000-00000000000f'  # unknown


def run(*args, env=None):
    r = subprocess.run([sys.executable, '-I', SCRIPT] + list(args), capture_output=True, text=True, env=env)
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise AssertionError('bad output: %r %r' % (r.stdout, r.stderr))


def stat_start(pid):
    with open('/proc/%d/stat' % pid) as f:
        data = f.read()
    return data[data.rfind(')') + 2:].split()[19]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


class Env:
    """A fake ~/.claude with live 'claude' processes (copies of sleep named claude)."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='sessions-test-')
        self.home = os.path.join(self.root, 'claude')
        self.data = os.path.join(self.root, 'data')
        self.proj = os.path.join(self.root, "proj A's folder")
        os.makedirs(self.proj)
        bindir = os.path.join(self.root, 'bin')
        os.makedirs(bindir)
        # A script named claude: its process name is "claude" (a copied binary may not run
        # under another name, e.g. multi-call coreutils). The trailing `:` keeps it alive.
        self.fake_claude_bin = os.path.join(bindir, 'claude')
        write(self.fake_claude_bin, '#!/bin/sh\nsleep "$1"\n:\n')
        os.chmod(self.fake_claude_bin, 0o755)
        self.procs = []

    def spawn(self, argv, **kw):
        # Own process group, so cleanup also ends whatever the helper started.
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, **kw)
        self.procs.append(p)
        return p

    def registry(self, pid, sid, cwd, proc_start, kind='interactive', name=None, home=None):
        o = {'pid': pid, 'sessionId': sid, 'cwd': cwd, 'startedAt': 1793722012466, 'procStart': proc_start,
             'kind': kind, 'name': name or 'reg-' + sid[:4], 'status': 'idle'}
        write(os.path.join(home or self.home, 'sessions', '%d.json' % pid), json.dumps(o))

    def transcript(self, sid, cwd, extra=(), home=None):
        lines = [json.dumps({'type': 'mode', 'mode': 'normal', 'sessionId': sid}),
                 json.dumps({'type': 'user', 'message': {'role': 'user', 'content': 'hi'}, 'cwd': cwd, 'sessionId': sid})]
        write(os.path.join(home or self.home, 'projects', 'proj', sid + '.jsonl'), '\n'.join(lines + list(extra)))

    def snapshot(self, name, sessions, data=None, **extra):
        s = {'version': 1, 'createdAt': '2026-01-01T00:00:00Z', 'restoredAt': None, 'restoredSessionIds': [],
             'sessions': sessions}
        s.update(extra)
        write(os.path.join(data or self.data, 'snapshots', name), json.dumps(s))

    def close(self):
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.SubprocessError:
                pass
        shutil.rmtree(self.root, ignore_errors=True)


class SessionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = e = Env()
        # A: "claude" started from bash, so the shell is detectable.
        shell = e.spawn(['bash', '-c', '"$0" 300; :', e.fake_claude_bin])
        assert wait_for(lambda: any(True for _ in cls._children(shell.pid)))
        cls.claude_a = next(cls._children(shell.pid))
        e.registry(cls.claude_a, A, e.proj, stat_start(cls.claude_a))
        b = e.spawn([e.fake_claude_bin, '300'])
        e.registry(b.pid, B, e.proj, stat_start(b.pid), kind='sdk')
        other = e.spawn(['sleep', '300'])  # a different program on the PID
        e.registry(other.pid, C, e.proj, '1')
        e.registry(999999, D, e.proj, '1')
        write(os.path.join(e.home, 'sessions', 'broken.json'), '{"pid": 12, "sessio')
        e.transcript(A, e.proj, [json.dumps({'type': 'ai-title', 'aiTitle': 'Old AI title', 'sessionId': A}),
                                 json.dumps({'type': 'custom-title', 'customTitle': 'My named session', 'sessionId': A}),
                                 json.dumps({'type': 'ai-title', 'aiTitle': 'Newer AI title', 'sessionId': A}),
                                 json.dumps({'type': 'last-prompt', 'lastPrompt': 'fix   the\nbug', 'sessionId': A})])
        e.transcript(E, e.proj, [json.dumps({'type': 'ai-title', 'aiTitle': 'Ended work', 'sessionId': E})])
        e.transcript(F, os.path.join(e.root, 'gone'))

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    @staticmethod
    def _children(pid):
        for d in os.listdir('/proc'):
            if d.isdigit():
                try:
                    with open('/proc/%s/stat' % d) as f:
                        data = f.read()
                except OSError:
                    continue
                if int(data[data.rfind(')') + 2:].split()[1]) == pid:
                    yield int(d)

    def h(self):
        return ['-ClaudeHome', self.env.home]

    # ------------------------------------------------------------ list
    def test_list(self):
        r = run('list', *self.h(), '-CurrentSessionId', A)
        self.assertTrue(r['ok'])
        self.assertEqual(r['source'], 'registry')
        self.assertEqual([s['sessionId'] for s in r['sessions']], [A], 'stale, reused-PID, dead and broken entries skipped')
        self.assertEqual(r['hiddenNonInteractive'], 1)
        s = r['sessions'][0]
        self.assertTrue(s['isCurrent'])
        self.assertEqual(s['title'], 'My named session')
        self.assertEqual(s['lastPrompt'], 'fix the bug')
        self.assertEqual(s['cwd'], self.env.proj)
        self.assertEqual(s['shell'], 'bash')
        self.assertTrue(s['shellPath'].endswith('bash'))

    def test_list_non_interactive(self):
        r = run('list', *self.h(), '-IncludeNonInteractive')
        ids = {s['sessionId']: s for s in r['sessions']}
        self.assertEqual(set(ids), {A, B})
        self.assertEqual(ids[B]['title'], 'reg-bbbb')

    def test_start_time_formats(self):
        e = self.env
        home = os.path.join(e.root, 'claude-fmt')
        p = e.spawn([e.fake_claude_bin, '300'])
        ticks = int(stat_start(p.pid))
        with open('/proc/stat') as f:
            btime = next(int(l.split()[1]) for l in f if l.startswith('btime '))
        started = btime + ticks / float(os.sysconf('SC_CLK_TCK'))
        for label, value in (('ticks', str(ticks)), ('epoch ms', str(int(started * 1000))), ('epoch s', str(int(started)))):
            e.registry(p.pid, A, e.proj, value, home=home)
            r = run('list', '-ClaudeHome', home)
            self.assertEqual(len(r['sessions']), 1, label)
        # Unknown format on a process that is not claude: rejected.
        o = e.spawn(['sleep', '300'])
        e.registry(o.pid, B, e.proj, 'weird', home=home)
        r = run('list', '-ClaudeHome', home)
        self.assertNotIn(B, [s['sessionId'] for s in r['sessions']])

    def test_tmux_detection(self):
        if not shutil.which('tmux'):
            self.skipTest('tmux not installed')
        e = self.env
        home = os.path.join(e.root, 'claude-tmux')
        sock = 'sessions-test-%d' % os.getpid()
        subprocess.run(['tmux', '-L', sock, 'new-session', '-d', '-s', 'work',
                        'bash -c \'"%s" 300; :\'' % e.fake_claude_bin], check=True)
        try:
            server = subprocess.run(['tmux', '-L', sock, 'display-message', '-p', '#{pid}'], capture_output=True, text=True).stdout.strip()
            pane_shell = subprocess.run(['tmux', '-L', sock, 'display-message', '-p', '#{pane_pid}'], capture_output=True, text=True).stdout.strip()
            self.assertTrue(wait_for(lambda: any(True for _ in self._children(int(pane_shell)))))
            claude = next(self._children(int(pane_shell)))
            e.registry(claude, A, e.proj, stat_start(claude), home=home)
            s = run('list', '-ClaudeHome', home)['sessions'][0]
            self.assertEqual((s['shell'], s['host'], s['tmuxSession']), ('bash', 'tmux', 'work'))
            self.assertTrue(server)
        finally:
            subprocess.run(['tmux', '-L', sock, 'kill-server'], stderr=subprocess.DEVNULL)

    def test_wsl_started_from_windows(self):
        """A shell started by wsl.exe (as Windows Terminal does) sits under WSL's Relay/SessionLeader."""
        wslexe = shutil.which('wsl.exe')
        if not (os.environ.get('WSL_DISTRO_NAME') and wslexe):
            self.skipTest('not WSL')
        e = self.env
        home = os.path.join(e.root, 'claude-wsl')
        tag = '301'
        p = e.spawn([wslexe, '-d', os.environ['WSL_DISTRO_NAME'], '-e', 'bash', '-c', '"$0" %s; :' % tag, e.fake_claude_bin])
        found = []

        def find():
            for d in os.listdir('/proc'):
                if d.isdigit():
                    try:
                        with open('/proc/%s/cmdline' % d, 'rb') as f:
                            args = f.read().split(b'\0')
                    except OSError:
                        continue
                    # A script runs as: /bin/sh <script> <args...>
                    if len(args) >= 2 and args[1] == e.fake_claude_bin.encode() and tag.encode() in args:
                        found.append(int(d))
                        return True
            return False
        try:
            self.assertTrue(wait_for(find, 15), 'process started via wsl.exe not found')
            claude = found[0]
            e.registry(claude, A, e.proj, stat_start(claude), home=home)
            s = run('list', '-ClaudeHome', home)['sessions'][0]
            self.assertEqual((s['shell'], s['host']), ('bash', 'wt'))
        finally:
            for pid in found:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            p.kill()

    def test_transcript_fallback(self):
        e = self.env
        home = os.path.join(e.root, 'claude2')
        e.transcript(E, e.proj, [json.dumps({'type': 'ai-title', 'aiTitle': 'Recent', 'sessionId': E})], home=home)
        r = run('list', '-ClaudeHome', home)
        self.assertEqual(r['source'], 'transcripts')
        self.assertEqual(r['sessions'][0]['sessionId'], E)

    # ------------------------------------------------------------ save
    def test_save(self):
        e = self.env
        data = os.path.join(e.root, 'save-data')
        r = run('save', *self.h(), '-DataDir', data, '-Ids', '%s,%s,%s' % (A, E, U))
        self.assertTrue(r['ok'])
        self.assertEqual(len(r['saved']), 2)
        self.assertEqual(r['missing'], [U])
        self.assertTrue(os.path.isfile(r['snapshot']))
        ended = [s for s in r['saved'] if s['sessionId'] == E][0]
        self.assertEqual((ended['cwd'], ended['title']), (e.proj, 'Ended work'))
        live = [s for s in r['saved'] if s['sessionId'] == A][0]
        self.assertEqual(live['shell'], 'bash')

    def test_save_errors_and_fallback_dir(self):
        e = self.env
        r = run('save', *self.h(), '-DataDir', '${CLAUDE_PLUGIN_DATA}', '-Ids', A, '-Force')
        self.assertTrue(r['dataDirFallback'])
        self.assertEqual(r['dataDir'], os.path.join(e.home, 'plugins', 'data', 'sessions-vslipchenko'))
        r = run('save', *self.h(), '-DataDir', e.data, '-Ids', 'not-a-guid')
        self.assertEqual(r['error'], 'bad-id')
        r = run('save', *self.h(), '-DataDir', e.data, '-Ids', U)
        self.assertEqual(r['error'], 'nothing-saved')

    def test_one_snapshot_and_protection(self):
        e = self.env
        one = os.path.join(e.root, 'one')
        snaps = os.path.join(one, 'snapshots')
        count = lambda: len([f for f in os.listdir(snaps) if f.startswith('snapshot-')])
        r = run('save', *self.h(), '-DataDir', one, '-Ids', A)
        self.assertEqual(r['replaced'], 0)
        r = run('save', *self.h(), '-DataDir', one, '-Ids', E)
        self.assertEqual(r['error'], 'unrestored-snapshot')
        self.assertEqual([p['sessionId'] for p in r['pendingSnapshot']['pending']], [A])
        self.assertEqual(count(), 1)
        r = run('list', *self.h(), '-DataDir', one)
        self.assertTrue(r['pendingSnapshot'])
        time.sleep(1.1)
        r = run('save', *self.h(), '-DataDir', one, '-Ids', E, '-Force')
        self.assertEqual((r['ok'], r['replaced'], count()), (True, 1, 1))

        two = [{'sessionId': A, 'cwd': e.proj, 'title': 'a'}, {'sessionId': E, 'cwd': e.proj, 'title': 'e'}]
        for f in os.listdir(snaps):
            os.remove(os.path.join(snaps, f))
        e.snapshot('snapshot-20260101-000000.json', two, data=one, restoredAt='x', settledSessionIds=[A, E])
        r = run('save', *self.h(), '-DataDir', one, '-Ids', A)
        self.assertEqual((r['ok'], count()), (True, 1), 'fully restored snapshot replaced silently')
        for f in os.listdir(snaps):
            os.remove(os.path.join(snaps, f))
        e.snapshot('snapshot-20260101-000000.json', two, data=one, restoredAt='x', settledSessionIds=[A])
        r = run('save', *self.h(), '-DataDir', one, '-Ids', A)
        self.assertEqual([p['sessionId'] for p in r['pendingSnapshot']['pending']], [E], 'partly restored protects the rest')
        for f in os.listdir(snaps):
            os.remove(os.path.join(snaps, f))
        for i in range(1, 4):
            e.snapshot('snapshot-2026010%d-000000.json' % i, two, data=one, restoredAt='x')
        r = run('save', *self.h(), '-DataDir', one, '-Ids', A)
        self.assertEqual((r['replaced'], count()), (3, 1), 'older restored snapshots cleaned up')

        # A restore where every session is open or gone settles the snapshot without opening anything.
        for f in os.listdir(snaps):
            os.remove(os.path.join(snaps, f))
        e.snapshot('snapshot-20260101-000000.json', [{'sessionId': A, 'cwd': e.proj, 'title': 'a'},
                                                     {'sessionId': F, 'cwd': os.path.join(e.root, 'gone'), 'title': 'f'}],
                   data=one, settledSessionIds=[])
        r = run('restore', *self.h(), '-DataDir', one, '-ClaudeExe', '/x/claude')
        self.assertEqual((len(r['launched']), len(r['skipped'])), (0, 2))
        r = run('save', *self.h(), '-DataDir', one, '-Ids', A)
        self.assertTrue(r['ok'])

    def test_snapshots(self):
        e = self.env
        data = os.path.join(e.root, 'snaps-data')
        run('save', *self.h(), '-DataDir', data, '-Ids', '%s,%s' % (A, E))
        r = run('snapshots', *self.h(), '-DataDir', data)
        self.assertEqual(len(r['snapshots']), 1)
        self.assertEqual(r['snapshots'][0]['count'], 2)
        self.assertIn(A, [s['sessionId'] for s in r['snapshots'][0]['sessions']])

    # ------------------------------------------------------------ restore planning
    def plan(self, fields, *more, terminals='xterm,tmux', shells='bash,zsh,fish,sh'):
        e = self.env
        entry = {'sessionId': E, 'cwd': e.proj, 'title': 'plan'}
        entry.update(fields)
        data = os.path.join(e.root, 'plan-data')
        e.snapshot('plan.json', [entry], data=data)
        env = dict(os.environ, DISPLAY=':0')
        r = run('restore', *self.h(), '-DataDir', data, '-DryRun', '-Snapshot', 'plan', '-ClaudeExe', '/x/claude',
                '-Terminals', terminals, '-Shells', shells, *more, env=env)
        self.assertTrue(r['ok'], r)
        return r['launched'][0] if r['launched'] else r['skipped'][0]

    def test_restore_skips(self):
        e = self.env
        data = os.path.join(e.root, 'restore-data')
        e.snapshot('snapshot-29990101-000000.json', [
            {'sessionId': A, 'cwd': e.proj, 'title': 'a'},
            {'sessionId': E, 'cwd': e.proj, 'title': 'e "quoted"; title'},
            {'sessionId': F, 'cwd': os.path.join(e.root, 'gone'), 'title': 'f'},
            {'sessionId': G, 'cwd': e.proj, 'title': 'g'}], data=data)
        r = run('restore', *self.h(), '-DataDir', data, '-DryRun', '-ClaudeExe', '/x/claude')
        self.assertEqual([l['sessionId'] for l in r['launched']], [E])
        reasons = {s['sessionId']: s['reason'] for s in r['skipped']}
        self.assertEqual(reasons, {A: 'already-running', F: 'folder-missing', G: 'transcript-missing'})
        with open(os.path.join(data, 'snapshots', 'snapshot-29990101-000000.json')) as f:
            self.assertIsNone(json.load(f)['restoredAt'], 'dry run does not mark the snapshot')
        r = run('restore', *self.h(), '-DataDir', data, '-DryRun', '-ClaudeExe', 'x', '-Ids', G)
        self.assertEqual((len(r['launched']), len(r['skipped'])), (0, 1))
        r = run('restore', *self.h(), '-DataDir', data, '-DryRun', '-ClaudeExe', 'x', '-Snapshot', 'nope')
        self.assertEqual(r['error'], 'snapshot-not-found')
        r = run('restore', *self.h(), '-DataDir', os.path.join(e.root, 'empty'), '-DryRun', '-ClaudeExe', 'x')
        self.assertEqual(r['error'], 'no-snapshots')

    def test_restore_commands(self):
        e = self.env
        bash = shutil.which('bash') or '/bin/bash'
        fish = shutil.which('fish') or '/bin/fish'
        p = self.plan({'shell': 'bash', 'host': 'xterm'})
        q = "'" + e.proj.replace("'", "'\\''") + "'"
        self.assertEqual((p['shell'], p['terminal'], p['fallback']), ('bash', 'xterm', None))
        self.assertEqual(p['command'], "cd %s && ('/x/claude' --resume %s || :) && exec '%s' -l" % (q, E, bash))
        self.assertNotIn(';', p['command'], 'no ; so Windows Terminal needs no escaping')
        p = self.plan({'shell': 'fish'})
        fq = "'" + e.proj.replace('\\', '\\\\').replace("'", "\\'") + "'"
        self.assertEqual(p['command'], "cd %s && '/x/claude' --resume %s; exec '%s' -l" % (fq, E, fish))

    def test_restore_fallbacks(self):
        p = self.plan({'shell': 'zsh', 'host': 'xterm'}, shells='bash,sh')
        self.assertEqual(p['shell'], 'bash')
        self.assertIn('zsh not found', p['fallback'])
        p = self.plan({'shell': 'bash'}, shells='sh')
        self.assertEqual(p['shell'], 'sh')
        p = self.plan({'shell': 'nu'})
        self.assertEqual(p['shell'], 'bash')
        self.assertIn('not supported', p['fallback'])
        p = self.plan({'shell': 'bash', 'host': 'konsole'}, terminals='xterm,tmux')
        self.assertEqual(p['terminal'], 'xterm')
        self.assertIn('konsole not available', p['fallback'])
        p = self.plan({'shell': 'bash', 'host': 'vscode'}, terminals='xterm')
        self.assertIn("editor terminals can't be opened", p['fallback'])
        p = self.plan({'shell': 'bash', 'host': 'xterm'}, terminals='tmux')
        self.assertEqual(p['terminal'], 'tmux', 'no graphical terminal -> detached tmux')
        p = self.plan({'shell': 'bash', 'host': 'xterm'}, terminals='')
        self.assertEqual(p['reason'], 'no-terminal')
        p = self.plan({'shell': 'bash', 'host': 'tmux', 'tmuxSession': 'work'}, terminals='xterm,tmux')
        self.assertEqual((p['terminal'], p['tmuxSession']), ('tmux', 'work'))
        p = self.plan({'shell': 'bash', 'host': 'tmux'}, terminals='tmux')
        self.assertEqual(p['tmuxSession'], 'claude-sessions')
        p = self.plan({'shell': 'bash', 'host': 'xterm'}, '-UseShell', 'sh', '-Terminal', 'tmux')
        self.assertEqual((p['shell'], p['terminal']), ('sh', 'tmux'))

    def test_restore_wt_from_wsl(self):
        p = self.plan({'shell': 'bash', 'host': 'wt'}, terminals='wt,xterm')
        self.assertEqual((p['terminal'], p['fallback']), ('wt', None))
        p = self.plan({'shell': 'bash', 'host': 'konsole'}, terminals='wt,xterm')
        self.assertEqual(p['terminal'], 'wt', 'in WSL, Windows Terminal is the first fallback')
        p = self.plan({'shell': 'bash', 'host': 'wt'}, terminals='xterm')
        self.assertEqual(p['terminal'], 'xterm')
        self.assertIn('wt not available', p['fallback'])

    def test_config(self):
        e = self.env
        data = os.path.join(e.root, 'plan-data')
        r = run('config', *self.h(), '-DataDir', data, '-UseShell', 'sh', '-Terminal', 'tmux')
        self.assertEqual((r['config']['restoreShell'], r['config']['restoreTerminal']), ('sh', 'tmux'))
        try:
            p = self.plan({'shell': 'bash', 'host': 'xterm'})
            self.assertEqual((p['shell'], p['terminal']), ('sh', 'tmux'))
        finally:
            r = run('config', *self.h(), '-DataDir', data, '-Reset')
        self.assertIsNone(r['config']['restoreShell'])
        p = self.plan({'shell': 'bash', 'host': 'xterm'})
        self.assertEqual(p['terminal'], 'xterm')

    @staticmethod
    def _wt_pids():
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            '(Get-Process WindowsTerminal -ErrorAction SilentlyContinue).Id'],
                           capture_output=True, text=True, cwd='/mnt/c')
        return {int(x) for x in r.stdout.split() if x.strip().isdigit()}

    def _close_test_wt(self, before):
        """The tab stays open showing the fake's exit code. Close it only if it lives in a
        Windows Terminal process this test started (never one of the user's own windows)."""
        time.sleep(1.5)
        for pid in self._wt_pids() - before:
            r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                '(Get-Process -Id %d).MainWindowTitle' % pid], capture_output=True, text=True, cwd='/mnt/c')
            if r.stdout.strip() == 'launch test':
                subprocess.run(['powershell.exe', '-NoProfile', '-Command', 'Stop-Process -Id %d' % pid],
                               capture_output=True, cwd='/mnt/c')
                return
        print('  note: the Windows Terminal test tab ("launch test") opened in an existing window; close it by hand')

    @staticmethod
    def _wt():
        return bool(os.environ.get('WSL_DISTRO_NAME')) and bool(shutil.which('wt.exe'))

    # ------------------------------------------------------------ real launches
    @unittest.skipUnless(LAUNCH, 'set SESSIONS_LAUNCH=1')
    def test_real_launches(self):
        e = self.env
        marker = os.path.join(e.root, 'marker.txt')
        fake_dir = os.path.join(e.root, 'fake dir')
        os.makedirs(fake_dir)
        fake = os.path.join(fake_dir, 'claude')
        # Records "<cwd>|<args>|<leaked markers>", then ends the shell that started it so the
        # window closes (a Windows Terminal tab may stay open showing the exit code).
        write(fake, '#!/bin/sh\nleak=""\nfor v in CLAUDE_CODE_CHILD_SESSION CLAUDECODE CLAUDE_CODE_SESSION_ID; do\n'
                    '  eval "[ -n \\"\\${$v+x}\\" ]" && leak="$leak$v,"\ndone\n'
                    'printf "%%s|%%s|%%s\\n" "$PWD" "$*" "$leak" >> %s\nkill -9 $PPID\n' % ("'" + marker + "'"))
        os.chmod(fake, 0o755)
        data = os.path.join(e.root, 'launch-data')
        e.snapshot('snapshot-29990101-000000.json', [{'sessionId': E, 'cwd': e.proj, 'title': 'launch test'}], data=data)
        env = dict(os.environ, CLAUDE_CODE_CHILD_SESSION='1', CLAUDECODE='1', CLAUDE_CODE_SESSION_ID='parent',
                   TMUX_TMPDIR=tempfile.mkdtemp(prefix='tmux-', dir=e.root))
        cases = [(t, 'bash') for t in ['xterm', 'gnome-terminal', 'kitty', 'alacritty', 'foot', 'konsole', 'tmux']
                 if shutil.which(t)]
        for sh in ('zsh', 'fish', 'sh'):
            if shutil.which(sh) and shutil.which('xterm'):
                cases.append(('xterm', sh))
        if self._wt():
            cases.append(('wt', 'bash'))
        self.assertTrue(cases, 'no terminal installed')
        failures = []
        for term, sh in cases:
            if os.path.exists(marker):
                os.remove(marker)
            wt_before = self._wt_pids() if term == 'wt' else None
            r = run('restore', *self.h(), '-DataDir', data, '-ClaudeExe', fake, '-Terminal', term, '-UseShell', sh,
                    '-Ids', E, env=env)
            ok = wait_for(lambda: os.path.exists(marker), 25)
            got = ''
            if ok:
                with open(marker) as f:
                    got = f.read().strip()
            if wt_before is not None:
                self._close_test_wt(wt_before)
            want = '%s|--resume %s|' % (e.proj, E)
            if got != want or r['launched'][0]['terminal'] != term:
                failures.append('%s/%s: got %r (%s)' % (term, sh, got, r['launched'][0].get('fallback')))
            else:
                print('  ok   real launch: %s in %s' % (sh, term))
        subprocess.run(['tmux', 'kill-server'], env=env, stderr=subprocess.DEVNULL)
        self.assertEqual(failures, [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
