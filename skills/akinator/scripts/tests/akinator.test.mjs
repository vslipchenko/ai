import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SECRET = path.join(__dirname, "..", "secret.mjs");
const BOARD = path.join(__dirname, "..", "leaderboard.mjs");
const LISTS = path.join(__dirname, "..", "..", "references", "secrets");

function withHome(fn) {
  const home = mkdtempSync(path.join(tmpdir(), "akinator-"));
  try {
    return fn(home, (script, args) =>
      JSON.parse(execFileSync("node", [script, ...args], {
        encoding: "utf-8",
        env: { ...process.env, AKINATOR_HOME: home },
        stdio: ["ignore", "pipe", "pipe"],
      })));
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
}

function bundledAnimals() {
  return readFileSync(path.join(LISTS, "animals.txt"), "utf-8").split(/\r?\n/).filter(Boolean);
}

function record(run, extra) {
  const base = { mode: "claude-guesses", limit: "25", secret: "x", domain: "animal", date: "2026-09-25" };
  const flags = Object.entries({ ...base, ...extra }).flatMap(([k, v]) => [`--${k}`, String(v)]);
  return run(BOARD, ["record", ...flags]);
}

test("secret: commit prints the hash but not the secret", () => {
  withHome((home, run) => {
    const out = run(SECRET, ["commit", "--domain", "animal"]);
    const state = JSON.parse(readFileSync(path.join(home, "secret.json"), "utf-8"));
    assert.equal(out.hash, state.hash);
    assert.ok(!JSON.stringify(out).includes(state.secret));
    assert.ok(bundledAnimals().includes(state.secret));
  });
});

test("secret: reveal verifies the salted commitment and clears state", () => {
  withHome((home, run) => {
    const { hash } = run(SECRET, ["commit", "--domain", "character"]);
    const out = run(SECRET, ["reveal"]);
    assert.equal(out.hash, hash);
    assert.equal(out.verified, true);
    assert.equal(createHash("sha256").update(out.preimage).digest("hex"), hash);
    assert.equal(out.preimage, `${out.salt}:${out.secret}`);
    assert.ok(!existsSync(path.join(home, "secret.json")));
    const recent = JSON.parse(readFileSync(path.join(home, "recent.json"), "utf-8"));
    assert.deepEqual(recent.character, [out.secret]);
  });
});

test("secret: same secret commits to different hashes (salted)", () => {
  withHome((home, run) => {
    const hashes = new Set();
    for (let i = 0; i < 5; i++) {
      hashes.add(run(SECRET, ["commit", "--domain", "object"]).hash);
    }
    assert.equal(hashes.size, 5);
  });
});

test("secret: recently revealed secrets are not picked again", () => {
  withHome((home, run) => {
    const seen = [];
    for (let i = 0; i < 10; i++) {
      run(SECRET, ["commit", "--domain", "animal"]);
      seen.push(run(SECRET, ["reveal"]).secret);
    }
    assert.equal(new Set(seen).size, 10);
  });
});

test("secret: user extension list is merged, deduplicated, comments skipped", () => {
  withHome((home, run) => {
    mkdirSync(path.join(home, "secrets"));
    writeFileSync(path.join(home, "secrets", "animals.txt"), "# my animals\ntest-only-creature\n\nDOG\ntest-only-creature\n");
    const out = run(SECRET, ["commit", "--domain", "animal"]);
    assert.equal(out.custom_entries, 1);
    assert.equal(out.pool_size, bundledAnimals().length + 1);
  });
});

test("secret: extension entries can be picked", () => {
  withHome((home, run) => {
    mkdirSync(path.join(home, "secrets"));
    writeFileSync(path.join(home, "secrets", "animals.txt"), "test-only-creature\n");
    writeFileSync(path.join(home, "recent.json"), JSON.stringify({ animal: bundledAnimals() }));
    run(SECRET, ["commit", "--domain", "animal"]);
    assert.equal(run(SECRET, ["reveal"]).secret, "test-only-creature");
  });
});

test("secret: reveal without commit fails; bad domain fails", () => {
  withHome((home, run) => {
    assert.throws(() => run(SECRET, ["reveal"]));
    assert.throws(() => run(SECRET, ["commit", "--domain", "planet"]));
  });
});

test("leaderboard: first run is both best and worst", () => {
  withHome((home, run) => {
    const out = record(run, { questions: 12, outcome: "guessed" });
    assert.equal(out.board, "claude-guesses/25");
    assert.equal(out.new_best, true);
    assert.equal(out.new_worst, true);
    assert.equal(out.best.questions, 12);
  });
});

test("leaderboard: claude-guesses ranks stumps above wins, then more questions", () => {
  withHome((home, run) => {
    record(run, { questions: 12, outcome: "guessed" });
    let out = record(run, { questions: 20, outcome: "guessed" });
    assert.equal(out.new_best, true);
    out = record(run, { questions: 5, outcome: "guessed" });
    assert.equal(out.new_worst, true);
    out = record(run, { questions: 8, outcome: "not-guessed" });
    assert.equal(out.new_best, true);
    assert.equal(out.best.outcome, "not-guessed");
    assert.equal(out.worst.questions, 5);
  });
});

test("leaderboard: user-guesses ranks wins by fewer questions, losses below wins", () => {
  withHome((home, run) => {
    const mode = "user-guesses";
    record(run, { mode, questions: 15, outcome: "guessed" });
    let out = record(run, { mode, questions: 9, outcome: "guessed" });
    assert.equal(out.new_best, true);
    out = record(run, { mode, questions: 3, outcome: "not-guessed" });
    assert.equal(out.new_worst, true);
    out = record(run, { mode, questions: 10, outcome: "not-guessed" });
    assert.equal(out.new_worst, false);
    assert.equal(out.best.questions, 9);
    assert.equal(out.worst.questions, 3);
  });
});

test("leaderboard: ties keep the earlier run", () => {
  withHome((home, run) => {
    record(run, { secret: "first", questions: 10, outcome: "guessed" });
    const out = record(run, { secret: "second", questions: 10, outcome: "guessed" });
    assert.equal(out.new_best, false);
    assert.equal(out.new_worst, false);
    assert.equal(out.best.secret, "first");
  });
});

test("leaderboard: boards are separate per mode and limit; show filters", () => {
  withHome((home, run) => {
    record(run, { limit: "20", questions: 10, outcome: "guessed" });
    record(run, { limit: "none", questions: 40, outcome: "guessed", note: "2 answers didn't fit" });
    record(run, { mode: "user-guesses", questions: 7, outcome: "guessed" });
    assert.deepEqual(Object.keys(run(BOARD, ["show"])).sort(),
      ["claude-guesses/20", "claude-guesses/none", "user-guesses/25"]);
    const none = run(BOARD, ["show", "--limit", "none"]);
    assert.equal(none["claude-guesses/none"].best.note, "2 answers didn't fit");
    assert.deepEqual(Object.keys(run(BOARD, ["show", "--mode", "user-guesses"])), ["user-guesses/25"]);
  });
});

test("leaderboard: rejects question counts outside the limit", () => {
  withHome((home, run) => {
    assert.throws(() => record(run, { limit: "20", questions: 21, outcome: "guessed" }));
    assert.throws(() => record(run, { questions: 0, outcome: "guessed" }));
    assert.throws(() => record(run, { questions: 5, outcome: "won" }));
  });
});
