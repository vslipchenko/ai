"""Turn a raw Jira history bundle into the git-log style HTML page.

Everything that must not vary between runs lives here: classifying each
changelog item into an activity type, repairing broken characters, diffing
text fields, converting ADF to wiki markup, ordering entries and deciding
which ones are automation. The template only renders what this script decides.

Mirrors build_history.mjs rule-for-rule, so a page built by either runtime is
byte-identical. Standard library only.

Input is a bundle as written by fetch_history (or assembled by the model from
an MCP); see references/fetching.md for its schema.
"""

import calendar
import json
import os
import re
import sys
import time

MODEL_VERSION = 1
TYPES = [
    "status", "assignee", "description", "title", "fields",
    "comments", "links", "weblinks", "attachments", "worklogs",
]

# Whitespace set spelled out so JS and Python agree on what a "word" and a
# "blank line" are (their built-in \s classes differ at the edges).
WS = "[ \\t\\n\\r\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]"
WS_SPLIT = re.compile("(" + WS + "+)")
WS_TRAIL = re.compile(WS + "+$")
WS_LEAD = re.compile("^" + WS + "+")
WS_ONLY = re.compile("^" + WS + "*$")

# Guards against quadratic blow-ups on huge fields. Past these sizes a diff
# degrades to "whole line/field replaced" -- still correct, just coarser.
MAX_LINE_CELLS = 4000000
MAX_WORD_CELLS = 1000000

# ------------------------------------------------------------------ mojibake --
# UTF-8 text that was decoded as Windows-1252 before Jira stored it ("—" kept
# as "â€”"). A run is rewritten only when re-encoding it as cp1252 yields one
# valid UTF-8 character, so genuine text such as "Â" or "naïve" is untouched.
CP1252_HIGH = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85, 0x2020: 0x86,
    0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C,
    0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95,
    0x2013: 0x96, 0x2014: 0x97, 0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B,
    0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F,
}
_CONT = "\\u0080-\\u00bf" + "".join("\\u%04x" % c for c in CP1252_HIGH)
MOJIBAKE = re.compile("[\\u00c2-\\u00f4][" + _CONT + "]{1,3}")


def repair_mojibake(s):
    if not isinstance(s, str):
        return s, []
    fixed = []

    def fix(m):
        run = m.group(0)
        data = bytes(ord(ch) if ord(ch) < 0x100 else CP1252_HIGH[ord(ch)] for ch in run)
        try:
            out = data.decode("utf-8")
        except UnicodeDecodeError:
            return run
        if len(out) != 1:
            return run
        fixed.append((run, out))
        return out

    return MOJIBAKE.sub(fix, s), fixed


def repair(s):
    return repair_mojibake(s)[0]


def encoding_seen(s):
    seen = []
    for bad, good in repair_mojibake(s)[1]:
        label = "%s → %s" % (bad, good)
        if label not in seen:
            seen.append(label)
    return seen


# --------------------------------------------------------------- wiki markup --
# Jira escapes punctuation with a backslash when it converts editor content to
# wiki markup. For display we drop escapes that carry no formatting meaning;
# \* and \_ stay so the renderer keeps them literal instead of emphasising.
ESC_DISPLAY = re.compile(r"\\([-()+!\[\]{}.#|~^])")
ESC_ALL = re.compile(r"\\([-()+!\[\]{}.#|~^*_])")


def unescape_display(s):
    return ESC_DISPLAY.sub(r"\1", s)


def unescape_all(s):
    return ESC_ALL.sub(r"\1", s)


def _attr(node, name):
    attrs = node.get("attrs") or {}
    return attrs.get(name)


def adf_to_wiki(doc):
    """ADF (Atlassian Document Format) -> wiki markup, so both storage formats
    diff and render through one path."""
    out = []

    def inline(node):
        parts = []
        for c in node.get("content") or []:
            t = c.get("type")
            if t == "hardBreak":
                parts.append("\n")
            elif t == "mention":
                parts.append("@" + re.sub(r"^@", "", str(_attr(c, "text") or "")))
            elif t == "emoji":
                parts.append(_attr(c, "text") or _attr(c, "shortName") or "")
            elif t in ("inlineCard", "blockCard"):
                parts.append(_attr(c, "url") or "")
            elif t == "status":
                parts.append("[%s]" % (_attr(c, "text") or ""))
            elif t == "date":
                parts.append(_attr(c, "timestamp") or "")
            elif t in ("media", "mediaInline"):
                parts.append("[image]")
            elif t != "text":
                parts.append(inline(c))
            else:
                s = c.get("text") or ""
                for m in c.get("marks") or []:
                    mt = m.get("type")
                    if mt == "strong":
                        s = "*%s*" % s
                    elif mt == "em":
                        s = "_%s_" % s
                    elif mt == "code":
                        s = "{{%s}}" % s
                    elif mt == "strike":
                        s = "-%s-" % s
                    elif mt == "underline":
                        s = "+%s+" % s
                    elif mt == "link" and (m.get("attrs") or {}).get("href"):
                        s = "[%s|%s]" % (s, m["attrs"]["href"])
                parts.append(s)
        return "".join(parts)

    def block(node, prefix):
        for c in node.get("content") or []:
            t = c.get("type")
            if t == "heading":
                out.append("h%s. %s" % (_attr(c, "level") or 1, inline(c)))
            elif t == "paragraph":
                out.append((prefix + " " if prefix else "") + inline(c))
            elif t in ("bulletList", "orderedList"):
                mark = "*" if t == "bulletList" else "#"
                for li in c.get("content") or []:
                    block(li, (prefix or "") + mark)
            elif t == "listItem":
                block(c, prefix)
            elif t == "codeBlock":
                out.append("{code}")
                out.append(inline(c))
                out.append("{code}")
            elif t == "blockquote":
                for p in c.get("content") or []:
                    out.append("bq. " + inline(p))
            elif t == "rule":
                out.append("----")
            elif t == "table":
                for row in c.get("content") or []:
                    cells = [
                        {"head": cell.get("type") == "tableHeader",
                         "text": " ".join(inline(x) for x in cell.get("content") or [])}
                        for cell in row.get("content") or []
                    ]
                    head = len(cells) > 0 and all(x["head"] for x in cells)
                    if head:
                        out.append("||" + "||".join(x["text"] for x in cells) + "||")
                    else:
                        out.append("|" + "|".join(x["text"] for x in cells) + "|")
            elif t in ("mediaSingle", "mediaGroup"):
                out.append("[image]")
            else:
                block(c, prefix)

    block(doc, "")
    return "\n\n".join(out)


_ADF_START = re.compile(r'^\s*\{\s*"type"\s*:\s*"doc"')


def parse_adf(value):
    if isinstance(value, dict):
        return value if value.get("type") == "doc" else None
    if not isinstance(value, str) or not _ADF_START.match(value):
        return None
    for candidate in (value, unescape_all(value)):
        try:
            doc = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("type") == "doc":
            return doc
    return None


def to_wiki(value):
    """Raw field value -> wiki text (mojibake repaired, ADF converted)."""
    if value is None:
        return ""
    doc = parse_adf(value)
    if doc is not None:
        return repair(adf_to_wiki(doc))
    return repair(str(value))


def split_lines(text):
    return [l for l in (WS_TRAIL.sub("", x) for x in text.split("\n")) if not WS_ONLY.match(l)]


# ---------------------------------------------------------------------- diff --
def lcs_ops(a, b):
    n, m = len(a), len(b)
    if n * m > MAX_LINE_CELLS:
        return [["-", x] for x in a] + [["+", x] for x in b]
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, below = dp[i], dp[i + 1]
        ai = a[i]
        for j in range(m - 1, -1, -1):
            if ai == b[j]:
                row[j] = below[j + 1] + 1
            else:
                x, y = below[j], row[j + 1]
                row[j] = x if x >= y else y
    ops = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            ops.append(["=", a[i]])
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append(["-", a[i]])
            i += 1
        else:
            ops.append(["+", b[j]])
            j += 1
    while i < n:
        ops.append(["-", a[i]])
        i += 1
    while j < m:
        ops.append(["+", b[j]])
        j += 1
    return ops


def word_diff(a, b):
    """Word-level segments for a changed pair: [["=", text] | ["x", text], ...]."""
    ta, tb = WS_SPLIT.split(a), WS_SPLIT.split(b)
    if len(ta) * len(tb) > MAX_WORD_CELLS:
        return {"del": [["x", a]] if a else [], "add": [["x", b]] if b else []}
    ops = lcs_ops(ta, tb)

    def side(keep):
        out = []
        for k, t in ops:
            if k != "=" and k != keep:
                continue
            if t == "":
                continue
            kind = "=" if k == "=" else "x"
            if out and out[-1][0] == kind:
                out[-1][1] += t
            else:
                out.append([kind, t])
        return out

    return {"del": side("-"), "add": side("+")}


def text_diff(from_raw, to_raw):
    """Multi-line text diff: collapsed hunks, the full "after" text with change
    marks, and which side carried broken characters."""
    from_wiki, to_wiki_text = to_wiki(from_raw), to_wiki(to_raw)
    a = split_lines(unescape_display(from_wiki))
    b = split_lines(unescape_display(to_wiki_text))
    ops = lcs_ops(a, b)
    lines = []
    k = 0
    while k < len(ops):
        if ops[k][0] != "-":
            lines.append({"k": ops[k][0], "t": ops[k][1]})
            k += 1
            continue
        dels, adds = [], []
        while k < len(ops) and ops[k][0] == "-":
            dels.append(ops[k][1])
            k += 1
        while k < len(ops) and ops[k][0] == "+":
            adds.append(ops[k][1])
            k += 1
        pairs = min(len(dels), len(adds))
        wd = [word_diff(dels[i], adds[i]) for i in range(pairs)]
        for i, t in enumerate(dels):
            lines.append({"k": "-", "t": t, "w": wd[i]["del"]} if i < pairs else {"k": "-", "t": t})
        for i, t in enumerate(adds):
            lines.append({"k": "+", "t": t, "w": wd[i]["add"]} if i < pairs else {"k": "+", "t": t})

    def near(j):
        return 0 <= j < len(lines) and lines[j]["k"] != "="

    hunks = []
    skipped = 0
    for i, l in enumerate(lines):
        if l["k"] != "=" or near(i - 1) or near(i + 1):
            if skipped:
                hunks.append({"k": "~", "n": skipped})
            skipped = 0
            hunks.append(l)
        else:
            skipped += 1
    if skipped:
        hunks.append({"k": "~", "n": skipped})
    full = [l for l in lines if l["k"] != "-"]
    add = len([l for l in lines if l["k"] == "+"])
    dele = len([l for l in lines if l["k"] == "-"])
    same = "\n".join(split_lines(unescape_all(from_wiki))) == "\n".join(split_lines(unescape_all(to_wiki_text)))
    return {
        "add": 0 if same else add,
        "del": 0 if same else dele,
        "hunks": [] if same else hunks,
        "full": full,
        "markup_only": same,
        "adf": bool(parse_adf(from_raw) or parse_adf(to_raw)),
        "encoding": {"before": encoding_seen(from_raw), "after": encoding_seen(to_raw)},
    }


# ---------------------------------------------------------------- timestamps --
TS = re.compile(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$")


def to_epoch_ms(ts):
    m = TS.match(str(ts or ""))
    if not m:
        return None
    y, mo, d, h, mi, s, frac, zone = m.groups()
    ms = int((frac + "00")[:3]) if frac else 0
    off_min = 0
    if zone and zone != "Z":
        z = zone.replace(":", "")
        off_min = (-1 if z[0] == "-" else 1) * (int(z[1:3]) * 60 + int(z[3:5]))
    secs = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(s), 0, 0, 0))
    return secs * 1000 + ms - off_min * 60000


def render_ts(ms, tz):
    """Render an instant in the machine's local zone ("local") or UTC ("utc")."""
    if ms is None:
        return None
    sec = ms // 1000
    if tz == "utc":
        st = time.gmtime(sec)
        off = 0
    else:
        st = time.localtime(sec)
        off = st.tm_gmtoff // 60
    sign = "-" if off < 0 else "+"
    a = abs(off)
    return "%04d-%02d-%02dT%02d:%02d:%02d%s%02d:%02d" % (
        st.tm_year, st.tm_mon, st.tm_mday, st.tm_hour, st.tm_min, st.tm_sec, sign, a // 60, a % 60)


# -------------------------------------------------------------- html -> text --
ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " "}


def _entity(m):
    e = m.group(1)
    if e[0] == "#":
        try:
            code = int(e[2:], 16) if e[1] in "xX" else int(e[1:], 10)
        except ValueError:
            return m.group(0)
        if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF:
            return chr(code)
        return m.group(0)
    v = ENTITIES.get(e.lower())
    return m.group(0) if v is None else v


def html_to_text(html):
    s = str(html or "")
    s = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|div|li|h[1-6]|tr|pre|blockquote)>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]*>", "", s)
    return re.sub(r"&(#x[0-9a-f]+|#\d+|[a-z]+);", _entity, s, flags=re.I)


def wiki_to_text(s):
    s = unescape_all(s)
    s = re.sub(r"\[~accountid:[^\]]+\]", "@user", s)
    s = re.sub(r"\[~([^\]]+)\]", r"@\1", s)
    s = re.sub(r"\[([^\]|]+)\|[^\]]+\]", r"\1", s)
    s = re.sub(r"\{\{|\}\}", "", s)
    s = re.sub(r"(^|\s)[*_](\S)", r"\1\2", s)
    return re.sub(r"(\S)[*_](?=\s|$|[.,:;!?)])", r"\1", s)


def first_line(text, width=80):
    line = ""
    for l in str(text or "").split("\n"):
        l = WS_LEAD.sub("", WS_TRAIL.sub("", l))
        if l != "":
            line = l
            break
    return line[:width - 2] + "…" if len(line) > width else line


# ------------------------------------------------------------ classification --
def id_of(u):
    return (u.get("accountId") or u.get("key") or u.get("name") or None) if u else None


def name_of(u):
    return (u.get("displayName") or u.get("name") or u.get("accountId") or "Unknown") if u else "Unknown"


def classify(item):
    """Map a changelog item to one of TYPES from Jira's own field identity only."""
    fid = str(item.get("fieldId") or "").lower()
    f = str(item.get("field") or "")
    key = fid or f.lower()
    if key == "status":
        return "status"
    if key == "assignee":
        return "assignee"
    if key == "description":
        return "description"
    if key == "summary":
        return "title"
    if f in ("Link", "IssueParentAssociation", "Parent") or key == "parent" or (f == "Epic Link" and not fid):
        return "links"
    if f in ("RemoteWorkItemLink", "RemoteIssueLink"):
        return "weblinks"
    if f == "Attachment" or key == "attachment":
        return "attachments"
    if f == "Comment" or key == "comment":
        return "comments"
    if f == "WorklogId" or key in ("timespent", "timeestimate", "timeoriginalestimate", "worklogtimespent"):
        return "worklogs"
    return "fields"


LABELS = {
    "status": "Status", "assignee": "Assignee", "reporter": "Reporter", "priority": "Priority",
    "summary": "Title", "description": "Description", "labels": "Labels", "issuetype": "Type",
    "resolution": "Resolution", "environment": "Environment", "duedate": "Due date",
    "components": "Component", "fixversions": "Fix version", "versions": "Affects version",
    "timespent": "Time spent", "timeestimate": "Remaining estimate", "timeoriginalestimate": "Original estimate",
    "worklogid": "Worklog", "link": "Issue link", "issueparentassociation": "Parent",
    "remoteworkitemlink": "Web link", "remoteissuelink": "Web link", "attachment": "Attachment",
    "comment": "Comment",
}


def label_of(item):
    fid = str(item.get("fieldId") or "").lower()
    f = str(item.get("field") or "")
    return LABELS.get(fid) or LABELS.get(f.lower()) or f or fid or "Field"


def clean_value(s):
    """Cascading selects log "Parent values: A(10)Level 1 values: B(11)" -- a
    Jira format, not a site convention -- so render it as "A / B"."""
    if s is None or s == "":
        return None
    v = repair(str(s))
    if v.startswith("Parent values: "):
        v = re.sub(r"^Parent values: ", "", v)
        v = v.replace("Level 1 values: ", " / ", 1)
        v = re.sub(r"\(\d+\)", "", v)
    return v


def is_multiline(item):
    key = str(item.get("fieldId") or item.get("field") or "").lower()
    if key in ("description", "environment"):
        return True
    for v in (item.get("fromString"), item.get("toString")):
        if isinstance(v, str) and ("\n" in v or parse_adf(v)):
            return True
    return False


PRIORITY = {"status": 0, "assignee": 1, "title": 2, "description": 3}


def to_change(item):
    cat = classify(item)
    label = label_of(item)
    field_id = str(item.get("fieldId") or item.get("field") or "")
    raw_from = None if item.get("fromString") is None else str(item["fromString"])
    raw_to = None if item.get("toString") is None else str(item["toString"])
    frm, to = clean_value(raw_from), clean_value(raw_to)
    base = {"cat": cat, "label": label, "field_id": field_id}

    if cat == "comments":
        change = dict(base, **{"from": None, "to": None})
        change["deleted"] = to_wiki(raw_from) if frm else None
        change["subject"] = "Delete comment" if frm and not to else "Change comment"
        return change
    if cat == "description" or (cat == "fields" and is_multiline(item)):
        diff = text_diff(raw_from, raw_to)
        name = "description" if cat == "description" else label
        enc = diff["encoding"]
        if diff["markup_only"]:
            if enc["before"] and not enc["after"]:
                subject = "Fix broken characters in %s" % name
            elif any(x not in enc["before"] for x in enc["after"]):
                subject = "Save %s with broken characters" % name
            else:
                subject = "Reformat %s (markup only)" % name
        elif not raw_from:
            subject = "Add %s" % name
        elif not raw_to:
            subject = "Clear %s" % name
        else:
            subject = "Edit %s (+%d −%d)" % (name, diff["add"], diff["del"])
        change = dict(base, **{"from": None, "to": None})
        change["diff"] = diff
        change["subject"] = subject
        return change
    if cat == "title":
        change = dict(base, **{"from": frm, "to": to})
        change["words"] = word_diff(frm or "", to or "")
        change["subject"] = "Rename ticket"
        return change
    if cat == "status":
        subject = "Move to %s" % (to or "(none)")
    elif cat == "assignee":
        subject = ("Assign to %s" % to) if to else ("Unassign %s" % (frm or "")).strip()
    elif cat in ("links", "weblinks"):
        subject = to if to else "Remove: %s" % (frm or "")
    elif cat == "attachments":
        subject = ("Attach %s" % to) if to else "Remove attachment %s" % (frm or "")
    elif field_id.lower() == "labels":
        a = [x for x in (frm or "").split(" ") if x]
        b = [x for x in (to or "").split(" ") if x]
        plus = ["+" + x for x in b if x not in a]
        minus = ["−" + x for x in a if x not in b]
        subject = ("Labels %s" % " ".join(plus + minus)).strip()
    elif not frm:
        subject = "Set %s to %s" % (label, to or "(empty)")
    elif not to:
        subject = "Clear %s" % label
    else:
        subject = "%s: %s → %s" % (label, frm, to)
    change = dict(base, **{"from": frm, "to": to})
    change["subject"] = subject
    if cat == "status":
        change["status"] = {"from": frm, "to": to}
    return change


# --------------------------------------------------------------------- build --
DEVSUMMARY = "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummarycf"


def dev_summary(issue):
    schema = issue.get("schema") or {}
    fields = issue.get("fields") or {}
    field_id = next((k for k in sorted(schema) if isinstance(schema[k], dict) and schema[k].get("custom") == DEVSUMMARY), None)
    if not field_id or not isinstance(fields.get(field_id), str):
        return None
    m = re.search(r"json=(\{.*\})\s*\}\s*$", fields[field_id])
    if not m:
        return None
    try:
        parsed = json.loads(m.group(1))
    except ValueError:
        return None
    s = (parsed.get("cachedValue") or {}).get("summary") or {}

    def o(k):
        return (s.get(k) or {}).get("overall") or None

    pr, build, dep, br, cm = o("pullrequest"), o("build"), o("deployment-environment"), o("branch"), o("repository")
    if not (pr or build or dep or br or cm):
        return None
    return {
        "branches": (br.get("count") or 0) if br else 0,
        "commits": (cm.get("count") or 0) if cm else 0,
        "pull_requests": (pr.get("count") or 0) if pr else 0,
        "pull_request_state": str(pr.get("state") or "") if pr else "",
        "builds": (build.get("count") or 0) if build else 0,
        "failed_builds": (build.get("failedBuildCount") or 0) if build else 0,
        "deployments": (dep.get("count") or 0) if dep else 0,
    }


def initial_value(changelog, field_key, current):
    for h in changelog:
        for it in h.get("items") or []:
            if str(it.get("fieldId") or it.get("field") or "").lower() == field_key:
                return None if it.get("fromString") is None else str(it["fromString"])
    return current


def comment_body(c):
    rendered = c.get("renderedBody")
    if isinstance(rendered, str) and rendered.strip():
        return {"format": "html", "text": repair(rendered)}
    fmt = c.get("body_format") or ("adf" if parse_adf(c.get("body")) is not None else "wiki")
    if fmt == "html":
        return {"format": "html", "text": repair(str(c.get("body") or ""))}
    return {"format": "wiki", "text": to_wiki(c.get("body"))}


def body_text(body):
    return html_to_text(body["text"]) if body["format"] == "html" else wiki_to_text(body["text"])


def _name_field(v):
    if isinstance(v, dict):
        return v.get("displayName") or v.get("name") or v.get("value") or None
    return None if v is None else str(v)


def _dumps(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def build_model(bundle, tz="local", automation_accounts=(), exclude_fields=(), types=None,
                order="desc", hide_automation=False):
    tz = "utc" if tz == "utc" else "local"
    automation = set(automation_accounts or [])
    exclude = set(str(x).lower() for x in (exclude_fields or []))
    issue = bundle.get("issue") or {}
    f = issue.get("fields") or {}
    site = re.sub(r"/+$", "", str(bundle.get("site") or ""))
    key = str(issue.get("key") or bundle.get("key") or "")

    def ms_or_zero(h):
        v = to_epoch_ms(h.get("created"))
        return 0 if v is None else v

    changelog = sorted(bundle.get("changelog") or [], key=lambda h: (ms_or_zero(h), str(h.get("id"))))
    warnings = []

    def is_bot(u):
        return bool(u and (u.get("accountType") == "app" or id_of(u) in automation))

    def ts(raw):
        return render_ts(to_epoch_ms(raw), tz)

    excluded = set()
    commits = []
    created = to_epoch_ms(f.get("created"))
    creator = f.get("creator") or f.get("reporter") or None
    created_changes = []

    def add(cat, label, field_key, value):
        if field_key in exclude or value is None or value == "":
            return
        created_changes.append({"cat": cat, "label": label, "field_id": field_key, "from": None, "to": clean_value(value)})

    def initial(k, cur):
        return initial_value(changelog, k, cur)

    add("fields", "Type", "issuetype", initial("issuetype", _name_field(f.get("issuetype"))))
    add("status", "Status", "status", initial("status", _name_field(f.get("status"))))
    add("fields", "Priority", "priority", initial("priority", _name_field(f.get("priority"))))
    add("assignee", "Assignee", "assignee", initial("assignee", _name_field(f.get("assignee"))))
    add("fields", "Reporter", "reporter", initial("reporter", _name_field(f.get("reporter"))))
    add("title", "Title", "summary", initial("summary", None if f.get("summary") is None else str(f.get("summary"))))
    # The first description edit's "from" is the original text (always
    # wiki/ADF). With no edits, the current value is original, in whatever
    # format the fetch path declared (REST v2 gives wiki; an MCP may give HTML).
    desc = f.get("description")
    current = None if desc is None else desc if isinstance(desc, str) else _dumps(desc)
    first_desc = initial("description", current)
    desc_html = first_desc == current and issue.get("description_format") == "html"
    if "description" not in exclude and first_desc:
        change = {"cat": "description", "label": "Description", "field_id": "description", "from": None, "to": None}
        if desc_html:
            change["initial_html"] = repair(first_desc)
        else:
            change["initial"] = split_lines(unescape_display(to_wiki(first_desc)))
        created_changes.append(change)
    if created is not None:
        commits.append({
            "id": "i" + str(issue.get("id") or key), "kind": "created", "ms": created, "ts": ts(f.get("created")),
            "author": name_of(creator), "author_id": id_of(creator), "bot": is_bot(creator),
            "subject": "Create %s" % key, "changes": created_changes,
        })

    for h in changelog:
        items = []
        for it in h.get("items") or []:
            k1 = str(it.get("fieldId") or "").lower()
            k2 = str(it.get("field") or "").lower()
            if k1 in exclude or k2 in exclude:
                excluded.add(label_of(it))
                continue
            items.append(it)
        if not items:
            continue
        indexed = list(enumerate(to_change(it) for it in items))
        indexed.sort(key=lambda p: (PRIORITY.get(p[1]["cat"], 9), p[0]))
        changes = [c for _, c in indexed]
        ms = to_epoch_ms(h.get("created"))
        if ms is None:
            warnings.append("Changelog entry %s has no readable date and was skipped." % h.get("id"))
            continue
        more = " (+%d more)" % (len(changes) - 1) if len(changes) > 1 else ""
        commit = {
            "id": str(h.get("id")), "kind": "history", "ms": ms, "ts": ts(h.get("created")),
            "author": name_of(h.get("author")), "author_id": id_of(h.get("author")), "bot": is_bot(h.get("author")),
            "subject": changes[0]["subject"] + more, "changes": changes,
        }
        st = next((c for c in changes if c.get("status")), None)
        if st:
            commit["transition"] = st["status"]
        commits.append(commit)

    if "comment" not in exclude:
        for c in bundle.get("comments") or []:
            ms = to_epoch_ms(c.get("created"))
            if ms is None:
                warnings.append("Comment %s has no readable date and was skipped." % c.get("id"))
                continue
            body = comment_body(c)
            commit = {
                "id": "c" + str(c.get("id")), "kind": "comment", "ms": ms, "ts": ts(c.get("created")),
                "author": name_of(c.get("author")), "author_id": id_of(c.get("author")), "bot": is_bot(c.get("author")),
                "subject": first_line(body_text(body)) or "Comment",
                "changes": [{"cat": "comments", "label": "Comment", "field_id": "comment", "from": None, "to": None}],
                "body": body,
            }
            upd = to_epoch_ms(c.get("updated")) if c.get("updated") else None
            if upd is not None and upd - ms >= 1000:
                commit["edited"] = ts(c.get("updated"))
            if c.get("parentId") is not None:
                commit["parent"] = "c" + str(c.get("parentId"))
            vis = c.get("visibility") or {}
            if vis.get("value"):
                commit["visibility"] = str(vis["value"])
            commits.append(commit)

    if "worklog" not in exclude:
        for w in bundle.get("worklogs") or []:
            when = w.get("created") or w.get("started")
            ms = to_epoch_ms(when)
            if ms is None:
                warnings.append("Worklog %s has no readable date and was skipped." % w.get("id"))
                continue
            spent = str(w.get("timeSpent") or "")
            commit = {
                "id": "w" + str(w.get("id")), "kind": "worklog", "ms": ms, "ts": ts(when),
                "author": name_of(w.get("author")), "author_id": id_of(w.get("author")), "bot": is_bot(w.get("author")),
                "subject": "Log %s" % (spent or "time"),
                "changes": [{"cat": "worklogs", "label": "Time spent", "field_id": "worklog", "from": None, "to": spent or None}],
            }
            if w.get("started"):
                commit["started"] = ts(w.get("started"))
            if w.get("comment"):
                commit["body"] = {"format": "wiki", "text": to_wiki(w.get("comment"))}
            upd = to_epoch_ms(w.get("updated")) if w.get("updated") else None
            if upd is not None and upd - ms >= 1000:
                commit["edited"] = ts(w.get("updated"))
            commits.append(commit)

    kind_order = {"created": 0, "history": 1, "comment": 2, "worklog": 3}
    commits.sort(key=lambda c: (c["ms"], kind_order[c["kind"]], c["id"]))
    for c in commits:
        del c["ms"]

    completeness = bundle.get("completeness") or {}
    fetch = []
    for source, what in (("changelog", "Changelog entries"), ("comments", "Comments"), ("worklogs", "Worklogs")):
        cinfo = completeness.get(source)
        got = len(bundle.get(source) or [])
        if not cinfo:
            fetch.append({"what": what, "got": got, "total": None, "pages": None, "complete": False})
            warnings.append("%s: the bundle does not say whether every page was fetched." % what)
            continue
        total = None if cinfo.get("total") is None else int(cinfo["total"])
        complete = cinfo.get("complete") is not False and total is not None and got >= total
        fetch.append({"what": what, "got": got, "total": total,
                      "pages": None if cinfo.get("pages") is None else int(cinfo["pages"]), "complete": complete})
        if not complete:
            warnings.append("%s: fetched %d of %s. This history is incomplete." % (
                what, got, "an unknown number" if total is None else total))
    for e in bundle.get("errors") or []:
        warnings.append("%s: %s" % (e.get("source"), e.get("message")))

    parent_f = f.get("parent")
    parent = None
    if parent_f:
        parent = {"key": str(parent_f.get("key") or ""),
                  "summary": repair(str((parent_f.get("fields") or {}).get("summary") or ""))}

    return {
        "model_version": MODEL_VERSION,
        "site": site,
        "fetched_at": ts(bundle.get("fetched_at")) if bundle.get("fetched_at") else None,
        "ticket": {
            "key": key, "url": "%s/browse/%s" % (site, key) if site else "",
            "summary": repair(str(f.get("summary") or "")),
            "type": _name_field(f.get("issuetype")), "status": _name_field(f.get("status")),
            "priority": _name_field(f.get("priority")),
            "assignee": name_of(f["assignee"]) if f.get("assignee") else None,
            "reporter": name_of(f["reporter"]) if f.get("reporter") else None,
            "parent": parent,
            "created": ts(f.get("created")), "updated": ts(f.get("updated")),
        },
        "dev": dev_summary(issue),
        "defaults": {
            "types": [t for t in TYPES if t in (types or TYPES)],
            "order": "asc" if order == "asc" else "desc",
            "hide_automation": bool(hide_automation),
        },
        "excluded_fields": sorted(excluded),
        "fetch": fetch,
        "warnings": warnings,
        "commits": commits,
    }


def to_json(model):
    return _dumps(model).replace("<", "\\u003c")


def _esc_html(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def render_page(template, model):
    marker = "/*__DATA__*/null"
    at = template.find(marker)
    if at < 0:
        raise ValueError("template has no /*__DATA__*/null placeholder")
    title = _esc_html("%s History" % model["ticket"]["key"])
    head = template[:at].replace("__TITLE__", title)
    return head + to_json(model) + template[at + len(marker):]


# ----------------------------------------------------------------------- cli --
def parse_args(argv):
    a = {"bundle": None, "config": None, "template": None, "out": None, "tz": None,
         "types": None, "order": None, "hide_automation": None}
    i = 0
    while i < len(argv):
        k = argv[i]

        def nxt():
            if i + 1 >= len(argv):
                raise ValueError("%s needs a value" % k)
            return argv[i + 1]

        if k in ("--bundle", "--config", "--template", "--out", "--tz", "--order"):
            a[k[2:]] = nxt()
            i += 1
        elif k == "--types":
            a["types"] = [s.strip() for s in nxt().split(",") if s.strip()]
            i += 1
        elif k == "--hide-automation":
            a["hide_automation"] = True
        elif k == "--show-automation":
            a["hide_automation"] = False
        else:
            raise ValueError("unknown argument %s" % k)
        i += 1
    if not a["bundle"]:
        raise ValueError("--bundle is required")
    if a["tz"] and a["tz"] not in ("local", "utc"):
        raise ValueError("--tz must be local or utc")
    if a["order"] and a["order"] not in ("asc", "desc"):
        raise ValueError("--order must be asc or desc")
    for t in a["types"] or []:
        if t not in TYPES:
            raise ValueError("unknown type %s; expected one of %s" % (t, ",".join(TYPES)))
    return a


def expand_user(p):
    return os.path.expanduser(p) if p else p


def load_config(p):
    path = expand_user(p or "~/.jira-ticket-history/config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        if p:
            raise ValueError("cannot read config %s: %s" % (path, e))
        return {}


def main(argv):
    try:
        args = parse_args(argv)
        cfg = load_config(args["config"])
    except ValueError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1
    hist, out = cfg.get("history") or {}, cfg.get("output") or {}
    if args["bundle"] == "-":
        bundle = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    else:
        with open(expand_user(args["bundle"]), encoding="utf-8") as fh:
            bundle = json.load(fh)
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = expand_user(args["template"]) or os.path.join(here, "..", "assets", "template.html")
    with open(tpl, encoding="utf-8", newline="") as fh:
        template = fh.read()
    model = build_model(
        bundle,
        tz=args["tz"] or out.get("timezone") or "local",
        automation_accounts=cfg.get("automation_accounts") or [],
        exclude_fields=hist.get("exclude_fields") or [],
        types=args["types"] or hist.get("types") or TYPES,
        order=args["order"] or out.get("order") or "desc",
        hide_automation=args["hide_automation"] if args["hide_automation"] is not None else bool(out.get("hide_automation")),
    )
    html = render_page(template, model)
    target = expand_user(args["out"]) or "%s-history.html" % (model["ticket"]["key"] or "ticket")
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(html)
    for w in model["warnings"]:
        sys.stderr.write("warning: %s\n" % w)
    sys.stdout.write(_dumps({"out": os.path.abspath(target), "entries": len(model["commits"]),
                             "fetch": model["fetch"], "warnings": model["warnings"]}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
