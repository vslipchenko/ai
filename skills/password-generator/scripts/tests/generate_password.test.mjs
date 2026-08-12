import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = path.join(__dirname, "..", "generate_password.mjs");

function run(args) {
  const out = execFileSync("node", [SCRIPT, ...args], { encoding: "utf-8" });
  return JSON.parse(out);
}

test("password: respects requested length", () => {
  const [{ value }] = run(["--mode", "password", "--length", "16"]);
  assert.equal(value.length, 16);
});

test("password: covers every enabled class", () => {
  const [{ value }] = run(["--mode", "password", "--length", "24"]);
  assert.match(value, /[a-z]/);
  assert.match(value, /[A-Z]/);
  assert.match(value, /[0-9]/);
  assert.match(value, /[^a-zA-Z0-9]/);
});

test("password: --no-ambiguous strips confusable chars", () => {
  for (let i = 0; i < 20; i++) {
    const [{ value }] = run(["--mode", "password", "--length", "40", "--no-ambiguous"]);
    assert.doesNotMatch(value, /[O0Il1|`'"]/);
  }
});

test("password: --count generates multiple independent values", () => {
  const results = run(["--mode", "password", "--length", "20", "--count", "5"]);
  assert.equal(results.length, 5);
  assert.equal(new Set(results.map((r) => r.value)).size, 5);
});

test("password: length shorter than required classes exits non-zero", () => {
  assert.throws(() => run(["--mode", "password", "--length", "2"]));
});

test("passphrase: word count and separator respected", () => {
  const [{ value }] = run(["--mode", "passphrase", "--words", "5", "--separator", "_"]);
  assert.equal(value.split("_").length, 5);
});

test("passphrase: --capitalize capitalizes every word", () => {
  const [{ value }] = run(["--mode", "passphrase", "--words", "4", "--capitalize"]);
  for (const word of value.split("-")) {
    assert.match(word[0], /[A-Z]/);
  }
});

test("passphrase: --add-number appends a trailing digit token", () => {
  const [{ value }] = run(["--mode", "passphrase", "--words", "3", "--add-number"]);
  const parts = value.split("-");
  assert.equal(parts.length, 4);
  assert.match(parts.at(-1), /^[0-9]$/);
});

test("passphrase: entropy scales linearly with word count", () => {
  const [{ entropy_bits: bits3 }] = run(["--mode", "passphrase", "--words", "3"]);
  const [{ entropy_bits: bits6 }] = run(["--mode", "passphrase", "--words", "6"]);
  // Each side is independently rounded to 1 decimal, so allow for that.
  assert.ok(Math.abs(bits6 - 2 * bits3) < 0.15);
});
