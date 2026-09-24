import test from "node:test";
import assert from "node:assert/strict";
import { homedir } from "node:os";
import {
  parseIso,
  isoString,
  render,
  buildTicketPattern,
  extractTickets,
  shortBranch,
  parseLog,
  padDate,
  dedupe,
  parseArgs,
  expandUser,
} from "../collect_git.mjs";

const US = "\x1f";
const RS = "\x1e";

test("parses a positive-offset timestamp and round-trips it", () => {
  const parsed = parseIso("2026-09-22T09:14:03+03:00");
  assert.equal(isoString(parsed), "2026-09-22T09:14:03+03:00");
  assert.equal(parsed.offsetMinutes, 180);
});

test("parses a negative offset without losing the sign", () => {
  const parsed = parseIso("2026-09-22T23:30:00-07:00");
  assert.equal(parsed.offsetMinutes, -420);
  assert.equal(isoString(parsed), "2026-09-22T23:30:00-07:00");
});

test("accepts a bare Z as UTC", () => {
  assert.equal(isoString(parseIso("2026-01-02T03:04:05Z")), "2026-01-02T03:04:05+00:00");
});

test("rejects garbage rather than guessing a date", () => {
  assert.throws(() => parseIso("last tuesday"), RangeError);
});

test("tz=commit renders the wall clock the developer saw", () => {
  // 23:30-07:00 is 06:30 UTC the NEXT day; the commit's own day is the 22nd.
  assert.deepEqual(render(parseIso("2026-09-22T23:30:00-07:00"), "commit"), [
    "2026-09-22",
    "23:30",
  ]);
});

test("ticket prefixes restrict matching to real project keys", () => {
  const pattern = buildTicketPattern(["ABC", "OPS"], null);
  assert.deepEqual(
    extractTickets(pattern, "ABC-12 bump to UTF-8 and SHA-256 for OPS-7"),
    ["ABC-12", "OPS-7"]
  );
});

test("the generic pattern is the one that mistakes UTF-8 for a ticket", () => {
  // Documents exactly why configuring project keys matters.
  assert.deepEqual(extractTickets(buildTicketPattern([], null), "bump to UTF-8"), ["UTF-8"]);
});

test("ticket ids are upper-cased and de-duplicated in first-seen order", () => {
  const pattern = buildTicketPattern(["abc"], null);
  assert.deepEqual(extractTickets(pattern, "abc-9 again ABC-9 then Abc-4"), ["ABC-9", "ABC-4"]);
});

test("ticket ids are collected across subject, body and branch", () => {
  const pattern = buildTicketPattern(["ABC"], null);
  assert.deepEqual(
    extractTickets(pattern, "fix login", "refs ABC-2", "feature/ABC-1-login"),
    ["ABC-2", "ABC-1"]
  );
});

test("an explicit ticket pattern overrides the prefix list", () => {
  const pattern = buildTicketPattern(["ABC"], "TASK_\\d+");
  assert.deepEqual(extractTickets(pattern, "ABC-1 and TASK_99"), ["TASK_99"]);
});

test("branch refs are stripped to a readable name", () => {
  assert.equal(shortBranch("refs/heads/feature/ABC-1"), "feature/ABC-1");
  assert.equal(shortBranch("refs/remotes/origin/main"), "origin/main");
});

test("a bare sha or HEAD is not a branch name", () => {
  assert.equal(shortBranch("9f3c1ab9f3c1ab9f3c1ab9f3c1ab9f3c1ab9f3c1"), null);
  assert.equal(shortBranch("HEAD"), null);
  assert.equal(shortBranch(""), null);
});

test("log parsing survives subjects containing commas and quotes", () => {
  const raw =
    ["sha1", "sha1s", "2026-09-22T09:14:03+03:00", "Dev", "d@x.io", "refs/heads/main",
      'ABC-1 fix "login", again', "body"].join(US) + RS;
  const [record] = parseLog(raw);
  assert.equal(record[6], 'ABC-1 fix "login", again');
});

test("log parsing ignores the trailing blank record", () => {
  const one = ["a", "b", "c", "d", "e", "f", "g", "h"].join(US) + RS;
  assert.equal(parseLog(one + "\n").length, 1);
});

test("a short record is padded rather than throwing", () => {
  const [record] = parseLog(["a", "b"].join(US) + RS);
  assert.equal(record.length, 8);
  assert.equal(record[7], "");
});

test("date padding crosses month boundaries", () => {
  assert.equal(padDate("2026-03-01", -7), "2026-02-22");
  assert.equal(padDate("2026-12-31", 1), "2027-01-01");
});

test("dedupe drops a repo listed twice but keeps a cherry-pick elsewhere", () => {
  const a = { repo: "web", ref: "abc1234", timestamp: "2026-09-22T09:14:03+03:00" };
  const b = { repo: "api", ref: "abc1234", timestamp: "2026-09-22T09:14:03+03:00" };
  assert.equal(dedupe([a, { ...a }, b]).length, 2);
});

test("parseArgs collects repeatable flags", () => {
  const opts = parseArgs([
    "--repo", "a", "--repo", "b",
    "--since", "2026-09-01", "--until", "2026-09-07",
    "--author", "dev@x.io", "--ticket-prefix", "ABC",
  ]);
  assert.deepEqual(opts.repo, ["a", "b"]);
  assert.deepEqual(opts.author, ["dev@x.io"]);
  assert.deepEqual(opts.ticketPrefix, ["ABC"]);
  assert.equal(opts.tz, "local", "local is the shared convention across sources");
  assert.equal(opts.allBranches, true);
});

test("parseArgs refuses a missing range instead of inventing one", () => {
  assert.throws(() => parseArgs(["--repo", "a"]), /--since and --until are required/);
});

test("parseArgs rejects an unknown flag", () => {
  assert.throws(
    () => parseArgs(["--repo", "a", "--since", "x", "--until", "y", "--nope"]),
    /unknown argument/
  );
});

test("a leading ~ expands in repo and output paths too", () => {
  assert.equal(expandUser("~"), homedir());
  assert.ok(expandUser("~/work/api").startsWith(homedir()));
  assert.equal(expandUser("~someone/x"), "~someone/x", "parity with the Python twin");
  assert.equal(expandUser("/abs/repo"), "/abs/repo");
});
