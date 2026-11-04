"""Turn a test log into short GitHub annotations (readable via the public API).

    python .github/annotate.py <title> <log-file> <exit-status>

Prints one `::notice` with a one-line summary when the tests passed, or one
`::error` per failing test (traceback trimmed) plus a summary when they failed.
Messages are kept short and single-line: long multi-line ones may be dropped.
"""
import re
import sys


def esc(s):
    return s.replace('%', '%25').replace('\r', '').replace('\n', '%0A')


def main():
    title, path, status = sys.argv[1], sys.argv[2], int(sys.argv[3])
    with open(path, encoding='utf-8-sig', errors='replace') as f:   # -sig: PowerShell writes a BOM
        text = f.read()
    lines = [l.rstrip() for l in text.splitlines()]
    # One-line summary: unittest ("Ran N tests" + OK/FAILED), PowerShell suite ("N passed, M failed"),
    # node --test ("pass N" / "fail N"), plus any "note" lines (skipped real launches etc.).
    keys = [l.strip() for l in lines if re.match(r'^(Ran \d+ tests|OK|FAILED|\d+ passed, \d+ failed)', l.strip())]
    keys += ['%s %s' % (m.group(1), m.group(2)) for m in re.finditer(r'\b(pass|fail) (\d+)\b', text)][-2:]
    notes = [l.strip() for l in lines if l.strip().startswith(('note', 'ok   real launch'))]
    summary = ' | '.join(keys + notes)[:900] or '(no summary line found)'
    if status == 0:
        print('::notice title=%s passed::%s' % (title, esc(summary)))
        return
    blocks = []
    # unittest failures: "FAIL: name" / "ERROR: name" followed by the traceback.
    for m in re.finditer(r'^(FAIL|ERROR): (.+?)\n-+\n(.*?)(?=\n=+\n|\n-+\nRan )', text, re.S | re.M):
        tb = m.group(3).strip().splitlines()
        blocks.append('%s %s: %s' % (m.group(1), m.group(2), ' / '.join(tb[-4:])))
    # PowerShell suite: "  FAIL name" + "       last output: ...".
    for m in re.finditer(r'^\s*FAIL (.+)\n(?:\s*last output: (.*))?', text, re.M):
        blocks.append('FAIL %s: %s' % (m.group(1).strip(), (m.group(2) or '').strip()))
    # node --test: "✖ name" lines.
    for m in re.finditer(r'^\s*✖ (.+)$', text, re.M):
        blocks.append('FAIL %s' % m.group(1).strip())
    for b in blocks[:9]:
        print('::error title=%s::%s' % (title, esc(b[:900])))
    print('::error title=%s failed::%s' % (title, esc(summary)))


if __name__ == '__main__':
    main()
