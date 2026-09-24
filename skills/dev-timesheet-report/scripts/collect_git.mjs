// Scan local git repositories for one developer's commits in a date range.
// Mirrors collect_git.py field-for-field: same CLI flags, same event schema,
// same author-date filtering over a padded committer-date window (a rebase or
// squash rewrites committer date, and a timesheet cares when work was authored),
// and the same default of rendering in the machine's timezone so every source
// in this skill agrees on which day a piece of work belongs to.
import { spawnSync } from "node:child_process";
import { writeFileSync, mkdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Field/record separators that will not appear in commit metadata.
const US = "\x1f";
const RS = "\x1e";

const PRETTY = ["%H", "%h", "%aI", "%an", "%ae", "%S", "%s", "%b"].join(US) + RS;

// See collect_git.py for why the generic pattern needs 2+ leading alphanumerics
// and why --ticket-prefix is the reliable form.
const DEFAULT_TICKET_PATTERN = "\\b[A-Z][A-Z0-9]{1,9}-\\d+\\b";

const ISO =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:Z|([+-])(\d{2}):?(\d{2}))$/;

export class GitError extends Error {}

export function parseIso(stamp) {
  const m = ISO.exec(String(stamp).trim());
  if (!m) throw new RangeError(`unparseable git timestamp: ${stamp}`);
  const [, y, mo, d, h, mi, s, sign, offH, offM] = m;
  const offsetMinutes =
    sign === undefined ? 0 : (sign === "-" ? -1 : 1) * (Number(offH) * 60 + Number(offM));
  const utcMs =
    Date.UTC(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s)) -
    offsetMinutes * 60000;
  return { utcMs, offsetMinutes, wall: { y, mo, d, h, mi, s } };
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

export function isoString(parsed) {
  const { wall, offsetMinutes } = parsed;
  if (offsetMinutes === 0) return `${wall.y}-${wall.mo}-${wall.d}T${wall.h}:${wall.mi}:${wall.s}+00:00`;
  const sign = offsetMinutes < 0 ? "-" : "+";
  const abs = Math.abs(offsetMinutes);
  return (
    `${wall.y}-${wall.mo}-${wall.d}T${wall.h}:${wall.mi}:${wall.s}` +
    `${sign}${pad2(Math.floor(abs / 60))}:${pad2(abs % 60)}`
  );
}

export function render(parsed, tzMode) {
  if (tzMode === "local") {
    const d = new Date(parsed.utcMs);
    return [
      `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`,
      `${pad2(d.getHours())}:${pad2(d.getMinutes())}`,
    ];
  }
  const { wall } = parsed;
  return [`${wall.y}-${wall.mo}-${wall.d}`, `${wall.h}:${wall.mi}`];
}

export function buildTicketPattern(prefixes, explicit) {
  if (explicit) return new RegExp(explicit, "gi");
  if (prefixes && prefixes.length) {
    const keys = prefixes.map((p) => p.toUpperCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    return new RegExp(`\\b(?:${keys})-\\d+\\b`, "gi");
  }
  return new RegExp(DEFAULT_TICKET_PATTERN, "g");
}

export function extractTickets(pattern, ...texts) {
  const found = [];
  for (const text of texts) {
    if (!text) continue;
    pattern.lastIndex = 0;
    for (const match of String(text).matchAll(pattern)) {
      const key = match[0].toUpperCase();
      if (!found.includes(key)) found.push(key);
    }
  }
  return found;
}

export function shortBranch(sourceRef) {
  let ref = (sourceRef || "").trim();
  if (!ref || ref === "HEAD") return null;
  for (const prefix of ["refs/heads/", "refs/remotes/", "refs/tags/"]) {
    if (ref.startsWith(prefix)) {
      ref = ref.slice(prefix.length);
      break;
    }
  }
  if (/^[0-9a-f]{7,40}$/.test(ref)) return null;
  return ref || null;
}

export function parseLog(raw) {
  const records = [];
  for (let chunk of String(raw).split(RS)) {
    chunk = chunk.replace(/^\n+|\n+$/g, "");
    if (!chunk.trim()) continue;
    const fields = chunk.split(US);
    while (fields.length < 8) fields.push("");
    records.push(fields.slice(0, 8));
  }
  return records;
}

function runGit(repo, args) {
  const proc = spawnSync("git", ["-C", repo, ...args], {
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  if (proc.error && proc.error.code === "ENOENT") {
    throw new GitError("git executable not found on PATH");
  }
  if (proc.status !== 0) {
    throw new GitError((proc.stderr || proc.stdout || "").trim() || "git failed");
  }
  return proc.stdout;
}

// Expand a leading `~` to the user's home directory. Deliberately narrower than
// Python's os.path.expanduser, which also resolves `~otheruser`: Node has no
// equivalent and the twins have to agree on every input. Repo paths come from a
// config file as often as a shell, so nothing else would expand the `~`.
export function expandUser(target) {
  if (!target) return target;
  const text = String(target);
  if (text === "~") return homedir();
  if (text.startsWith("~/") || text.startsWith("~\\")) {
    return path.join(homedir(), text.slice(2));
  }
  return text;
}

export function padDate(dateStr, days) {
  const [y, m, d] = dateStr.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return `${dt.getUTCFullYear()}-${pad2(dt.getUTCMonth() + 1)}-${pad2(dt.getUTCDate())}`;
}

function repoName(p) {
  return path.basename(path.resolve(p.replace(/[/\\]+$/, ""))) || p;
}

function collectRepo(repo, opts, pattern) {
  const args = [
    "log",
    "--source",
    opts.allBranches ? "--all" : "--branches",
    "--date-order",
    `--since=${padDate(opts.since, -opts.padDays)}`,
    `--until=${padDate(opts.until, opts.padDays + 1)}`,
    `--pretty=format:${PRETTY}`,
  ];
  if (!opts.includeMerges) args.push("--no-merges");
  for (const author of opts.author) args.push(`--author=${author}`);

  const name = opts.repoName || repoName(repo);
  const events = [];
  for (const [sha, shortSha, stamp, an, ae, sourceRef, subject, body] of parseLog(
    runGit(repo, args)
  )) {
    let parsed;
    try {
      parsed = parseIso(stamp);
    } catch {
      continue;
    }
    const [date, time] = render(parsed, opts.tz);
    if (date < opts.since || date > opts.until) continue;
    const branch = shortBranch(sourceRef);
    events.push({
      timestamp: isoString(parsed),
      date,
      time,
      source: "local-git",
      type: "commit",
      repo: name,
      ref: shortSha || sha.slice(0, 9),
      branch,
      ticket_ids: extractTickets(pattern, subject, body, branch),
      subject,
      author: `${an} <${ae}>`.trim(),
      url: null,
    });
  }
  return events;
}

export function dedupe(events) {
  const seen = new Set();
  const out = [];
  for (const event of events) {
    const key = `${event.repo}\u0000${event.ref}\u0000${event.timestamp}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(event);
  }
  return out;
}

const USAGE = `Usage: collect_git.mjs --repo PATH [--repo PATH ...] --since YYYY-MM-DD --until YYYY-MM-DD
  [--author PATTERN ...] [--ticket-prefix KEY ...] [--ticket-pattern REGEX]
  [--tz commit|local] [--local-branches] [--include-merges] [--pad-days N]
  [--repo-name NAME] [--out PATH]`;

export function parseArgs(argv) {
  const opts = {
    repo: [],
    since: null,
    until: null,
    author: [],
    ticketPrefix: [],
    ticketPattern: null,
    tz: "local",
    allBranches: true,
    includeMerges: false,
    padDays: 7,
    repoName: null,
    out: null,
  };
  const takesValue = {
    "--repo": (v) => opts.repo.push(v),
    "--since": (v) => (opts.since = v),
    "--until": (v) => (opts.until = v),
    "--author": (v) => opts.author.push(v),
    "--ticket-prefix": (v) => opts.ticketPrefix.push(v),
    "--ticket-pattern": (v) => (opts.ticketPattern = v),
    "--tz": (v) => (opts.tz = v),
    "--pad-days": (v) => (opts.padDays = Number(v)),
    "--repo-name": (v) => (opts.repoName = v),
    "--out": (v) => (opts.out = v),
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--local-branches") opts.allBranches = false;
    else if (arg === "--all-branches") opts.allBranches = true;
    else if (arg === "--include-merges") opts.includeMerges = true;
    else if (takesValue[arg]) {
      i += 1;
      if (i >= argv.length) throw new Error(`${arg} needs a value`);
      takesValue[arg](argv[i]);
    } else throw new Error(`unknown argument: ${arg}`);
  }
  if (!opts.repo.length) throw new Error("--repo is required");
  if (!opts.since || !opts.until) throw new Error("--since and --until are required");
  if (!["commit", "local"].includes(opts.tz)) throw new Error("--tz must be commit or local");
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
  if (opts.repoName && opts.repo.length > 1) {
    console.error("--repo-name applies to a single --repo");
    process.exit(1);
  }
  if (opts.since > opts.until) {
    console.error("--since must not be after --until");
    process.exit(1);
  }

  const pattern = buildTicketPattern(opts.ticketPrefix, opts.ticketPattern);
  let events = [];
  const skipped = [];
  for (const repo of opts.repo.map(expandUser)) {
    let isDir = false;
    try {
      isDir = statSync(repo).isDirectory();
    } catch {
      isDir = false;
    }
    if (!isDir) {
      skipped.push({ repo, reason: "path does not exist" });
      continue;
    }
    try {
      events.push(...collectRepo(repo, opts, pattern));
    } catch (err) {
      if (!(err instanceof GitError)) throw err;
      skipped.push({ repo, reason: err.message });
    }
  }

  events = dedupe(events);
  events.sort((a, b) =>
    `${a.date}${a.time}${a.repo}${a.ref}`.localeCompare(`${b.date}${b.time}${b.repo}${b.ref}`)
  );
  const text = JSON.stringify({ events, skipped }, null, 2);
  if (opts.out) {
    const target = expandUser(opts.out);
    try {
      const parent = path.dirname(path.resolve(target));
      if (parent) mkdirSync(parent, { recursive: true });
      writeFileSync(target, text + "\n", "utf8");
    } catch (err) {
      console.error(`cannot write ${target}: ${err.message}`);
      process.exit(1);
    }
    console.log(`${events.length} event(s) written to ${target}`);
  } else {
    console.log(text);
  }
  for (const entry of skipped) {
    console.error(`warning: skipped ${entry.repo} (${entry.reason})`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2));
}
