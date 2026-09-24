"""Scan local git repositories for one developer's commits in a date range.

Emits normalized timesheet events as JSON on stdout, so the model never has to
hand-parse `git log` output (where subjects contain commas, newlines and the
occasional separator character) or do calendar arithmetic across timezone
offsets by eye.

Two deliberate choices worth knowing about:

* `git log --since/--until` filters on *committer* date, which a rebase,
  cherry-pick or squash rewrites. A timesheet cares about when the work was
  authored, so this script asks git for a padded window and then filters
  precisely on the rendered *author* date.
* The rendered date/time is the calendar date in the machine's own timezone by
  default (`--tz local`). That is the convention every source in this skill
  follows, so a commit and a code review from the same evening land on the same
  day. `--tz commit` renders in the commit's own recorded offset instead --
  the wall clock the developer saw, which differs only when commits were made
  from another timezone.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# Field/record separators that will not appear in commit metadata.
US = "\x1f"
RS = "\x1e"

PRETTY = US.join(["%H", "%h", "%aI", "%an", "%ae", "%S", "%s", "%b"]) + RS

# Matches "ABC-123" style keys. Requires 2+ leading alphanumerics so the generic
# form does not swallow "v-2"; it still cannot tell a real key from "UTF-8",
# which is why --ticket-prefix exists.
DEFAULT_TICKET_PATTERN = r"\b[A-Z][A-Z0-9]{1,9}-\d+\b"

ISO = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})"
    r"(?:Z|([+-])(\d{2}):?(\d{2}))$"
)


class GitError(RuntimeError):
    pass


def parse_iso(stamp):
    """Parse git's %aI (strict ISO 8601) into an offset-aware datetime."""
    m = ISO.match(stamp.strip())
    if not m:
        raise ValueError("unparseable git timestamp: %r" % stamp)
    year, month, day, hour, minute, second = (int(g) for g in m.groups()[:6])
    sign, off_h, off_m = m.group(7), m.group(8), m.group(9)
    if sign is None:
        tz = timezone.utc
    else:
        delta = timedelta(hours=int(off_h), minutes=int(off_m))
        tz = timezone(-delta if sign == "-" else delta)
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


def render(dt, tz_mode):
    """Return (date, time) strings for a commit, in the requested timezone."""
    if tz_mode == "local":
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def build_ticket_pattern(prefixes, explicit):
    if explicit:
        return re.compile(explicit, re.IGNORECASE)
    if prefixes:
        keys = "|".join(re.escape(p.upper()) for p in prefixes)
        return re.compile(r"\b(?:%s)-\d+\b" % keys, re.IGNORECASE)
    return re.compile(DEFAULT_TICKET_PATTERN)


def extract_tickets(pattern, *texts):
    found = []
    for text in texts:
        for match in pattern.finditer(text or ""):
            key = match.group(0).upper()
            if key not in found:
                found.append(key)
    return found


def short_branch(source_ref):
    """Turn git's %S ref into a readable branch name, or None for a bare SHA."""
    ref = (source_ref or "").strip()
    if not ref or ref == "HEAD":
        return None
    for prefix in ("refs/heads/", "refs/remotes/", "refs/tags/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
            break
    # A detached traversal reports the commit id itself; that is not a branch.
    if re.fullmatch(r"[0-9a-f]{7,40}", ref):
        return None
    return ref or None


def parse_log(raw):
    """Split `git log` output on our separators into field tuples."""
    records = []
    for chunk in raw.split(RS):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split(US)
        if len(fields) < 8:
            fields += [""] * (8 - len(fields))
        records.append(fields[:8])
    return records


def run_git(repo, args):
    try:
        proc = subprocess.run(
            ["git", "-C", repo] + args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise GitError("git executable not found on PATH")
    if proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout or "").strip() or "git failed")
    return proc.stdout


def expand_user(path):
    """Expand a leading `~` to the user's home directory.

    Deliberately narrower than os.path.expanduser, which also resolves
    `~otheruser`: Node has no equivalent, and the two script twins have to agree
    on every input. Repo paths come from a config file as often as a shell, so
    nothing else would expand the `~`.
    """
    if not path:
        return path
    text = str(path)
    if text == "~":
        return os.path.expanduser("~")
    if text.startswith("~/") or text.startswith("~\\"):
        return os.path.join(os.path.expanduser("~"), text[2:])
    return text


def pad(date_str, days):
    d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def repo_name(path):
    return os.path.basename(os.path.abspath(path.rstrip("/\\"))) or path


def collect_repo(repo, opts, pattern):
    """Return normalized events for one repository."""
    args = [
        "log",
        "--source",
        "--all" if opts.all_branches else "--branches",
        "--date-order",
        "--since=" + pad(opts.since, -opts.pad_days),
        "--until=" + pad(opts.until, opts.pad_days + 1),
        "--pretty=format:" + PRETTY,
    ]
    if not opts.include_merges:
        args.append("--no-merges")
    for author in opts.author:
        args.append("--author=" + author)

    events = []
    name = opts.repo_name or repo_name(repo)
    for sha, short_sha, stamp, an, ae, source_ref, subject, body in parse_log(
        run_git(repo, args)
    ):
        try:
            authored = parse_iso(stamp)
        except ValueError:
            continue
        date, time = render(authored, opts.tz)
        if date < opts.since or date > opts.until:
            continue
        branch = short_branch(source_ref)
        events.append(
            {
                "timestamp": authored.isoformat(),
                "date": date,
                "time": time,
                "source": "local-git",
                "type": "commit",
                "repo": name,
                "ref": short_sha or sha[:9],
                "branch": branch,
                "ticket_ids": extract_tickets(pattern, subject, body, branch),
                "subject": subject,
                "author": ("%s <%s>" % (an, ae)).strip(),
                "url": None,
            }
        )
    return events


def dedupe(events):
    """Drop commits seen twice -- the same repo passed twice on the command
    line stops double-counting; the same work cherry-picked into two different
    repos legitimately stays."""
    seen = set()
    out = []
    for event in events:
        key = (event["repo"], event["ref"], event["timestamp"])
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


def build_parser():
    p = argparse.ArgumentParser(
        description="Collect local git commits as normalized timesheet events."
    )
    p.add_argument("--repo", action="append", default=[], required=True,
                   help="path to a local git repository (repeatable)")
    p.add_argument("--since", required=True, help="first day of the range, YYYY-MM-DD")
    p.add_argument("--until", required=True, help="last day of the range, inclusive")
    p.add_argument("--author", action="append", default=[],
                   help="git author pattern: name, email or substring (repeatable, OR'd)")
    p.add_argument("--ticket-prefix", action="append", default=[],
                   help="project key such as ABC; restricts ticket matching (repeatable)")
    p.add_argument("--ticket-pattern", default=None,
                   help="explicit regex for ticket ids; overrides --ticket-prefix")
    p.add_argument("--tz", choices=["commit", "local"], default="local",
                   help="render dates in the machine's timezone (default) or the commit's own offset")
    p.add_argument("--all-branches", dest="all_branches", action="store_true", default=True,
                   help="traverse all refs including remotes (default)")
    p.add_argument("--local-branches", dest="all_branches", action="store_false",
                   help="traverse local branches only")
    p.add_argument("--include-merges", action="store_true",
                   help="keep merge commits (skipped by default)")
    p.add_argument("--pad-days", type=int, default=7,
                   help="committer-date padding around the range (default 7)")
    p.add_argument("--repo-name", default=None,
                   help="label to use instead of the directory name (single --repo only)")
    p.add_argument("--out", default=None, help="write JSON here instead of stdout")
    return p


def main(argv):
    opts = build_parser().parse_args(argv)
    if opts.repo_name and len(opts.repo) > 1:
        sys.exit("--repo-name applies to a single --repo")
    if opts.since > opts.until:
        sys.exit("--since must not be after --until")

    pattern = build_ticket_pattern(opts.ticket_prefix, opts.ticket_pattern)
    events, skipped = [], []
    for repo in [expand_user(r) for r in opts.repo]:
        if not os.path.isdir(repo):
            skipped.append({"repo": repo, "reason": "path does not exist"})
            continue
        try:
            events.extend(collect_repo(repo, opts, pattern))
        except GitError as exc:
            skipped.append({"repo": repo, "reason": str(exc)})

    events = dedupe(events)
    events.sort(key=lambda e: (e["date"], e["time"], e["repo"], e["ref"]))
    payload = {"events": events, "skipped": skipped}
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if opts.out:
        target = expand_user(opts.out)
        parent = os.path.dirname(os.path.abspath(target))
        try:
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError as exc:
            sys.exit("cannot write %s: %s" % (target, exc.strerror or exc))
        print("%d event(s) written to %s" % (len(events), target))
    else:
        print(text)
    for entry in skipped:
        print("warning: skipped %s (%s)" % (entry["repo"], entry["reason"]), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
