import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { parseTicket, authHeader, pageAll, fetchHistory, getJson, HttpError, parseArgs } from "../fetch_history.mjs";

const SITE = "https://example.atlassian.net";
const API = `${SITE}/rest/api/2/issue/DEMO-42`;
const OPTS = { pageSize: 2, maxPages: 50 };

// A fake Jira: routes by path, pages by startAt/maxResults, records every URL.
function fakeJira({ changelog = 5, comments = 3, worklogStatus = 200, changelogStatus = 200, dc = false } = {}) {
  const seen = [];
  const list = (n, prefix) => Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i + 1}`, created: "2026-03-02T10:00:00.000+0200" }));
  const all = { changelog: list(changelog, "h"), comments: list(comments, "c"), worklogs: list(1, "w") };
  const get = async (url) => {
    seen.push(url);
    const u = new URL(url);
    const startAt = Number(u.searchParams.get("startAt") || 0), max = Number(u.searchParams.get("maxResults") || 50);
    const slice = (arr) => arr.slice(startAt, startAt + max);
    if (u.pathname.endsWith("/serverInfo")) return { deploymentType: dc ? "Server" : "Cloud" };
    if (u.pathname.endsWith("/changelog")) {
      if (changelogStatus !== 200) throw new HttpError(changelogStatus, "nope");
      const values = slice(all.changelog);
      return { startAt, maxResults: max, total: all.changelog.length, isLast: startAt + values.length >= all.changelog.length, values };
    }
    if (u.pathname.endsWith("/comment")) return { startAt, maxResults: max, total: all.comments.length, comments: slice(all.comments) };
    if (u.pathname.endsWith("/worklog")) {
      if (worklogStatus !== 200) throw new HttpError(worklogStatus, "no permission");
      return { startAt: 0, maxResults: 5000, total: 1, worklogs: all.worklogs }; // DC style: ignores paging
    }
    if (u.searchParams.get("expand") === "changelog") return { changelog: { startAt: 0, maxResults: all.changelog.length, total: all.changelog.length, histories: all.changelog } };
    return { id: "10042", key: "DEMO-42", fields: { summary: "x" }, names: {}, schema: {} };
  };
  return { get, seen, all };
}

test("tickets are read from keys and from URLs", () => {
  assert.deepEqual(parseTicket("demo-42", "https://x.test/"), { site: "https://x.test", key: "DEMO-42" });
  assert.deepEqual(parseTicket("https://acme.atlassian.net/browse/OPS-7?atlOrigin=abc"), { site: "https://acme.atlassian.net", key: "OPS-7" });
  assert.deepEqual(parseTicket("https://jira.acme.io/secure/RapidBoard.jspa?rapidView=1&selectedIssue=OPS-8"), { site: "https://jira.acme.io", key: "OPS-8" });
  assert.equal(parseTicket("not a ticket"), null);
});

test("Cloud uses Basic auth, Data Center a bearer token", () => {
  assert.equal(authHeader("cloud", "a@b.c", "t"), "Basic " + Buffer.from("a@b.c:t").toString("base64"));
  assert.equal(authHeader("datacenter", null, "pat"), "Bearer pat");
});

test("paging follows isLast to the end", async () => {
  const j = fakeJira({ changelog: 5 });
  const r = await pageAll(`${API}/changelog`, "values", j.get, OPTS);
  assert.equal(r.items.length, 5);
  assert.deepEqual(r.info, { got: 5, total: 5, pages: 3, complete: true });
});

test("paging without isLast stops on total", async () => {
  const j = fakeJira({ comments: 3 });
  const r = await pageAll(`${API}/comment?orderBy=created`, "comments", j.get, OPTS);
  assert.deepEqual(r.info, { got: 3, total: 3, pages: 2, complete: true });
  assert.ok(j.seen[0].includes("orderBy=created&startAt=0&maxResults=2"));
});

test("an empty page before the end is incomplete, not finished", async () => {
  const get = async () => ({ total: 10, values: [], isLast: false });
  const r = await pageAll(`${API}/changelog`, "values", get, OPTS);
  assert.deepEqual(r.info, { got: 0, total: 10, pages: 1, complete: false });
});

test("the page cap is reported instead of silently truncating", async () => {
  const j = fakeJira({ changelog: 9 });
  const r = await pageAll(`${API}/changelog`, "values", j.get, { pageSize: 2, maxPages: 2 });
  assert.equal(r.capped, true);
  assert.equal(r.info.complete, false);
  assert.equal(r.info.got, 4);
});

test("fetches every source to the end and records completeness", async () => {
  const j = fakeJira({ changelog: 5, comments: 3 });
  const b = await fetchHistory({ site: SITE + "/", key: "DEMO-42", deployment: "auto", email: "a@b.c", token: "t", ...OPTS, getImpl: (u) => j.get(u), now: new Date(Date.UTC(2026, 2, 4)) });
  assert.equal(b.deployment, "cloud");
  assert.equal(b.changelog.length, 5);
  assert.equal(b.comments.length, 3);
  assert.equal(b.worklogs.length, 1);
  assert.deepEqual(b.completeness.changelog, { got: 5, total: 5, pages: 3, complete: true });
  assert.deepEqual(b.errors, []);
  assert.equal(b.fetched_at, "2026-03-04T00:00:00.000Z");
  assert.equal(b.issue.description_format, "wiki");
  assert.ok(j.seen.some((u) => u.includes("expand=renderedBody")));
  assert.ok(j.seen.every((u) => !u.includes("expand=changelog")), "Cloud never uses the capped expand");
});

test("a failing optional source is recorded and the rest still arrives", async () => {
  const j = fakeJira({ worklogStatus: 403 });
  const b = await fetchHistory({ site: SITE, key: "DEMO-42", deployment: "cloud", email: "a", token: "t", ...OPTS, getImpl: (u) => j.get(u) });
  assert.deepEqual(b.errors, [{ source: "worklogs", message: "no permission" }]);
  assert.deepEqual(b.completeness.worklogs, { got: 0, total: null, pages: 0, complete: false });
  assert.equal(b.changelog.length, 5);
});

test("Data Center without the changelog endpoint falls back to expand=changelog", async () => {
  const j = fakeJira({ changelogStatus: 404, dc: true, changelog: 4 });
  const b = await fetchHistory({ site: SITE, key: "DEMO-42", deployment: "auto", email: null, token: "pat", ...OPTS, getImpl: (u) => j.get(u) });
  assert.equal(b.deployment, "datacenter");
  assert.equal(b.changelog.length, 4);
  assert.deepEqual(b.completeness.changelog, { got: 4, total: 4, pages: 1, complete: true });
});

test("429 responses are retried after Retry-After", async () => {
  let calls = 0;
  const server = http.createServer((req, res) => {
    calls++;
    if (calls === 1) { res.writeHead(429, { "Retry-After": "0" }); res.end(); return; }
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ ok: true, auth: req.headers.authorization }));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    const url = `http://127.0.0.1:${server.address().port}/x`;
    const waits = [];
    const body = await getJson(url, { Authorization: "Bearer t" }, { sleep: async (s) => waits.push(s) });
    assert.deepEqual(body, { ok: true, auth: "Bearer t" });
    assert.equal(calls, 2);
    assert.deepEqual(waits, [0]);
  } finally {
    server.close();
  }
});

test("HTTP errors carry a readable reason", async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ errorMessages: ["Issue does not exist"] }));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  try {
    await assert.rejects(getJson(`http://127.0.0.1:${server.address().port}/x`, {}), (e) => e.status === 404 && /Issue does not exist/.test(e.message));
  } finally {
    server.close();
  }
});

test("arguments are validated", () => {
  assert.throws(() => parseArgs([]), /--key/);
  assert.throws(() => parseArgs(["--key", "A-1", "--deployment", "moon"]), /--deployment/);
  assert.throws(() => parseArgs(["--key", "A-1", "--page-size", "0"]), /page-size/);
  assert.equal(parseArgs(["--key", "A-1", "--page-size", "25"]).pageSize, 25);
});
