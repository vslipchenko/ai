// Akinator leaderboard: the best and worst run per (mode, question limit).
//
// Every board is ranked from the user's point of view, so "best" always means
// "the user did well":
//
//   claude-guesses (user thinks, Claude asks)
//       stumping Claude beats any run Claude guessed; within each outcome,
//       more questions is better.
//   user-guesses (Claude thinks, user asks)
//       guessing it beats giving up / running out; guessed runs rank by fewer
//       questions, lost runs by more questions (held out longer).
//
// A new run replaces a stored one only when strictly better (best) or strictly
// worse (worst), so on a tie the earlier run keeps its place.
//
// Usage:
//   leaderboard.mjs record --mode M --limit L --secret S --domain D
//                          --questions N --outcome guessed|not-guessed [--note T]
//   leaderboard.mjs show [--mode M] [--limit L]

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

const MODES = ["claude-guesses", "user-guesses"];
const LIMITS = ["20", "25", "none"];
const DOMAINS = ["character", "animal", "object"];
const OUTCOMES = ["guessed", "not-guessed"];

function fail(message) {
  process.stderr.write(message + "\n");
  process.exit(1);
}

function boardFile() {
  return path.join(process.env.AKINATOR_HOME || path.join(homedir(), ".akinator"), "leaderboard.json");
}

function load() {
  try {
    return JSON.parse(readFileSync(boardFile(), "utf-8"));
  } catch (err) {
    if (err.code === "ENOENT") return { version: 1, boards: {} };
    throw err;
  }
}

function save(data) {
  const file = boardFile();
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

// Higher is better for the user; compared as [primary, secondary] tuples.
function score(mode, entry) {
  const q = entry.questions;
  if (mode === "claude-guesses") return [entry.outcome === "not-guessed" ? 1 : 0, q];
  const guessed = entry.outcome === "guessed";
  return [guessed ? 1 : 0, guessed ? -q : q];
}

function compare(a, b) {
  return a[0] - b[0] || a[1] - b[1];
}

function applyRun(boards, mode, limit, entry) {
  const key = `${mode}/${limit}`;
  const board = (boards[key] ??= {});
  const s = score(mode, entry);
  const newBest = !board.best || compare(s, score(mode, board.best)) > 0;
  const newWorst = !board.worst || compare(s, score(mode, board.worst)) < 0;
  if (newBest) board.best = entry;
  if (newWorst) board.worst = entry;
  return { board: key, new_best: newBest, new_worst: newWorst, ...board };
}

function parseFlags(args, spec) {
  const out = {};
  for (let i = 0; i < args.length; i++) {
    const name = args[i].replace(/^--/, "");
    if (!args[i].startsWith("--") || !(name in spec)) fail(`Unknown argument: ${args[i]}`);
    const value = args[++i];
    if (value === undefined) fail(`--${name} needs a value`);
    const choices = spec[name];
    if (choices && !choices.includes(value)) fail(`--${name} must be one of: ${choices.join(", ")}`);
    out[name] = value;
  }
  return out;
}

function today() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function main(argv) {
  const [command, ...rest] = argv;
  const data = load();
  if (command === "record") {
    const f = parseFlags(rest, {
      mode: MODES, limit: LIMITS, secret: null, domain: DOMAINS,
      questions: null, outcome: OUTCOMES, note: null, date: null,
    });
    for (const req of ["mode", "limit", "secret", "domain", "questions", "outcome"]) {
      if (f[req] === undefined) fail(`--${req} is required`);
    }
    if (!/^-?\d+$/.test(f.questions)) fail("--questions must be an integer.");
    const questions = Number(f.questions);
    if (questions < 1) fail("--questions must be at least 1.");
    if (f.limit !== "none" && questions > Number(f.limit)) {
      fail(`--questions (${questions}) exceeds the ${f.limit}-question limit.`);
    }
    const entry = {
      secret: f.secret,
      domain: f.domain,
      questions,
      outcome: f.outcome,
      date: f.date ?? today(),
    };
    if (f.note) entry.note = f.note;
    const result = applyRun(data.boards, f.mode, f.limit, entry);
    save(data);
    console.log(JSON.stringify(result));
  } else if (command === "show") {
    const f = parseFlags(rest, { mode: MODES, limit: LIMITS });
    const boards = Object.fromEntries(
      Object.entries(data.boards).filter(([key]) => {
        const [mode, limit] = key.split("/");
        return (!f.mode || mode === f.mode) && (!f.limit || limit === f.limit);
      }),
    );
    console.log(JSON.stringify(boards));
  } else {
    fail("Usage: leaderboard.mjs record ... | leaderboard.mjs show [--mode M] [--limit L]");
  }
}

main(process.argv.slice(2));
