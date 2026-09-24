// Turn normalized timesheet events into a terminal table or a CSV file.
// Mirrors build_report.py rule-for-rule: same labelling precedence, same
// grouping key, same column set, same RFC 4180 quoting -- so a report rendered
// by either runtime is byte-identical.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Byte-order mark, built via fromCharCode so the source carries no invisible
// character. Excel needs it to read a UTF-8 CSV as UTF-8.
const BOM = String.fromCharCode(0xfeff);

export const KNOWN_WHEN_FIELDS = new Set([
  "type",
  "source",
  "repo",
  "branch",
  "subject_matches",
  "status_to",
  "ticket_type",
  "ticket_ids",
]);

export const DEFAULT_COLUMNS = ["date", "day", "item_type", "id", "title", "activity"];
export const ALL_COLUMNS = [
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
];

// Looser spellings accepted in `output.columns` and --columns. Note `type`
// points at ticket_type, matching its "Type" header; the Jira/Confluence
// column is `item_type`, headed "System".
export const COLUMN_ALIASES = {
  ticket_id: "id",
  ticket: "id",
  type: "ticket_type",
  issue_type: "ticket_type",
  system: "item_type",
};

// Terminal output prints these as the group heading rather than as columns.
export const HEADING_COLUMNS = ["date", "day"];

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// Which system the `id` lives in -- not where the evidence came from. A commit
// on ABC-1234 is item_type "jira" because its id is a Jira key, while the
// `source` column says the evidence was a commit.
export const ITEM_TYPE_LABELS = { jira: "Jira", confluence: "Confluence" };
export const ITEM_TYPE_ORDER = { Jira: 0, Confluence: 1 };

export const HEADERS = {
  date: "Date",
  day: "Day",
  time: "Time",
  item_type: "System",
  ticket_type: "Type",
  id: "Id",
  title: "Title",
  activity: "Activity",
  source: "Source",
  repo: "Repo",
  url: "URL",
  evidence: "Events",
};

function asList(value) {
  if (value === null || value === undefined) return [];
  return Array.isArray(value) ? [...value] : [value];
}

function lowerAll(values) {
  return values.map((v) => String(v).toLowerCase());
}

// Display name for the kind of item an event's ids refer to.
export function itemTypeFor(event) {
  const raw = String(event.item_type || "jira").trim().toLowerCase();
  return ITEM_TYPE_LABELS[raw] || (raw ? raw[0].toUpperCase() + raw.slice(1) : "");
}

// Jira first, then Confluence, then anything else, then untyped rows. Without
// this, mixed ids sort meaninglessly -- a numeric Confluence page id lands
// among the ABC-123 keys purely because digits precede letters.
export function itemTypeRank(value) {
  if (!value) return 3;
  return value in ITEM_TYPE_ORDER ? ITEM_TYPE_ORDER[value] : 2;
}

// Short day name for a YYYY-MM-DD string, or "" if it is not a real date.
// Uses a fixed table and UTC rather than toLocaleDateString, which would vary
// with the machine's locale and disagree with the Python twin.
export function weekday(dateStr) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr ?? ""));
  if (!m) return "";
  const [y, mo, d] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const dt = new Date(Date.UTC(y, mo - 1, d));
  // Date.UTC rolls 2026-02-31 over into March; Python's strptime rejects it,
  // so reject it here too rather than reporting a day for a date that is not.
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) {
    return "";
  }
  // getUTCDay() is Sunday-first; WEEKDAYS is Monday-first to match Python.
  return WEEKDAYS[(dt.getUTCDay() + 6) % 7];
}

export function earliest(a, b) {
  const times = [a, b].filter(Boolean);
  if (!times.length) return "";
  return times.reduce((x, y) => (x <= y ? x : y));
}

export function matchRule(event, when, warn) {
  for (const [field, expected] of Object.entries(when || {})) {
    if (field === "subject_matches") {
      if (!new RegExp(String(expected), "i").test(event.subject || "")) return false;
      continue;
    }
    if (!KNOWN_WHEN_FIELDS.has(field)) {
      warn(`rule condition '${field}' is not a recognized field; it can never match`);
      return false;
    }
    const actual = lowerAll(asList(event[field]));
    if (!actual.length) return false;
    const wanted = new Set(lowerAll(asList(expected)));
    if (!actual.some((v) => wanted.has(v))) return false;
  }
  return true;
}

// Returns the activity label for an event, or null to drop it entirely.
//
// An event may carry an explicit activity (a correction the user made, or an
// adapter that already knows); that beats rule inference, including a drop
// rule -- pinning a label is always deliberate.
//
// A rule with `"drop": true` suppresses the event instead of labelling it.
// That is how bookkeeping events stay out of the report: assigning a ticket or
// moving it to Done is a record *about* work, not work, and giving it a row
// would say "Other" where nothing happened.
export function labelFor(event, rules, defaultActivity, warn) {
  if (event.activity) return String(event.activity);
  for (const rule of rules || []) {
    if (matchRule(event, rule.when || {}, warn)) {
      if (rule.drop) return null;
      if (!rule.label) {
        warn("rule matched but has neither a label nor drop: true; using the default activity");
      }
      return String(rule.label || defaultActivity);
    }
  }
  return defaultActivity;
}

// Drop the same commit when two sources both reported it.
//
// A commit present in the local clone and also returned by a code host would
// otherwise merge into one row carrying `evidence: 2` and both source names, as
// though two separate things had happened. Identity is the commit ref; the
// local-git copy wins because it carries the true author date, where a host may
// only expose the committer date.
//
// Only `commit` events with a ref are considered -- a PR review and a commit are
// genuinely different work even on the same ticket.
export function dedupeEvents(events) {
  const index = new Map();
  const out = [];
  for (const event of events) {
    const ref = String(event.ref || "");
    if (String(event.type || "") !== "commit" || !ref) {
      out.push(event);
      continue;
    }
    if (!index.has(ref)) {
      index.set(ref, out.length);
      out.push(event);
    } else if (event.source === "local-git" && out[index.get(ref)].source !== "local-git") {
      out[index.get(ref)] = event;
    }
  }
  return out;
}

export function expand(events, config, warn) {
  const output = config.output || {};
  const rules = config.activity_rules || [];
  const defaultActivity = config.default_activity || "Other";
  const placeholder = output.untracked_placeholder ?? "(no ticket)";
  let untracked = output.untracked ?? "include";
  if (!["include", "omit", "group"].includes(untracked)) {
    warn(`output.untracked '${untracked}' is not include/omit/group; using include`);
    untracked = "include";
  }

  let rows = [];
  let undated = 0;
  for (const event of events) {
    // weekday() returns "" for anything that is not a real YYYY-MM-DD date,
    // which makes it the validity check too. A row with no usable date cannot
    // be placed in a timesheet, and because dates sort as strings a malformed
    // one would also silently misorder the report -- so drop it and say so,
    // rather than rendering a group under a blank heading.
    if (!weekday(event.date)) {
      undated += 1;
      continue;
    }
    const activity = labelFor(event, rules, defaultActivity, warn);
    if (activity === null) continue;
    let itemType = itemTypeFor(event);
    let tickets = asList(event.ticket_ids).filter(Boolean);
    if (!tickets.length) {
      if (untracked === "omit") continue;
      tickets = [placeholder];
      // Nothing to type when there is no item behind the row.
      itemType = "";
    }
    for (const ticket of tickets) {
      rows.push({
        date: event.date || "",
        time: event.time || "",
        item_type: itemType,
        ticket_type: String(event.ticket_type || ""),
        id: String(ticket),
        activity,
        source: event.source || "",
        repo: event.repo || "",
        url: event.url || "",
        untracked: ticket === placeholder,
        // A ticketless row has no board title to look up, but the commit
        // subject says what the work was -- more useful than a placeholder in
        // the one column that would otherwise be empty.
        fallback_title: ticket === placeholder ? event.subject || "" : "",
      });
    }
  }
  if (undated) {
    warn(
      `dropped ${undated} event(s) with a missing or malformed date -- an adapter ` +
        "did not render one; see rule 1 in sources.md"
    );
  }
  if (untracked === "group") rows = collapseUntracked(rows, placeholder);
  return rows;
}

export function collapseUntracked(rows, placeholder) {
  const kept = [];
  const grouped = new Map();
  for (const row of rows) {
    if (!row.untracked) {
      kept.push(row);
      continue;
    }
    const key = `${row.date}\u0000${row.activity}`;
    if (!grouped.has(key)) {
      grouped.set(key, { ...row, id: placeholder, source: "", repo: "", url: "" });
    } else {
      const entry = grouped.get(key);
      entry.time = earliest(entry.time, row.time);
    }
  }
  return kept.concat([...grouped.values()]);
}

export function group(rows, includeTime, titles, missingTitle) {
  const merged = new Map();
  for (const row of rows) {
    // NUL joins the key parts: unlike a space it cannot occur inside a value,
    // so this behaves exactly like the Python twin's tuple key.
    const key = [
      row.date,
      includeTime ? row.time : "",
      row.item_type,
      row.id,
      row.activity,
    ].join("\u0000");
    if (!merged.has(key)) {
      merged.set(key, {
        date: row.date,
        day: weekday(row.date),
        time: row.time,
        item_type: row.item_type,
        ticket_type: row.ticket_type,
        id: row.id,
        title: titles[row.id] || row.fallback_title || missingTitle,
        activity: row.activity,
        sources: [],
        repos: [],
        url: row.url,
        evidence: 0,
      });
    }
    const entry = merged.get(key);
    entry.evidence += 1;
    if (row.source && !entry.sources.includes(row.source)) entry.sources.push(row.source);
    if (row.repo && !entry.repos.includes(row.repo)) entry.repos.push(row.repo);
    if (!entry.url && row.url) entry.url = row.url;
    // Only board events know the issue type; the commits merged into the same
    // row do not. Take the first non-empty rather than making it part of the
    // grouping key, which would split a ticket-day in two.
    if (!entry.ticket_type && row.ticket_type) entry.ticket_type = row.ticket_type;
    if (!includeTime) entry.time = earliest(entry.time, row.time);
  }

  const out = [...merged.values()].map((entry) => {
    const { sources, repos, ...rest } = entry;
    return { ...rest, source: sources.join(", "), repo: repos.join(", ") };
  });
  out.sort((a, b) => {
    const ka = [a.date, includeTime ? a.time : "", itemTypeRank(a.item_type), a.id, a.activity].join("\u0000");
    const kb = [b.date, includeTime ? b.time : "", itemTypeRank(b.item_type), b.id, b.activity].join("\u0000");
    return ka < kb ? -1 : ka > kb ? 1 : 0;
  });
  return out;
}

export function truncate(text, width) {
  const s = text === null || text === undefined ? "" : String(text);
  if (width <= 0 || s.length <= width) return s;
  if (width <= 3) return s.slice(0, width);
  return s.slice(0, width - 3) + "...";
}

export function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function renderCsv(rows, columns) {
  const lines = [columns.map((c) => csvCell(HEADERS[c] || c)).join(",")];
  for (const row of rows) {
    lines.push(columns.map((c) => csvCell(row[c] ?? "")).join(","));
  }
  return lines.join("\n") + "\n";
}

export function headingFor(row, date, showWeekday) {
  const day = row.day || weekday(date);
  return showWeekday && day ? `${date} (${day})` : date;
}

function cellsFor(row, lineColumns, widths) {
  return lineColumns.map((c) => String(row[c] ?? "").padEnd(widths[c]));
}

// Each day as its own boxed table. Column widths are computed across the whole
// report, not per day, so the boxes line up down the page instead of jittering
// wider and narrower as titles change.
export function renderGrid(body, lineColumns, widths, showWeekday, showHeader) {
  const border = "+" + lineColumns.map((c) => "-".repeat(widths[c] + 2)).join("+") + "+";
  const header = "| " + lineColumns.map((c) => (HEADERS[c] || c).padEnd(widths[c])).join(" | ") + " |";

  const out = [];
  let current = null;
  for (const row of body) {
    if (row.date !== current) {
      if (current !== null) {
        out.push(border);
        out.push("");
      }
      current = row.date;
      out.push(headingFor(row, current, showWeekday));
      out.push(border);
      if (showHeader) {
        out.push(header);
        out.push(border);
      }
    }
    out.push("| " + cellsFor(row, lineColumns, widths).join(" | ") + " |");
  }
  if (current !== null) out.push(border);
  return out;
}

// Indented columns, no borders, header once at the top. Narrower than the grid
// and friendlier to piping into another tool.
export function renderPlain(body, lineColumns, widths, showWeekday, showHeader) {
  const line = (cells) => ("  " + cells.join("  ")).replace(/\s+$/, "");

  const out = [];
  if (showHeader) {
    out.push(line(lineColumns.map((c) => (HEADERS[c] || c).padEnd(widths[c]))));
    out.push(line(lineColumns.map((c) => "-".repeat(widths[c]))));
    out.push("");
  }

  let current = null;
  for (const row of body) {
    if (row.date !== current) {
      if (current !== null) out.push("");
      current = row.date;
      out.push(headingFor(row, current, showWeekday));
    }
    out.push(line(cellsFor(row, lineColumns, widths)));
  }
  return out;
}

export function renderTerminal(
  rows,
  columns,
  titleWidth,
  rangeLabel,
  showSummary,
  showWeekday = true,
  showHeader = true,
  tableStyle = "grid"
) {
  if (!rows.length) {
    return `No activity found${rangeLabel ? ` for ${rangeLabel}` : ""}.\n`;
  }

  const body = rows.map((r) => ({ ...r, title: truncate(r.title, titleWidth) }));
  // `date`/`day` become the group heading, so they are not repeated per line.
  const lineColumns = columns.filter((c) => !HEADING_COLUMNS.includes(c));
  const widths = {};
  for (const c of lineColumns) widths[c] = (HEADERS[c] || c).length;
  for (const row of body) {
    for (const c of lineColumns) {
      widths[c] = Math.max(widths[c], String(row[c] ?? "").length);
    }
  }

  const out = [];
  if (rangeLabel) {
    out.push(`Timesheet -- ${rangeLabel}`);
    out.push("");
  }

  if (!lineColumns.length) {
    // Only heading columns were requested; there is no table to draw.
    const seen = [];
    for (const row of body) {
      if (!seen.includes(row.date)) {
        seen.push(row.date);
        out.push(headingFor(row, row.date, showWeekday));
      }
    }
  } else if (tableStyle === "plain") {
    out.push(...renderPlain(body, lineColumns, widths, showWeekday, showHeader));
  } else {
    out.push(...renderGrid(body, lineColumns, widths, showWeekday, showHeader));
  }

  if (showSummary) {
    const tally = new Map();
    for (const row of body) tally.set(row.activity, (tally.get(row.activity) || 0) + 1);
    out.push("");
    out.push("Summary");
    const entries = [...tally.entries()].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1));
    for (const [activity, count] of entries) {
      out.push(`  ${activity.padEnd(20)} ${count} entr${count === 1 ? "y" : "ies"}`);
    }
    out.push(`  ${"total lines".padEnd(20)} ${body.length}`);
  }
  return out.join("\n") + "\n";
}

// Expand a leading `~` to the user's home directory.
//
// Deliberately narrower than Python's os.path.expanduser, which also resolves
// `~otheruser`: Node has no equivalent, and the two script twins have to agree
// on every input. `~otheruser` is left as a literal here.
//
// This matters most for paths that never pass through a shell -- `csv_path` in
// the config file, or a repo path typed into setup -- where nothing else would
// expand the `~` for you.
export function expandUser(target) {
  if (!target) return target;
  const text = String(target);
  if (text === "~") return homedir();
  if (text.startsWith("~/") || text.startsWith("~\\")) {
    return path.join(homedir(), text.slice(2));
  }
  return text;
}

function loadJson(source) {
  if (source === "-") return JSON.parse(readFileSync(0, "utf8"));
  const target = expandUser(source);
  let text;
  try {
    text = readFileSync(target, "utf8");
  } catch (err) {
    console.error(`cannot read ${target}: ${err.message}`);
    process.exit(1);
  }
  try {
    return JSON.parse(text);
  } catch (err) {
    console.error(`${target} is not valid JSON: ${err.message}`);
    process.exit(1);
  }
}

// Write `text` to `target`, creating the parent directory if needed. Returns
// the resolved path so the caller can report where the file actually landed,
// which is the useful part when `~` was expanded.
export function writeText(target, text, bom = false) {
  const resolved = expandUser(target);
  try {
    const parent = path.dirname(path.resolve(resolved));
    if (parent) mkdirSync(parent, { recursive: true });
    writeFileSync(resolved, (bom ? BOM : "") + text, "utf8");
  } catch (err) {
    console.error(`cannot write ${resolved}: ${err.message}`);
    process.exit(1);
  }
  return resolved;
}

export function resolveColumns(requested, includeTime, warn) {
  let columns = requested && requested.length ? [...requested] : [...DEFAULT_COLUMNS];
  columns = columns.map((c) => COLUMN_ALIASES[c] || c);
  for (const c of columns.filter((c) => !ALL_COLUMNS.includes(c))) {
    warn(`unknown column '${c}'; dropping it (known: ${ALL_COLUMNS.join(", ")})`);
  }
  columns = columns.filter((c) => ALL_COLUMNS.includes(c));
  if (includeTime && !columns.includes("time")) {
    // Slot it after any leading date/day, so the reading order stays
    // date -> day -> time rather than date -> time -> day.
    let position = 0;
    while (position < columns.length && HEADING_COLUMNS.includes(columns[position])) {
      position += 1;
    }
    columns.splice(position, 0, "time");
  }
  if (!includeTime) columns = columns.filter((c) => c !== "time");
  return columns.length ? columns : [...DEFAULT_COLUMNS];
}

const USAGE = `Usage: build_report.mjs --events PATH|- [--config PATH] [--format terminal|csv]
  [--out PATH] [--columns a,b,c] [--include-time|--no-include-time]
  [--title-width N] [--range-label TEXT] [--summary|--no-summary]
  [--weekday|--no-weekday] [--header|--no-header] [--table-style grid|plain]
  [--bom]`;

export function parseArgs(argv) {
  const opts = {
    events: null,
    config: null,
    format: null,
    out: null,
    columns: null,
    includeTime: null,
    titleWidth: null,
    rangeLabel: null,
    summary: null,
    weekday: null,
    header: null,
    tableStyle: null,
    bom: false,
  };
  const takesValue = {
    "--events": (v) => (opts.events = v),
    "--config": (v) => (opts.config = v),
    "--format": (v) => (opts.format = v),
    "--out": (v) => (opts.out = v),
    "--columns": (v) => (opts.columns = v),
    "--title-width": (v) => (opts.titleWidth = Number(v)),
    "--range-label": (v) => (opts.rangeLabel = v),
    "--table-style": (v) => (opts.tableStyle = v),
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--include-time") opts.includeTime = true;
    else if (arg === "--no-include-time") opts.includeTime = false;
    else if (arg === "--summary") opts.summary = true;
    else if (arg === "--no-summary") opts.summary = false;
    else if (arg === "--weekday") opts.weekday = true;
    else if (arg === "--no-weekday") opts.weekday = false;
    else if (arg === "--header") opts.header = true;
    else if (arg === "--no-header") opts.header = false;
    else if (arg === "--bom") opts.bom = true;
    else if (takesValue[arg]) {
      i += 1;
      if (i >= argv.length) throw new Error(`${arg} needs a value`);
      takesValue[arg](argv[i]);
    } else throw new Error(`unknown argument: ${arg}`);
  }
  if (!opts.events) throw new Error("--events is required");
  if (opts.format && !["terminal", "csv"].includes(opts.format)) {
    throw new Error("--format must be terminal or csv");
  }
  if (opts.tableStyle && !["grid", "plain"].includes(opts.tableStyle)) {
    throw new Error("--table-style must be grid or plain");
  }
  return opts;
}

export function main(argv) {
  let opts;
  try {
    opts = parseArgs(argv);
  } catch (err) {
    console.error(`${err.message}\n\n${USAGE}`);
    process.exit(1);
  }

  const warnings = [];
  const warn = (message) => {
    if (!warnings.includes(message)) warnings.push(message);
  };

  const config = opts.config ? loadJson(opts.config) : {};
  let payload = loadJson(opts.events);
  if (Array.isArray(payload)) payload = { events: payload };
  const events = payload.events || [];
  const titles = payload.ticket_titles || {};

  const output = config.output || {};
  const fmt = opts.format || output.format || "terminal";
  const includeTime = opts.includeTime === null ? Boolean(output.include_time) : opts.includeTime;
  const titleWidth = opts.titleWidth === null ? Number(output.title_width ?? 60) : opts.titleWidth;
  const showSummary = opts.summary === null ? output.show_summary !== false : opts.summary;
  const showWeekday = opts.weekday === null ? output.show_weekday !== false : opts.weekday;
  const showHeader = opts.header === null ? output.show_header !== false : opts.header;
  let tableStyle = opts.tableStyle || output.table_style || "grid";
  if (!["grid", "plain"].includes(tableStyle)) {
    warn(`output.table_style '${tableStyle}' is not grid/plain; using grid`);
    tableStyle = "grid";
  }
  const missingTitle = output.missing_title_placeholder ?? "(title unavailable)";
  const requested = opts.columns ? opts.columns.split(",").map((c) => c.trim()) : output.columns;
  const columns = resolveColumns(requested, includeTime, warn);

  const rows = group(
    expand(dedupeEvents(events), config, warn),
    includeTime,
    titles,
    missingTitle
  );
  const text =
    fmt === "csv"
      ? renderCsv(rows, columns)
      : renderTerminal(
          rows,
          columns,
          titleWidth,
          opts.rangeLabel,
          showSummary,
          showWeekday,
          showHeader,
          tableStyle
        );

  const outPath = opts.out || (fmt === "csv" ? output.csv_path : null);
  if (outPath) {
    const written = writeText(outPath, text, fmt === "csv" && opts.bom);
    console.log(`${rows.length} row(s) written to ${written}`);
  } else {
    process.stdout.write(text);
  }
  for (const message of warnings) console.error("warning: " + message);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
