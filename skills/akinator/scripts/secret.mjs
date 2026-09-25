// Pick, commit to, and reveal the secret for Akinator's reverse mode.
//
// The model has no hidden memory: if it just "thinks of" a secret, it can
// quietly drift to a different one mid-game. So the secret is picked here with
// a CSPRNG from the bundled per-domain lists (which also avoids the model
// picking the same few favourites every time) plus the user's own extension
// lists in <state dir>/secrets/, written to a state file, and
// only a salted SHA-256 commitment is printed. `reveal` prints the secret and
// salt so the user can recompute the hash and confirm the secret never changed.
// The salt matters: without it the hash of every list entry could be
// precomputed and the commitment would give the answer away.
//
// Usage:
//   secret.mjs commit --domain character|animal|object
//   secret.mjs reveal

import { createHash, randomBytes, randomInt } from "node:crypto";
import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DOMAINS = { character: "characters.txt", animal: "animals.txt", object: "objects.txt" };
const LISTS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "references", "secrets");
const RECENT_LIMIT = 10;

function fail(message) {
  process.stderr.write(message + "\n");
  process.exit(1);
}

function stateDir() {
  return process.env.AKINATOR_HOME || path.join(homedir(), ".akinator");
}

// Non-empty, non-comment lines of a list file; [] if it doesn't exist.
function readEntries(file) {
  let text;
  try {
    text = readFileSync(file, "utf-8");
  } catch (err) {
    if (err.code === "ENOENT") return [];
    throw err;
  }
  return text
    .replace(/^﻿/, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
}

// Bundled list merged with the user's extension list, deduplicated
// case-insensitively (first spelling wins).
function loadList(domain) {
  const words = [];
  const seen = new Set();
  let custom = 0;
  const sources = [[LISTS_DIR, false], [path.join(stateDir(), "secrets"), true]];
  for (const [dir, isCustom] of sources) {
    for (const word of readEntries(path.join(dir, DOMAINS[domain]))) {
      const key = word.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      words.push(word);
      if (isCustom) custom++;
    }
  }
  return { words, custom };
}

function commitment(salt, secret) {
  return createHash("sha256").update(`${salt}:${secret}`, "utf-8").digest("hex");
}

function readJson(file, fallback) {
  try {
    return JSON.parse(readFileSync(file, "utf-8"));
  } catch (err) {
    if (err.code === "ENOENT") return fallback;
    throw err;
  }
}

function writeJson(file, data) {
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf-8");
}

function pick(domain, recent) {
  const { words, custom } = loadList(domain);
  let fresh = words.filter((w) => !recent.includes(w));
  if (fresh.length === 0) fresh = words;
  return { secret: fresh[randomInt(fresh.length)], pool: words.length, custom };
}

function cmdCommit(domain) {
  const base = stateDir();
  const recent = readJson(path.join(base, "recent.json"), {});
  const { secret, pool, custom } = pick(domain, recent[domain] || []);
  const salt = randomBytes(16).toString("hex");
  const hash = commitment(salt, secret);
  const secretFile = path.join(base, "secret.json");
  writeJson(secretFile, {
    domain,
    secret,
    salt,
    hash,
    created: new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00"),
  });
  // The secret itself is deliberately NOT printed.
  console.log(JSON.stringify({ domain, hash, secret_file: secretFile, pool_size: pool, custom_entries: custom }));
}

function cmdReveal() {
  const base = stateDir();
  const secretFile = path.join(base, "secret.json");
  const state = readJson(secretFile, null);
  if (state === null) fail("No committed secret found; start a game with `commit` first.");
  const verified = commitment(state.salt, state.secret) === state.hash;
  const recentFile = path.join(base, "recent.json");
  const recent = readJson(recentFile, {});
  const history = (recent[state.domain] || []).filter((w) => w !== state.secret);
  recent[state.domain] = [...history, state.secret].slice(-RECENT_LIMIT);
  writeJson(recentFile, recent);
  unlinkSync(secretFile);
  console.log(JSON.stringify({
    domain: state.domain,
    secret: state.secret,
    salt: state.salt,
    hash: state.hash,
    verified,
    preimage: `${state.salt}:${state.secret}`,
  }));
}

function main(argv) {
  const [command, ...rest] = argv;
  if (command === "commit") {
    const i = rest.indexOf("--domain");
    const domain = i >= 0 ? rest[i + 1] : undefined;
    if (!Object.hasOwn(DOMAINS, domain)) {
      fail(`--domain is required and must be one of: ${Object.keys(DOMAINS).sort().join(", ")}`);
    }
    cmdCommit(domain);
  } else if (command === "reveal") {
    cmdReveal();
  } else {
    fail("Usage: secret.mjs commit --domain character|animal|object | secret.mjs reveal");
  }
}

main(process.argv.slice(2));
