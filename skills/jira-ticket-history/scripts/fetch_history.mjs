// Fetch everything Jira knows about one ticket's history into a raw bundle.
// Mirrors fetch_history.py: same endpoints, same paging rules, same bundle
// shape. Read-only -- every request is a GET.
//
// The one rule that matters: page every endpoint to the end and record how far
// it got. A history that stops at the first page looks complete and is not.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const BUNDLE_VERSION = 1;
const DEFAULTS = { pageSize: 100, maxPages: 500, retries: 4, maxWait: 60 };

export class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));

export function parseTicket(input, site) {
  const raw = String(input || "").trim();
  const m = /^(https?:\/\/[^/]+)(?:\/.*?)?(?:\/browse\/|[?&]selectedIssue=)([A-Z][A-Z0-9_]+-\d+)/i.exec(raw);
  if (m) return { site: m[1], key: m[2].toUpperCase() };
  if (/^[A-Z][A-Z0-9_]+-\d+$/i.test(raw)) return { site: site ? String(site).replace(/\/+$/, "") : null, key: raw.toUpperCase() };
  return null;
}

export function authHeader(deployment, email, token) {
  if (deployment === "datacenter") return `Bearer ${token}`;
  return "Basic " + Buffer.from(`${email}:${token}`).toString("base64");
}

// GET with retry on 429/503, honouring Retry-After. Returns parsed JSON.
export async function getJson(url, headers, opts = {}) {
  const retries = opts.retries ?? DEFAULTS.retries;
  const wait = opts.sleep || sleep;
  for (let attempt = 0; ; attempt++) {
    let res;
    try {
      res = await fetch(url, { headers });
    } catch (e) {
      if (attempt < retries) { await wait(2 ** attempt); continue; }
      throw new HttpError(0, `network error: ${e.message}`);
    }
    if ((res.status === 429 || res.status === 503) && attempt < retries) {
      const ra = Number(res.headers.get("retry-after"));
      await wait(Number.isFinite(ra) && ra >= 0 ? Math.min(ra, DEFAULTS.maxWait) : 2 ** attempt);
      continue;
    }
    const text = await res.text();
    if (!res.ok) throw new HttpError(res.status, describe(res.status, text));
    try {
      return JSON.parse(text);
    } catch {
      throw new HttpError(res.status, "response was not JSON");
    }
  }
}

function describe(status, text) {
  let detail = "";
  try {
    const j = JSON.parse(text);
    detail = [...(j.errorMessages || []), ...Object.values(j.errors || {})].join("; ");
  } catch {
    // body was not JSON
  }
  const base = {
    401: "authentication failed (check the email and token)",
    403: "no permission",
    404: "not found, or you have no permission to see it",
    429: "rate limited, retries exhausted",
  }[status] || `HTTP ${status}`;
  return detail ? `${base}: ${detail}` : base;
}

// Page a startAt/maxResults endpoint until Jira says it is done.
export async function pageAll(base, listKey, get, opts) {
  const size = opts.pageSize, maxPages = opts.maxPages;
  const items = [];
  let startAt = 0, pages = 0, total = null, complete = false, capped = false;
  for (;;) {
    if (pages >= maxPages) { capped = true; break; }
    const sep = base.includes("?") ? "&" : "?";
    const body = await get(`${base}${sep}startAt=${startAt}&maxResults=${size}`);
    pages++;
    const page = Array.isArray(body[listKey]) ? body[listKey] : [];
    items.push(...page);
    if (typeof body.total === "number") total = body.total;
    if (body.isLast === true) { complete = true; break; }
    if (body.isLast === undefined && total != null && items.length >= total) { complete = true; break; }
    if (!page.length) break; // Jira says there is more but sent nothing: stop, marked incomplete
    startAt += page.length;
  }
  if (complete && total == null) total = items.length;
  if (complete && total != null && items.length < total) complete = false;
  return { items, info: { got: items.length, total, pages, complete }, capped };
}

export async function fetchHistory({ site, key, deployment, email, token, pageSize, maxPages, getImpl, now }) {
  const opts = { pageSize: pageSize || DEFAULTS.pageSize, maxPages: maxPages || DEFAULTS.maxPages };
  const root = site.replace(/\/+$/, "");
  const errors = [];
  let dep = deployment;
  const headersFor = (d) => ({ Accept: "application/json", Authorization: authHeader(d, email, token) });
  const getter = (d) => (url) => (getImpl || getJson)(url, headersFor(d));

  if (!dep || dep === "auto") {
    try {
      const info = await getter(email ? "cloud" : "datacenter")(`${root}/rest/api/2/serverInfo`);
      dep = info.deploymentType === "Cloud" ? "cloud" : "datacenter";
    } catch {
      dep = email ? "cloud" : "datacenter";
    }
  }
  const get = getter(dep);
  const api = `${root}/rest/api/2/issue/${encodeURIComponent(key)}`;

  const issue = await get(`${api}?fields=*all&expand=names,schema`); // fatal if this fails

  const completeness = {};
  const bundle = {
    bundle_version: BUNDLE_VERSION, site: root, key, deployment: dep,
    fetched_at: (now || new Date()).toISOString(),
    issue: { id: issue.id, key: issue.key, fields: issue.fields || {}, names: issue.names || {}, schema: issue.schema || {}, description_format: "wiki" },
    changelog: [], comments: [], worklogs: [], completeness, errors,
  };

  // Changelog: the paged endpoint (Cloud, recent Data Center), else expand=changelog.
  try {
    const r = await pageAll(`${api}/changelog`, "values", get, opts);
    bundle.changelog = r.items;
    completeness.changelog = r.info;
    if (r.capped) errors.push({ source: "changelog", message: `stopped after ${opts.maxPages} pages` });
  } catch (e) {
    if (!(e instanceof HttpError && e.status === 404)) {
      errors.push({ source: "changelog", message: e.message });
      completeness.changelog = { got: 0, total: null, pages: 0, complete: false };
    } else {
      try {
        const body = await get(`${api}?fields=summary&expand=changelog`);
        const cl = body.changelog || {};
        bundle.changelog = cl.histories || [];
        const total = typeof cl.total === "number" ? cl.total : bundle.changelog.length;
        completeness.changelog = { got: bundle.changelog.length, total, pages: 1, complete: bundle.changelog.length >= total };
      } catch (e2) {
        errors.push({ source: "changelog", message: e2.message });
        completeness.changelog = { got: 0, total: null, pages: 0, complete: false };
      }
    }
  }

  for (const [source, url, listKey] of [
    ["comments", `${api}/comment?orderBy=created&expand=renderedBody`, "comments"],
    ["worklogs", `${api}/worklog`, "worklogs"],
  ]) {
    try {
      const r = await pageAll(url, listKey, get, opts);
      bundle[source] = r.items;
      completeness[source] = r.info;
      if (r.capped) errors.push({ source, message: `stopped after ${opts.maxPages} pages` });
    } catch (e) {
      errors.push({ source, message: e.message });
      completeness[source] = { got: 0, total: null, pages: 0, complete: false };
    }
  }
  return bundle;
}

// -------------------------------------------------------------------- cli --
function expandUser(p) {
  return p && (p === "~" || p.startsWith("~/") || p.startsWith("~\\")) ? path.join(homedir(), p.slice(1)) : p;
}

export function parseArgs(argv) {
  const a = { key: null, site: null, deployment: null, emailEnv: null, tokenEnv: null, out: null, config: null, pageSize: null, maxPages: null };
  const flags = { "--key": "key", "--site": "site", "--deployment": "deployment", "--email-env": "emailEnv", "--token-env": "tokenEnv",
    "--out": "out", "--config": "config", "--page-size": "pageSize", "--max-pages": "maxPages" };
  for (let i = 0; i < argv.length; i++) {
    const name = flags[argv[i]];
    if (!name) throw new Error(`unknown argument ${argv[i]}`);
    if (i + 1 >= argv.length) throw new Error(`${argv[i]} needs a value`);
    a[name] = argv[++i];
  }
  if (!a.key) throw new Error("--key is required (an issue key or a Jira URL)");
  if (a.deployment && !["auto", "cloud", "datacenter"].includes(a.deployment)) throw new Error("--deployment must be auto, cloud or datacenter");
  for (const k of ["pageSize", "maxPages"]) {
    if (a[k] != null) {
      const n = Number(a[k]);
      if (!Number.isInteger(n) || n < 1) throw new Error(`--${k === "pageSize" ? "page-size" : "max-pages"} must be a positive integer`);
      a[k] = n;
    }
  }
  return a;
}

export async function main(argv, env = process.env) {
  let a;
  try {
    a = parseArgs(argv);
  } catch (e) {
    process.stderr.write(`error: ${e.message}\n`);
    return 1;
  }
  let cfg = {};
  try {
    cfg = JSON.parse(readFileSync(expandUser(a.config || "~/.jira-ticket-history/config.json"), "utf8"));
  } catch (e) {
    if (a.config) { process.stderr.write(`error: cannot read config: ${e.message}\n`); return 1; }
  }
  const auth = cfg.auth || {};
  const t = parseTicket(a.key, a.site || cfg.site);
  if (!t) { process.stderr.write(`error: "${a.key}" is neither an issue key nor a Jira issue URL\n`); return 1; }
  if (!t.site) { process.stderr.write("error: no Jira site: pass --site or set \"site\" in the config\n"); return 1; }
  const deployment = a.deployment || cfg.deployment || "auto";
  const emailEnv = a.emailEnv || auth.email_env || "JIRA_EMAIL";
  const tokenEnv = a.tokenEnv || auth.token_env || "JIRA_API_TOKEN";
  const token = env[tokenEnv];
  const email = env[emailEnv];
  if (!token) { process.stderr.write(`error: not configured: the environment variable ${tokenEnv} is not set\n`); return 2; }
  if (deployment === "cloud" && !email) { process.stderr.write(`error: not configured: Jira Cloud needs ${emailEnv} as well as ${tokenEnv}\n`); return 2; }

  let bundle;
  try {
    bundle = await fetchHistory({ site: t.site, key: t.key, deployment, email, token, pageSize: a.pageSize, maxPages: a.maxPages });
  } catch (e) {
    process.stderr.write(`error: could not read ${t.key}: ${e.message}\n`);
    return 3;
  }
  const out = expandUser(a.out) || `${t.key}-bundle.json`;
  mkdirSync(path.dirname(path.resolve(out)), { recursive: true });
  writeFileSync(out, JSON.stringify(bundle), "utf8");
  for (const e of bundle.errors) process.stderr.write(`warning: ${e.source}: ${e.message}\n`);
  process.stdout.write(JSON.stringify({ out: path.resolve(out), key: t.key, deployment: bundle.deployment, completeness: bundle.completeness, errors: bundle.errors }) + "\n");
  return 0;
}

if (import.meta.url === pathToFileURL(process.argv[1] || "").href) {
  main(process.argv.slice(2)).then((code) => { process.exitCode = code; });
}
