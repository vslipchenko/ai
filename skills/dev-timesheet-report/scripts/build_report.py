"""Turn normalized timesheet events into a terminal table or a CSV file.

Everything downstream of collection is deterministic and lives here: activity
labelling (first matching rule wins), collapsing many events into one row per
date/ticket/activity, column selection, sorting, and RFC 4180 CSV quoting. The
model's job is to gather events and ticket titles; this script decides what a
row is, so the same events always render the same report.

Input is a single JSON document:

    {
      "events": [ {...}, ... ],
      "ticket_titles": {"ABC-1234": "Fix login redirect loop"}
    }

A bare JSON array of events is accepted too. See references/config.md for the
event and rule schemas.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

KNOWN_WHEN_FIELDS = {
    "type",
    "source",
    "repo",
    "branch",
    "subject_matches",
    "status_to",
    "ticket_type",
    "ticket_ids",
}

DEFAULT_COLUMNS = ["date", "day", "item_type", "id", "title", "activity"]
ALL_COLUMNS = [
    "date",
    "day",
    "time",
    "item_type",
    "ticket_type",
    "id",
    "title",
    "activity",
    "source",
    "repo",
    "url",
    "evidence",
]

# Looser spellings accepted in `output.columns` and --columns. Note `type`
# points at ticket_type, matching its "Type" header; the Jira/Confluence
# column is `item_type`, headed "System".
COLUMN_ALIASES = {
    "ticket_id": "id",
    "ticket": "id",
    "type": "ticket_type",
    "issue_type": "ticket_type",
    "system": "item_type",
}

# Terminal output prints these as the group heading rather than as columns.
HEADING_COLUMNS = ("date", "day")

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Byte-order mark, written via chr() so the source carries no invisible
# character. Excel needs it to read a UTF-8 CSV as UTF-8.
BOM = chr(0xFEFF)

# Which system the `id` lives in -- not where the evidence came from. A commit
# on ABC-1234 is item_type "jira" because its id is a Jira key, while the
# `source` column says the evidence was a commit.
ITEM_TYPE_LABELS = {"jira": "Jira", "confluence": "Confluence"}
ITEM_TYPE_ORDER = {"Jira": 0, "Confluence": 1}

HEADERS = {
    "date": "Date",
    "day": "Day",
    "time": "Time",
    "item_type": "System",
    "ticket_type": "Type",
    "id": "Id",
    "title": "Title",
    "activity": "Activity",
    "source": "Source",
    "repo": "Repo",
    "url": "URL",
    "evidence": "Events",
}


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def lower_all(values):
    return [str(v).lower() for v in values]


def item_type_for(event):
    """Display name for the kind of item an event's ids refer to."""
    raw = str(event.get("item_type") or "jira").strip().lower()
    # Capitalize the first letter only -- str.title() would render "my type" as
    # "My Type" while the Node twin produces "My type".
    return ITEM_TYPE_LABELS.get(raw, raw[:1].upper() + raw[1:])


def item_type_rank(value):
    """Jira first, then Confluence, then anything else, then untyped rows.
    Without this, mixed ids sort meaninglessly -- a numeric Confluence page id
    lands among the ABC-123 keys purely because digits precede letters."""
    if not value:
        return 3
    return ITEM_TYPE_ORDER.get(value, 2)


def weekday(date_str):
    """Short day name for a YYYY-MM-DD string, or "" if it is not a real date.

    Deliberately a fixed ASCII table rather than strftime("%a"), which is
    locale-dependent -- it would render "Di" on a German machine and disagree
    with the Node twin.
    """
    try:
        parsed = datetime.strptime(str(date_str), "%Y-%m-%d")
    except (ValueError, TypeError):
        return ""
    return WEEKDAYS[parsed.weekday()]


def earliest(a, b):
    """Earliest of two HH:MM strings, ignoring empties -- a blank time means
    'unknown', not midnight."""
    times = [t for t in (a, b) if t]
    return min(times) if times else ""


def match_rule(event, when, warn):
    """True when every condition in `when` holds. Conditions AND together;
    a list of values inside one condition ORs."""
    for field, expected in when.items():
        if field == "subject_matches":
            if not re.search(str(expected), event.get("subject") or "", re.IGNORECASE):
                return False
            continue
        if field not in KNOWN_WHEN_FIELDS:
            warn("rule condition %r is not a recognized field; it can never match" % field)
            return False
        actual = lower_all(as_list(event.get(field)))
        if not actual:
            return False
        if not set(actual) & set(lower_all(as_list(expected))):
            return False
    return True


def label_for(event, rules, default_activity, warn):
    """Return the activity label for an event, or None to drop it entirely.

    An event may carry an explicit activity (a correction the user made, or an
    adapter that already knows); that beats rule inference, including a drop
    rule -- pinning a label is always deliberate.

    A rule with `"drop": true` suppresses the event instead of labelling it.
    That is how bookkeeping events stay out of the report: assigning a ticket
    or moving it to Done is a record *about* work, not work, and giving it a
    row would say "Other" where nothing happened.
    """
    explicit = event.get("activity")
    if explicit:
        return str(explicit)
    for rule in rules:
        if match_rule(event, rule.get("when") or {}, warn):
            if rule.get("drop"):
                return None
            if not rule.get("label"):
                warn("rule matched but has neither a label nor drop: true; "
                     "using the default activity")
            return str(rule.get("label") or default_activity)
    return default_activity


def dedupe_events(events):
    """Drop the same commit when two sources both reported it.

    A commit present in the local clone and also returned by a code host would
    otherwise merge into one row carrying `evidence: 2` and both source names,
    as though two separate things had happened. Identity is the commit ref;
    the local-git copy wins because it carries the true author date, where a
    host may only expose the committer date.

    Only `commit` events with a ref are considered -- a PR review and a commit
    are genuinely different work even on the same ticket.
    """
    index = {}
    out = []
    for event in events:
        ref = str(event.get("ref") or "")
        if str(event.get("type") or "") != "commit" or not ref:
            out.append(event)
            continue
        if ref not in index:
            index[ref] = len(out)
            out.append(event)
        elif event.get("source") == "local-git" and out[index[ref]].get("source") != "local-git":
            out[index[ref]] = event
    return out


def expand(events, config, warn):
    """One event becomes one row per ticket it touches."""
    output = config.get("output") or {}
    rules = config.get("activity_rules") or []
    default_activity = config.get("default_activity") or "Other"
    untracked = output.get("untracked", "include")
    placeholder = output.get("untracked_placeholder", "(no ticket)")
    if untracked not in ("include", "omit", "group"):
        warn("output.untracked %r is not include/omit/group; using include" % untracked)
        untracked = "include"

    rows = []
    undated = 0
    for event in events:
        # weekday() returns "" for anything that is not a real YYYY-MM-DD date,
        # which makes it the validity check too. A row with no usable date
        # cannot be placed in a timesheet, and because dates sort as strings a
        # malformed one would also silently misorder the report -- so drop it
        # and say so, rather than rendering a group under a blank heading.
        if not weekday(event.get("date")):
            undated += 1
            continue
        activity = label_for(event, rules, default_activity, warn)
        if activity is None:
            continue
        item_type = item_type_for(event)
        tickets = [t for t in as_list(event.get("ticket_ids")) if t]
        if not tickets:
            if untracked == "omit":
                continue
            tickets = [placeholder]
            # Nothing to type when there is no item behind the row.
            item_type = ""
        for ticket in tickets:
            rows.append(
                {
                    "date": event.get("date") or "",
                    "time": event.get("time") or "",
                    "item_type": item_type,
                    "ticket_type": str(event.get("ticket_type") or ""),
                    "id": str(ticket),
                    "activity": activity,
                    "source": event.get("source") or "",
                    "repo": event.get("repo") or "",
                    "url": event.get("url") or "",
                    "untracked": ticket == placeholder,
                    # A ticketless row has no board title to look up, but the
                    # commit subject says what the work was -- more useful than
                    # a placeholder in the one column that would be empty.
                    "fallback_title": (event.get("subject") or "") if ticket == placeholder else "",
                }
            )
    if undated:
        warn(
            "dropped %d event(s) with a missing or malformed date -- an adapter "
            "did not render one; see rule 1 in sources.md" % undated
        )
    if untracked == "group":
        rows = collapse_untracked(rows, placeholder)
    return rows


def collapse_untracked(rows, placeholder):
    """`group` mode keeps one ticketless line per date+activity rather than one
    per stray commit."""
    kept, grouped = [], {}
    for row in rows:
        if not row["untracked"]:
            kept.append(row)
            continue
        key = (row["date"], row["activity"])
        if key not in grouped:
            grouped[key] = dict(row, id=placeholder, time=row["time"], source="", repo="", url="")
        else:
            grouped[key]["time"] = earliest(grouped[key]["time"], row["time"])
    return kept + list(grouped.values())


def group(rows, include_time, titles, missing_title):
    """Collapse rows sharing a key into one line, counting the evidence behind
    it. Without --include-time a day's twelve commits on one ticket are one
    line; with it, each timestamped event stays separate."""
    merged = {}
    order = []
    for row in rows:
        key = (
            row["date"],
            row["time"] if include_time else "",
            row["item_type"],
            row["id"],
            row["activity"],
        )
        if key not in merged:
            merged[key] = {
                "date": row["date"],
                "day": weekday(row["date"]),
                "time": row["time"],
                "item_type": row["item_type"],
                "ticket_type": row["ticket_type"],
                "id": row["id"],
                "title": titles.get(row["id"]) or row.get("fallback_title") or missing_title,
                "activity": row["activity"],
                "sources": [],
                "repos": [],
                "url": row["url"],
                "evidence": 0,
            }
            order.append(key)
        entry = merged[key]
        entry["evidence"] += 1
        if row["source"] and row["source"] not in entry["sources"]:
            entry["sources"].append(row["source"])
        if row["repo"] and row["repo"] not in entry["repos"]:
            entry["repos"].append(row["repo"])
        if not entry["url"] and row["url"]:
            entry["url"] = row["url"]
        # Only board events know the issue type; the commits merged into the
        # same row do not. Take the first non-empty rather than making it part
        # of the grouping key, which would split a ticket-day in two.
        if not entry["ticket_type"] and row["ticket_type"]:
            entry["ticket_type"] = row["ticket_type"]
        if not include_time:
            # Keep the day's earliest timestamp, so a collapsed line still says
            # when the work started.
            entry["time"] = earliest(entry["time"], row["time"])

    out = []
    for key in order:
        entry = merged[key]
        entry["source"] = ", ".join(entry.pop("sources"))
        entry["repo"] = ", ".join(entry.pop("repos"))
        out.append(entry)
    out.sort(
        key=lambda r: (
            r["date"],
            r["time"] if include_time else "",
            item_type_rank(r["item_type"]),
            r["id"],
            r["activity"],
        )
    )
    return out


def truncate(text, width):
    text = str(text or "")
    if width <= 0 or len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def csv_cell(value):
    text = "" if value is None else str(value)
    if any(ch in text for ch in (",", '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def render_csv(rows, columns):
    lines = [",".join(csv_cell(HEADERS.get(c, c)) for c in columns)]
    for row in rows:
        lines.append(",".join(csv_cell(row.get(c, "")) for c in columns))
    return "\n".join(lines) + "\n"


def heading_for(row, date, show_weekday):
    day = row.get("day") or weekday(date)
    return "%s (%s)" % (date, day) if show_weekday and day else date


def cells_for(row, line_columns, widths):
    return [str(row.get(c, "")).ljust(widths[c]) for c in line_columns]


def render_grid(body, line_columns, widths, show_weekday, show_header):
    """Each day as its own boxed table. Column widths are computed across the
    whole report, not per day, so the boxes line up down the page instead of
    jittering wider and narrower as titles change."""
    border = "+" + "+".join("-" * (widths[c] + 2) for c in line_columns) + "+"
    header = "| " + " | ".join(HEADERS.get(c, c).ljust(widths[c]) for c in line_columns) + " |"

    out = []
    current = None
    for row in body:
        if row["date"] != current:
            if current is not None:
                out.append(border)
                out.append("")
            current = row["date"]
            out.append(heading_for(row, current, show_weekday))
            out.append(border)
            if show_header:
                out.append(header)
                out.append(border)
        out.append("| " + " | ".join(cells_for(row, line_columns, widths)) + " |")
    if current is not None:
        out.append(border)
    return out


def render_plain(body, line_columns, widths, show_weekday, show_header):
    """Indented columns, no borders, header once at the top. Narrower than the
    grid and friendlier to piping into another tool."""
    def line(cells):
        return ("  " + "  ".join(cells)).rstrip()

    out = []
    if show_header:
        out.append(line([HEADERS.get(c, c).ljust(widths[c]) for c in line_columns]))
        out.append(line(["-" * widths[c] for c in line_columns]))
        out.append("")

    current = None
    for row in body:
        if row["date"] != current:
            if current is not None:
                out.append("")
            current = row["date"]
            out.append(heading_for(row, current, show_weekday))
        out.append(line(cells_for(row, line_columns, widths)))
    return out


def render_terminal(rows, columns, title_width, range_label, show_summary,
                    show_weekday=True, show_header=True, table_style="grid"):
    if not rows:
        where = " for %s" % range_label if range_label else ""
        return "No activity found%s.\n" % where

    body = [dict(r, title=truncate(r.get("title"), title_width)) for r in rows]
    # `date`/`day` become the group heading, so they are not repeated per line.
    line_columns = [c for c in columns if c not in HEADING_COLUMNS]
    widths = {c: len(HEADERS.get(c, c)) for c in line_columns}
    for row in body:
        for c in line_columns:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))

    out = []
    if range_label:
        out.append("Timesheet -- %s" % range_label)
        out.append("")

    if not line_columns:
        # Only heading columns were requested; there is no table to draw.
        seen = []
        for row in body:
            if row["date"] not in seen:
                seen.append(row["date"])
                out.append(heading_for(row, row["date"], show_weekday))
    elif table_style == "plain":
        out.extend(render_plain(body, line_columns, widths, show_weekday, show_header))
    else:
        out.extend(render_grid(body, line_columns, widths, show_weekday, show_header))

    if show_summary:
        tally = {}
        for row in body:
            tally[row["activity"]] = tally.get(row["activity"], 0) + 1
        out.append("")
        out.append("Summary")
        for activity in sorted(tally, key=lambda a: (-tally[a], a)):
            out.append("  %-20s %d entr%s" % (activity, tally[activity], "y" if tally[activity] == 1 else "ies"))
        out.append("  %-20s %d" % ("total lines", len(body)))
    return "\n".join(out) + "\n"


def expand_user(path):
    """Expand a leading `~` to the user's home directory.

    Deliberately narrower than os.path.expanduser, which also resolves
    `~otheruser`: Node has no equivalent, and the two script twins have to agree
    on every input. `~otheruser` is left as a literal here.

    This matters most for paths that never pass through a shell -- `csv_path` in
    the config file, or a repo path typed into setup -- where nothing else would
    expand the `~` for you.
    """
    if not path:
        return path
    text = str(path)
    if text == "~":
        return os.path.expanduser("~")
    if text.startswith("~/") or text.startswith("~\\"):
        return os.path.join(os.path.expanduser("~"), text[2:])
    return text


def load_json(path):
    if path == "-":
        return json.load(sys.stdin)
    target = expand_user(path)
    try:
        with open(target, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        sys.exit("cannot read %s: %s" % (target, exc.strerror or exc))
    except ValueError as exc:
        sys.exit("%s is not valid JSON: %s" % (target, exc))


def write_text(path, text, bom=False):
    """Write `text` to `path`, creating the parent directory if needed.

    Returns the resolved path so the caller can report where the file actually
    landed, which is the useful part when `~` was expanded.
    """
    target = expand_user(path)
    parent = os.path.dirname(os.path.abspath(target))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as fh:
            if bom:
                fh.write(BOM)
            fh.write(text)
    except OSError as exc:
        sys.exit("cannot write %s: %s" % (target, exc.strerror or exc))
    return target


def resolve_columns(requested, include_time, warn):
    columns = list(requested) if requested else list(DEFAULT_COLUMNS)
    columns = [COLUMN_ALIASES.get(c, c) for c in columns]
    unknown = [c for c in columns if c not in ALL_COLUMNS]
    for c in unknown:
        warn("unknown column %r; dropping it (known: %s)" % (c, ", ".join(ALL_COLUMNS)))
    columns = [c for c in columns if c in ALL_COLUMNS]
    if include_time and "time" not in columns:
        # Slot it after any leading date/day, so the reading order stays
        # date -> day -> time rather than date -> time -> day.
        position = 0
        while position < len(columns) and columns[position] in HEADING_COLUMNS:
            position += 1
        columns.insert(position, "time")
    if not include_time:
        columns = [c for c in columns if c != "time"]
    return columns or list(DEFAULT_COLUMNS)


def build_parser():
    p = argparse.ArgumentParser(description="Render timesheet events as a table or CSV.")
    p.add_argument("--events", required=True, help="events JSON file, or - for stdin")
    p.add_argument("--config", default=None, help="config JSON file")
    p.add_argument("--format", choices=["terminal", "csv"], default=None)
    p.add_argument("--out", default=None, help="write here instead of stdout")
    p.add_argument("--columns", default=None, help="comma-separated column list")
    p.add_argument("--include-time", dest="include_time", action="store_true", default=None)
    p.add_argument("--no-include-time", dest="include_time", action="store_false")
    p.add_argument("--title-width", type=int, default=None, help="terminal title truncation (default 60)")
    p.add_argument("--range-label", default=None, help="header text, e.g. '2026-09-01 to 2026-09-07'")
    p.add_argument("--summary", dest="summary", action="store_true", default=None)
    p.add_argument("--no-summary", dest="summary", action="store_false")
    p.add_argument("--weekday", dest="weekday", action="store_true", default=None,
                   help="append the day name to each date heading (default on)")
    p.add_argument("--no-weekday", dest="weekday", action="store_false")
    p.add_argument("--header", dest="header", action="store_true", default=None,
                   help="print column names above the table (default on)")
    p.add_argument("--no-header", dest="header", action="store_false")
    p.add_argument("--table-style", choices=["grid", "plain"], default=None,
                   help="boxed table per day (default) or indented columns")
    p.add_argument("--bom", action="store_true", help="prefix CSV with a UTF-8 BOM for Excel")
    return p


def main(argv):
    opts = build_parser().parse_args(argv)
    warnings = []

    def warn(message):
        if message not in warnings:
            warnings.append(message)

    config = load_json(opts.config) if opts.config else {}
    payload = load_json(opts.events)
    if isinstance(payload, list):
        payload = {"events": payload}
    events = payload.get("events") or []
    titles = payload.get("ticket_titles") or {}

    output = config.get("output") or {}
    fmt = opts.format or output.get("format") or "terminal"
    include_time = opts.include_time
    if include_time is None:
        include_time = bool(output.get("include_time", False))
    title_width = opts.title_width if opts.title_width is not None else int(output.get("title_width", 60))
    show_summary = opts.summary
    if show_summary is None:
        show_summary = bool(output.get("show_summary", True))
    show_weekday = opts.weekday
    if show_weekday is None:
        show_weekday = bool(output.get("show_weekday", True))
    show_header = opts.header
    if show_header is None:
        show_header = bool(output.get("show_header", True))
    table_style = opts.table_style or output.get("table_style") or "grid"
    if table_style not in ("grid", "plain"):
        warn("output.table_style %r is not grid/plain; using grid" % table_style)
        table_style = "grid"
    missing_title = output.get("missing_title_placeholder", "(title unavailable)")
    requested = opts.columns.split(",") if opts.columns else output.get("columns")
    columns = resolve_columns([c.strip() for c in requested] if requested else None, include_time, warn)

    rows = group(
        expand(dedupe_events(events), config, warn), include_time, titles, missing_title
    )
    text = render_csv(rows, columns) if fmt == "csv" else render_terminal(
        rows, columns, title_width, opts.range_label, show_summary, show_weekday,
        show_header, table_style
    )

    out_path = opts.out or (output.get("csv_path") if fmt == "csv" else None)
    if out_path:
        written = write_text(out_path, text, bom=(fmt == "csv" and opts.bom))
        print("%d row(s) written to %s" % (len(rows), written))
    else:
        sys.stdout.write(text)

    for message in warnings:
        print("warning: " + message, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
