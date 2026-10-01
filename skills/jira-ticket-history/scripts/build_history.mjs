// Turn a raw Jira history bundle into the git-log style HTML page.
// Mirrors build_history.py rule-for-rule: same classification, same diff
// algorithm, same JSON layout -- so a page built by either runtime is
// byte-identical. Everything that must not vary between runs lives here; the
// template only renders what this script decides.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const MODEL_VERSION = 1;
export const TYPES = [
  "status", "assignee", "description", "title", "fields",
  "comments", "links", "weblinks", "attachments", "worklogs",
];

// Whitespace set spelled out so JS and Python agree on what a "word" and a
// "blank line" are (their built-in \s classes differ at the edges).
const WS = "[ \\t\\n\\r\\f\\v\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]";
const WS_SPLIT = new RegExp(`(${WS}+)`);
const WS_TRAIL = new RegExp(`${WS}+$`);
const WS_ONLY = new RegExp(`^${WS}*$`);

// Guards against quadratic blow-ups on huge fields. Past these sizes a diff
// degrades to "whole line/field replaced" -- still correct, just coarser.
export const MAX_LINE_CELLS = 4_000_000;
export const MAX_WORD_CELLS = 1_000_000;

// ---------------------------------------------------------------- mojibake --
// UTF-8 text that was decoded as Windows-1252 before Jira stored it ("—" kept
// as "â€”"). A run is rewritten only when re-encoding it as cp1252 yields one
// valid UTF-8 character, so genuine text such as "Â" or "naïve" is untouched.
const CP1252_HIGH = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86,
  0x2021: 0x87, 0x02c6: 0x88, 0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c,
  0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93, 0x201d: 0x94, 0x2022: 0x95,
  0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b,
  0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f,
};
const CONT_CHARS = "\\u0080-\\u00bf" + Object.keys(CP1252_HIGH)
  .map((c) => "\\u" + Number(c).toString(16).padStart(4, "0")).join("");
const MOJIBAKE = new RegExp(`[\\u00c2-\\u00f4][${CONT_CHARS}]{1,3}`, "g");
const UTF8 = new TextDecoder("utf-8", { fatal: true });

export function repairMojibake(s) {
  if (typeof s !== "string") return { text: s, fixed: [] };
  const fixed = [];
  const text = s.replace(MOJIBAKE, (run) => {
    const bytes = [...run].map((ch) => {
      const c = ch.codePointAt(0);
      return c < 0x100 ? c : CP1252_HIGH[c];
    });
    let out;
    try {
      out = UTF8.decode(Uint8Array.from(bytes));
    } catch {
      return run;
    }
    if ([...out].length !== 1) return run;
    fixed.push([run, out]);
    return out;
  });
  return { text, fixed };
}

export const repair = (s) => repairMojibake(s).text;

function encodingSeen(s) {
  const seen = [];
  for (const [bad, good] of repairMojibake(s).fixed) {
    const label = `${bad} → ${good}`;
    if (!seen.includes(label)) seen.push(label);
  }
  return seen;
}

// ------------------------------------------------------------ wiki markup --
// Jira escapes punctuation with a backslash when it converts editor content to
// wiki markup. For display we drop escapes that carry no formatting meaning;
// \* and \_ stay so the renderer keeps them literal instead of emphasising.
const ESC_DISPLAY = /\\([-()+!\[\]{}.#|~^])/g;
const ESC_ALL = /\\([-()+!\[\]{}.#|~^*_])/g;
export const unescapeDisplay = (s) => s.replace(ESC_DISPLAY, "$1");
export const unescapeAll = (s) => s.replace(ESC_ALL, "$1");

// ADF (Atlassian Document Format) -> wiki markup, so both storage formats diff
// and render through one path.
export function adfToWiki(doc) {
  const out = [];
  const inline = (node) => (node.content || []).map((c) => {
    if (c.type === "hardBreak") return "\n";
    if (c.type === "mention") return "@" + String((c.attrs && c.attrs.text) || "").replace(/^@/, "");
    if (c.type === "emoji") return (c.attrs && (c.attrs.text || c.attrs.shortName)) || "";
    if (c.type === "inlineCard" || c.type === "blockCard") return (c.attrs && c.attrs.url) || "";
    if (c.type === "status") return `[${(c.attrs && c.attrs.text) || ""}]`;
    if (c.type === "date") return (c.attrs && c.attrs.timestamp) || "";
    if (c.type === "media" || c.type === "mediaInline") return "[image]";
    if (c.type !== "text") return inline(c);
    let t = c.text || "";
    for (const m of c.marks || []) {
      if (m.type === "strong") t = `*${t}*`;
      else if (m.type === "em") t = `_${t}_`;
      else if (m.type === "code") t = `{{${t}}}`;
      else if (m.type === "strike") t = `-${t}-`;
      else if (m.type === "underline") t = `+${t}+`;
      else if (m.type === "link" && m.attrs && m.attrs.href) t = `[${t}|${m.attrs.href}]`;
    }
    return t;
  }).join("");
  const block = (node, prefix) => {
    for (const c of node.content || []) {
      const t = c.type;
      if (t === "heading") out.push(`h${(c.attrs && c.attrs.level) || 1}. ${inline(c)}`);
      else if (t === "paragraph") out.push((prefix ? prefix + " " : "") + inline(c));
      else if (t === "bulletList" || t === "orderedList") {
        const mark = t === "bulletList" ? "*" : "#";
        for (const li of c.content || []) block(li, (prefix || "") + mark);
      } else if (t === "listItem") block(c, prefix);
      else if (t === "codeBlock") { out.push("{code}"); out.push(inline(c)); out.push("{code}"); }
      else if (t === "blockquote") for (const p of c.content || []) out.push("bq. " + inline(p));
      else if (t === "rule") out.push("----");
      else if (t === "table") {
        for (const row of c.content || []) {
          const cells = (row.content || []).map((cell) => ({
            head: cell.type === "tableHeader",
            text: (cell.content || []).map(inline).join(" "),
          }));
          const head = cells.length > 0 && cells.every((x) => x.head);
          out.push(head ? "||" + cells.map((x) => x.text).join("||") + "||"
            : "|" + cells.map((x) => x.text).join("|") + "|");
        }
      } else if (t === "mediaSingle" || t === "mediaGroup") out.push("[image]");
      else block(c, prefix);
    }
  };
  block(doc, "");
  return out.join("\n\n");
}

function parseAdf(value) {
  if (value && typeof value === "object") return value.type === "doc" ? value : null;
  if (typeof value !== "string" || !/^\s*\{\s*"type"\s*:\s*"doc"/.test(value)) return null;
  for (const candidate of [value, unescapeAll(value)]) {
    try {
      const doc = JSON.parse(candidate);
      if (doc && doc.type === "doc") return doc;
    } catch {
      // try the next form
    }
  }
  return null;
}

// Raw field value -> wiki text (mojibake repaired, ADF converted).
export function toWiki(value) {
  if (value == null) return "";
  const doc = parseAdf(value);
  if (doc) return repair(adfToWiki(doc));
  return repair(String(value));
}

export function splitLines(text) {
  return text.split("\n").map((l) => l.replace(WS_TRAIL, "")).filter((l) => !WS_ONLY.test(l));
}

// ------------------------------------------------------------------- diff --
export function lcsOps(a, b) {
  const n = a.length, m = b.length;
  if (n * m > MAX_LINE_CELLS) return [...a.map((x) => ["-", x]), ...b.map((x) => ["+", x])];
  const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const ops = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push(["=", a[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push(["-", a[i++]]);
    else ops.push(["+", b[j++]]);
  }
  while (i < n) ops.push(["-", a[i++]]);
  while (j < m) ops.push(["+", b[j++]]);
  return ops;
}

// Word-level segments for a changed pair: [["=", text] | ["x", text], ...].
export function wordDiff(a, b) {
  const ta = a.split(WS_SPLIT), tb = b.split(WS_SPLIT);
  if (ta.length * tb.length > MAX_WORD_CELLS) {
    return { del: a ? [["x", a]] : [], add: b ? [["x", b]] : [] };
  }
  const ops = lcsOps(ta, tb);
  const side = (keep) => {
    const out = [];
    for (const [k, t] of ops) {
      if (k !== "=" && k !== keep) continue;
      if (t === "") continue;
      const kind = k === "=" ? "=" : "x";
      if (out.length && out[out.length - 1][0] === kind) out[out.length - 1][1] += t;
      else out.push([kind, t]);
    }
    return out;
  };
  return { del: side("-"), add: side("+") };
}

// Multi-line text diff: collapsed hunks, the full "after" text with change
// marks, and which side carried broken characters.
export function textDiff(fromRaw, toRaw) {
  const fromWiki = toWiki(fromRaw), toWikiText = toWiki(toRaw);
  const a = splitLines(unescapeDisplay(fromWiki)), b = splitLines(unescapeDisplay(toWikiText));
  const ops = lcsOps(a, b);
  const lines = [];
  for (let k = 0; k < ops.length; k++) {
    if (ops[k][0] !== "-") { lines.push({ k: ops[k][0], t: ops[k][1] }); continue; }
    const dels = [], adds = [];
    while (k < ops.length && ops[k][0] === "-") dels.push(ops[k++][1]);
    while (k < ops.length && ops[k][0] === "+") adds.push(ops[k++][1]);
    k--;
    const pairs = Math.min(dels.length, adds.length);
    const wd = [];
    for (let i = 0; i < pairs; i++) wd.push(wordDiff(dels[i], adds[i]));
    dels.forEach((t, i) => lines.push(i < pairs ? { k: "-", t, w: wd[i].del } : { k: "-", t }));
    adds.forEach((t, i) => lines.push(i < pairs ? { k: "+", t, w: wd[i].add } : { k: "+", t }));
  }
  const near = (j) => j >= 0 && j < lines.length && lines[j].k !== "=";
  const hunks = [];
  let skipped = 0;
  lines.forEach((l, i) => {
    if (l.k !== "=" || near(i - 1) || near(i + 1)) {
      if (skipped) hunks.push({ k: "~", n: skipped });
      skipped = 0;
      hunks.push(l);
    } else skipped++;
  });
  if (skipped) hunks.push({ k: "~", n: skipped });
  const full = lines.filter((l) => l.k !== "-");
  const add = lines.filter((l) => l.k === "+").length;
  const del = lines.filter((l) => l.k === "-").length;
  const same = splitLines(unescapeAll(fromWiki)).join("\n") === splitLines(unescapeAll(toWikiText)).join("\n");
  return {
    add: same ? 0 : add,
    del: same ? 0 : del,
    hunks: same ? [] : hunks,
    full,
    markup_only: same,
    adf: Boolean(parseAdf(fromRaw) || parseAdf(toRaw)),
    encoding: { before: encodingSeen(fromRaw), after: encodingSeen(toRaw) },
  };
}

// -------------------------------------------------------------- timestamps --
const TS = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$/;

export function toEpochMs(ts) {
  const m = TS.exec(String(ts || ""));
  if (!m) return null;
  const [, y, mo, d, h, mi, s, frac, zone] = m;
  const ms = frac ? Number((frac + "00").slice(0, 3)) : 0;
  let offMin = 0;
  if (zone && zone !== "Z") {
    const z = zone.replace(":", "");
    offMin = (z[0] === "-" ? -1 : 1) * (Number(z.slice(1, 3)) * 60 + Number(z.slice(3, 5)));
  }
  return Date.UTC(+y, +mo - 1, +d, +h, +mi, +s, ms) - offMin * 60000;
}

const pad = (n, w = 2) => String(n).padStart(w, "0");

// Render an instant in the machine's local zone ("local") or UTC ("utc").
export function renderTs(ms, tz) {
  if (ms == null) return null;
  const d = new Date(ms);
  let off, y, mo, day, h, mi, s;
  if (tz === "utc") {
    off = 0;
    [y, mo, day, h, mi, s] = [d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()];
  } else {
    off = -d.getTimezoneOffset();
    [y, mo, day, h, mi, s] = [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds()];
  }
  const sign = off < 0 ? "-" : "+";
  const a = Math.abs(off);
  return `${pad(y, 4)}-${pad(mo)}-${pad(day)}T${pad(h)}:${pad(mi)}:${pad(s)}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

// ------------------------------------------------------------ html -> text --
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
export function htmlToText(html) {
  return String(html || "")
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|tr|pre|blockquote)>/gi, "\n")
    .replace(/<[^>]*>/g, "")
    .replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) => {
      if (e[0] === "#") {
        const code = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
        return code > 0 && code <= 0x10ffff && (code < 0xd800 || code > 0xdfff) ? String.fromCodePoint(code) : m;
      }
      const k = e.toLowerCase();
      return Object.hasOwn(ENTITIES, k) ? ENTITIES[k] : m;
    });
}

function wikiToText(s) {
  return unescapeAll(s)
    .replace(/\[~accountid:[^\]]+\]/g, "@user")
    .replace(/\[~([^\]]+)\]/g, "@$1")
    .replace(/\[([^\]|]+)\|[^\]]+\]/g, "$1")
    .replace(/\{\{|\}\}/g, "")
    .replace(/(^|\s)[*_](\S)/g, "$1$2")
    .replace(/(\S)[*_](?=\s|$|[.,:;!?)])/g, "$1");
}

export function firstLine(text, width = 80) {
  const line = String(text || "").split("\n").map((l) => l.replace(WS_TRAIL, "").replace(new RegExp(`^${WS}+`), ""))
    .find((l) => l !== "") || "";
  return [...line].length > width ? [...line].slice(0, width - 2).join("") + "…" : line;
}

// ---------------------------------------------------------- classification --
const idOf = (u) => (u && (u.accountId || u.key || u.name)) || null;
const nameOf = (u) => (u && (u.displayName || u.name || u.accountId)) || "Unknown";

// Map a changelog item to one of TYPES from Jira's own field identity only.
export function classify(item) {
  const id = String(item.fieldId || "").toLowerCase();
  const f = String(item.field || "");
  const key = id || f.toLowerCase();
  if (key === "status") return "status";
  if (key === "assignee") return "assignee";
  if (key === "description") return "description";
  if (key === "summary") return "title";
  if (f === "Link" || f === "IssueParentAssociation" || key === "parent" || f === "Parent" || f === "Epic Link" && !id) return "links";
  if (f === "RemoteWorkItemLink" || f === "RemoteIssueLink") return "weblinks";
  if (f === "Attachment" || key === "attachment") return "attachments";
  if (f === "Comment" || key === "comment") return "comments";
  if (f === "WorklogId" || key === "timespent" || key === "timeestimate" || key === "timeoriginalestimate" || key === "worklogtimespent") return "worklogs";
  return "fields";
}

const LABELS = {
  status: "Status", assignee: "Assignee", reporter: "Reporter", priority: "Priority",
  summary: "Title", description: "Description", labels: "Labels", issuetype: "Type",
  resolution: "Resolution", environment: "Environment", duedate: "Due date",
  components: "Component", fixversions: "Fix version", versions: "Affects version",
  timespent: "Time spent", timeestimate: "Remaining estimate", timeoriginalestimate: "Original estimate",
  worklogid: "Worklog", link: "Issue link", issueparentassociation: "Parent",
  remoteworkitemlink: "Web link", remoteissuelink: "Web link", attachment: "Attachment",
  comment: "Comment",
};
function labelOf(item) {
  const id = String(item.fieldId || "").toLowerCase();
  const f = String(item.field || "");
  const own = (k) => (Object.hasOwn(LABELS, k) ? LABELS[k] : "");
  return own(id) || own(f.toLowerCase()) || f || id || "Field";
}

// Cascading selects log "Parent values: A(10)Level 1 values: B(11)" -- a Jira
// format, not a site convention -- so render it as "A / B".
function cleanValue(s) {
  if (s == null || s === "") return null;
  let v = repair(String(s));
  if (/^Parent values: /.test(v)) {
    v = v.replace(/^Parent values: /, "").replace(/Level 1 values: /, " / ").replace(/\(\d+\)/g, "");
  }
  return v;
}

// Own properties only: an item without "toString" would otherwise inherit
// Object.prototype.toString and read as a value.
export function side(item, k) {
  return Object.hasOwn(item, k) && item[k] != null ? String(item[k]) : null;
}

function isMultiline(item) {
  const key = String(item.fieldId || item.field || "").toLowerCase();
  if (key === "description" || key === "environment") return true;
  for (const v of [side(item, "fromString"), side(item, "toString")]) {
    if (typeof v === "string" && (v.includes("\n") || parseAdf(v))) return true;
  }
  return false;
}

const PRIORITY = { status: 0, assignee: 1, title: 2, description: 3 };

export function toChange(item) {
  const cat = classify(item);
  const label = labelOf(item);
  const fieldId = String(item.fieldId || item.field || "");
  const rawFrom = side(item, "fromString");
  const rawTo = side(item, "toString");
  const from = cleanValue(rawFrom), to = cleanValue(rawTo);
  const base = { cat, label, field_id: fieldId };

  if (cat === "comments") {
    return { ...base, from: null, to: null, deleted: from ? toWiki(rawFrom) : null, subject: from && !to ? "Delete comment" : "Change comment" };
  }
  if (cat === "description" || (cat === "fields" && isMultiline(item))) {
    const diff = textDiff(rawFrom, rawTo);
    const name = cat === "description" ? "description" : label;
    let subject;
    const enc = diff.encoding;
    if (diff.markup_only) {
      if (enc.before.length && !enc.after.length) subject = `Fix broken characters in ${name}`;
      else if (enc.after.some((x) => !enc.before.includes(x))) subject = `Save ${name} with broken characters`;
      else subject = `Reformat ${name} (markup only)`;
    } else if (!rawFrom) subject = `Add ${name}`;
    else if (!rawTo) subject = `Clear ${name}`;
    else subject = `Edit ${name} (+${diff.add} −${diff.del})`;
    return { ...base, from: null, to: null, diff, subject };
  }
  if (cat === "title") {
    return { ...base, from, to, words: wordDiff(from || "", to || ""), subject: "Rename ticket" };
  }
  let subject;
  if (cat === "status") subject = `Move to ${to || "(none)"}`;
  else if (cat === "assignee") subject = to ? `Assign to ${to}` : `Unassign ${from || ""}`.trim();
  else if (cat === "links" || cat === "weblinks") subject = to ? to : `Remove: ${from || ""}`;
  else if (cat === "attachments") subject = to ? `Attach ${to}` : `Remove attachment ${from || ""}`;
  else if (fieldId.toLowerCase() === "labels") {
    const a = (from || "").split(" ").filter(Boolean), b = (to || "").split(" ").filter(Boolean);
    const plus = b.filter((x) => !a.includes(x)).map((x) => "+" + x);
    const minus = a.filter((x) => !b.includes(x)).map((x) => "−" + x);
    subject = `Labels ${[...plus, ...minus].join(" ")}`.trim();
  } else if (!from) subject = `Set ${label} to ${to || "(empty)"}`;
  else if (!to) subject = `Clear ${label}`;
  else subject = `${label}: ${from} → ${to}`;
  const change = { ...base, from, to, subject };
  if (cat === "status") change.status = { from, to };
  return change;
}

// ------------------------------------------------------------------ build --
function devSummary(issue) {
  const schema = issue.schema || {};
  const fields = issue.fields || {};
  const fieldId = Object.keys(schema).sort().find((k) => schema[k] && schema[k].custom === "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummarycf");
  if (!fieldId || typeof fields[fieldId] !== "string") return null;
  const m = /json=(\{.*\})\s*\}\s*$/.exec(fields[fieldId]);
  if (!m) return null;
  let parsed;
  try { parsed = JSON.parse(m[1]); } catch { return null; }
  const s = (parsed.cachedValue && parsed.cachedValue.summary) || {};
  const o = (k) => (s[k] && s[k].overall) || null;
  const pr = o("pullrequest"), build = o("build"), dep = o("deployment-environment"), br = o("branch"), cm = o("repository");
  if (!pr && !build && !dep && !br && !cm) return null;
  return {
    branches: br ? br.count || 0 : 0,
    commits: cm ? cm.count || 0 : 0,
    pull_requests: pr ? pr.count || 0 : 0,
    pull_request_state: pr ? String(pr.state || "") : "",
    builds: build ? build.count || 0 : 0,
    failed_builds: build ? build.failedBuildCount || 0 : 0,
    deployments: dep ? dep.count || 0 : 0,
  };
}

function initialValue(changelog, fieldKey, current) {
  for (const h of changelog) {
    for (const it of h.items || []) {
      if (String(it.fieldId || it.field || "").toLowerCase() === fieldKey) {
        return side(it, "fromString");
      }
    }
  }
  return current;
}

function commentBody(c) {
  if (typeof c.renderedBody === "string" && c.renderedBody.trim()) return { format: "html", text: repair(c.renderedBody) };
  const fmt = c.body_format || (parseAdf(c.body) ? "adf" : "wiki");
  if (fmt === "html") return { format: "html", text: repair(String(c.body || "")) };
  return { format: "wiki", text: toWiki(c.body) };
}

function bodyText(body) {
  return body.format === "html" ? htmlToText(body.text) : wikiToText(body.text);
}

export function buildModel(bundle, opts = {}) {
  const tz = opts.tz === "utc" ? "utc" : "local";
  const automation = new Set(opts.automationAccounts || []);
  const exclude = new Set((opts.excludeFields || []).map((x) => String(x).toLowerCase()));
  const issue = bundle.issue || {};
  const f = issue.fields || {};
  const site = String(bundle.site || "").replace(/\/+$/, "");
  const key = String(issue.key || bundle.key || "");
  const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
  const changelog = (bundle.changelog || []).slice()
    .sort((a, b) => ((toEpochMs(a.created) ?? 0) - (toEpochMs(b.created) ?? 0)) || cmp(String(a.id), String(b.id)));
  const warnings = [];
  const isBot = (u) => Boolean(u && (u.accountType === "app" || automation.has(idOf(u))));
  const ts = (raw) => renderTs(toEpochMs(raw), tz);
  const excluded = new Set();

  const commits = [];
  const created = toEpochMs(f.created);
  const creator = f.creator || f.reporter || null;
  const initial = (k, cur) => initialValue(changelog, k, cur);
  const nameField = (v) => (v && typeof v === "object" ? v.displayName || v.name || v.value || null : v == null ? null : String(v));
  const createdChanges = [];
  const add = (cat, label, fieldKey, value) => {
    if (exclude.has(fieldKey) || value == null || value === "") return;
    createdChanges.push({ cat, label, field_id: fieldKey, from: null, to: cleanValue(value) });
  };
  add("fields", "Type", "issuetype", initial("issuetype", nameField(f.issuetype)));
  add("status", "Status", "status", initial("status", nameField(f.status)));
  add("fields", "Priority", "priority", initial("priority", nameField(f.priority)));
  add("assignee", "Assignee", "assignee", initial("assignee", nameField(f.assignee)));
  add("fields", "Reporter", "reporter", initial("reporter", nameField(f.reporter)));
  add("title", "Title", "summary", initial("summary", f.summary == null ? null : String(f.summary)));
  // The first description edit's "from" is the original text (always wiki/ADF).
  // With no edits, the current value is original, in whatever format the
  // fetch path declared (REST v2 gives wiki; an MCP may give HTML).
  const current = f.description == null ? null : typeof f.description === "string" ? f.description : JSON.stringify(f.description);
  const firstDesc = initial("description", current);
  const descHtml = firstDesc === current && issue.description_format === "html";
  if (!exclude.has("description") && firstDesc) {
    const change = { cat: "description", label: "Description", field_id: "description", from: null, to: null };
    if (descHtml) change.initial_html = repair(firstDesc);
    else change.initial = splitLines(unescapeDisplay(toWiki(firstDesc)));
    createdChanges.push(change);
  }
  if (created != null) {
    commits.push({ id: "i" + String(issue.id || key), kind: "created", ms: created, ts: ts(f.created),
      author: nameOf(creator), author_id: idOf(creator), bot: isBot(creator),
      subject: `Create ${key}`, changes: createdChanges });
  }

  for (const h of changelog) {
    const items = [];
    for (const it of h.items || []) {
      const k1 = String(it.fieldId || "").toLowerCase(), k2 = String(it.field || "").toLowerCase();
      if (exclude.has(k1) || exclude.has(k2)) { excluded.add(labelOf(it)); continue; }
      items.push(it);
    }
    if (!items.length) continue;
    const changes = items.map(toChange)
      .map((c, i) => [c, i]).sort((x, y) => ((PRIORITY[x[0].cat] ?? 9) - (PRIORITY[y[0].cat] ?? 9)) || x[1] - y[1]).map((x) => x[0]);
    const ms = toEpochMs(h.created);
    if (ms == null) { warnings.push(`Changelog entry ${h.id} has no readable date and was skipped.`); continue; }
    const commit = { id: String(h.id), kind: "history", ms, ts: ts(h.created), author: nameOf(h.author), author_id: idOf(h.author),
      bot: isBot(h.author), subject: changes[0].subject + (changes.length > 1 ? ` (+${changes.length - 1} more)` : ""), changes };
    const st = changes.find((c) => c.status);
    if (st) commit.transition = st.status;
    commits.push(commit);
  }

  if (!exclude.has("comment")) {
    for (const c of bundle.comments || []) {
      const ms = toEpochMs(c.created);
      if (ms == null) { warnings.push(`Comment ${c.id} has no readable date and was skipped.`); continue; }
      const body = commentBody(c);
      const commit = { id: "c" + String(c.id), kind: "comment", ms, ts: ts(c.created), author: nameOf(c.author), author_id: idOf(c.author),
        bot: isBot(c.author), subject: firstLine(bodyText(body)) || "Comment", changes: [{ cat: "comments", label: "Comment", field_id: "comment", from: null, to: null }], body };
      if (c.updated && toEpochMs(c.updated) != null && toEpochMs(c.updated) - ms >= 1000) commit.edited = ts(c.updated);
      if (c.parentId != null) commit.parent = "c" + String(c.parentId);
      if (c.visibility && c.visibility.value) commit.visibility = String(c.visibility.value);
      commits.push(commit);
    }
  }

  if (!exclude.has("worklog")) {
    for (const w of bundle.worklogs || []) {
      const ms = toEpochMs(w.created || w.started);
      if (ms == null) { warnings.push(`Worklog ${w.id} has no readable date and was skipped.`); continue; }
      const spent = String(w.timeSpent || "");
      const commit = { id: "w" + String(w.id), kind: "worklog", ms, ts: ts(w.created || w.started), author: nameOf(w.author), author_id: idOf(w.author),
        bot: isBot(w.author), subject: `Log ${spent || "time"}`,
        changes: [{ cat: "worklogs", label: "Time spent", field_id: "worklog", from: null, to: spent || null }] };
      if (w.started) commit.started = ts(w.started);
      if (w.comment) commit.body = { format: "wiki", text: toWiki(w.comment) };
      if (w.updated && toEpochMs(w.updated) != null && toEpochMs(w.updated) - ms >= 1000) commit.edited = ts(w.updated);
      commits.push(commit);
    }
  }

  const KIND = { created: 0, history: 1, comment: 2, worklog: 3 };
  commits.sort((a, b) => (a.ms - b.ms) || (KIND[a.kind] - KIND[b.kind]) || cmp(a.id, b.id));
  for (const c of commits) delete c.ms;

  const completeness = bundle.completeness || {};
  const fetch = [];
  for (const [source, what] of [["changelog", "Changelog entries"], ["comments", "Comments"], ["worklogs", "Worklogs"]]) {
    const cinfo = completeness[source];
    const got = (bundle[source] || []).length;
    if (!cinfo) {
      fetch.push({ what, got, total: null, pages: null, complete: false });
      warnings.push(`${what}: the bundle does not say whether every page was fetched.`);
      continue;
    }
    const total = cinfo.total == null ? null : Number(cinfo.total);
    const complete = cinfo.complete !== false && total != null && got >= total;
    fetch.push({ what, got, total, pages: cinfo.pages == null ? null : Number(cinfo.pages), complete });
    if (!complete) warnings.push(`${what}: fetched ${got} of ${total == null ? "an unknown number" : total}. This history is incomplete.`);
  }
  for (const e of bundle.errors || []) warnings.push(`${e.source}: ${e.message}`);

  const person = (v) => (v ? nameOf(v) : null);
  const parent = f.parent ? { key: String(f.parent.key || ""), summary: repair(String((f.parent.fields && f.parent.fields.summary) || "")) } : null;
  return {
    model_version: MODEL_VERSION,
    site,
    fetched_at: bundle.fetched_at ? ts(bundle.fetched_at) : null,
    ticket: {
      key, url: site ? `${site}/browse/${key}` : "",
      summary: repair(String(f.summary || "")),
      type: nameField(f.issuetype), status: nameField(f.status), priority: nameField(f.priority),
      assignee: person(f.assignee), reporter: person(f.reporter), parent,
      created: ts(f.created), updated: ts(f.updated),
    },
    dev: devSummary(issue),
    defaults: {
      types: TYPES.filter((t) => (opts.types || TYPES).includes(t)),
      order: opts.order === "asc" ? "asc" : "desc",
      hide_automation: Boolean(opts.hideAutomation),
    },
    excluded_fields: [...excluded].sort(),
    fetch,
    warnings,
    commits,
  };
}

export function toJson(model) {
  return JSON.stringify(model).replace(/</g, "\\u003c");
}

const escHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function renderPage(template, model) {
  const marker = "/*__DATA__*/null";
  const at = template.indexOf(marker);
  if (at < 0) throw new Error("template has no /*__DATA__*/null placeholder");
  const title = escHtml(`${model.ticket.key} History`);
  const head = template.slice(0, at).split("__TITLE__").join(title);
  return head + toJson(model) + template.slice(at + marker.length);
}

// -------------------------------------------------------------------- cli --
export function expandUser(p) {
  return p && (p === "~" || p.startsWith("~/") || p.startsWith("~\\")) ? path.join(homedir(), p.slice(1)) : p;
}

export function parseArgs(argv) {
  const a = { bundle: null, config: null, template: null, out: null, tz: null, types: null, order: null, hideAutomation: null };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const next = () => { if (i + 1 >= argv.length) throw new Error(`${k} needs a value`); return argv[++i]; };
    if (k === "--bundle") a.bundle = next();
    else if (k === "--config") a.config = next();
    else if (k === "--template") a.template = next();
    else if (k === "--out") a.out = next();
    else if (k === "--tz") a.tz = next();
    else if (k === "--types") a.types = next().split(",").map((s) => s.trim()).filter(Boolean);
    else if (k === "--order") a.order = next();
    else if (k === "--hide-automation") a.hideAutomation = true;
    else if (k === "--show-automation") a.hideAutomation = false;
    else throw new Error(`unknown argument ${k}`);
  }
  if (!a.bundle) throw new Error("--bundle is required");
  if (a.tz && !["local", "utc"].includes(a.tz)) throw new Error("--tz must be local or utc");
  if (a.order && !["asc", "desc"].includes(a.order)) throw new Error("--order must be asc or desc");
  if (a.types) for (const t of a.types) if (!TYPES.includes(t)) throw new Error(`unknown type ${t}; expected one of ${TYPES.join(",")}`);
  return a;
}

function loadConfig(p) {
  const file = expandUser(p || "~/.jira-ticket-history/config.json");
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch (e) {
    if (p) throw new Error(`cannot read config ${file}: ${e.message}`);
    return {};
  }
}

export function main(argv) {
  let args;
  try {
    args = parseArgs(argv);
  } catch (e) {
    process.stderr.write(`error: ${e.message}\n`);
    return 1;
  }
  const cfg = loadConfig(args.config);
  const hist = cfg.history || {}, out = cfg.output || {};
  const bundle = JSON.parse(readFileSync(args.bundle === "-" ? 0 : expandUser(args.bundle), "utf8"));
  const here = path.dirname(fileURLToPath(import.meta.url));
  const template = readFileSync(expandUser(args.template) || path.join(here, "..", "assets", "template.html"), "utf8");
  const model = buildModel(bundle, {
    tz: args.tz || out.timezone || "local",
    automationAccounts: cfg.automation_accounts || [],
    excludeFields: hist.exclude_fields || [],
    types: args.types || hist.types || TYPES,
    order: args.order || out.order || "desc",
    hideAutomation: args.hideAutomation ?? Boolean(out.hide_automation),
  });
  const html = renderPage(template, model);
  const target = expandUser(args.out) || `${model.ticket.key || "ticket"}-history.html`;
  mkdirSync(path.dirname(path.resolve(target)), { recursive: true });
  writeFileSync(target, html, "utf8");
  for (const w of model.warnings) process.stderr.write(`warning: ${w}\n`);
  process.stdout.write(JSON.stringify({ out: path.resolve(target), entries: model.commits.length, fetch: model.fetch, warnings: model.warnings }) + "\n");
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  process.exitCode = main(process.argv.slice(2));
}
