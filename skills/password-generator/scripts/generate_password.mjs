#!/usr/bin/env node
// Cryptographically secure password / diceware passphrase generator.
//
// All randomness comes from node:crypto's randomInt (a CSPRNG, rejection-
// sampled internally so there's no modulo bias) -- never from the model
// typing out characters itself. Character-class coverage is enforced by
// rejection sampling on the whole candidate string, not by force-inserting
// a character afterward, so the output stays uniformly random over the
// constrained space instead of losing entropy to a biased construction.

import { randomInt } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { spawnSync } from "node:child_process";

const LOWER = "abcdefghijklmnopqrstuvwxyz";
const UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const DIGITS = "0123456789";
const SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/~";
const AMBIGUOUS = new Set([..."O0Il1|`'\""]);

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_WORDLIST = path.join(__dirname, "..", "references", "eff_large_wordlist.txt");

function fail(msg) {
  console.error(msg);
  process.exit(1);
}

function choice(str) {
  return str[randomInt(0, str.length)];
}

// Tries platform clipboard tools in order; returns true on the first that
// accepts the text. All our generated values are pure ASCII, so no
// encoding/codepage concerns across clip/pbcopy/xclip/wl-copy/xsel.
function copyToClipboard(text) {
  const candidates =
    process.platform === "win32"
      ? [["clip", []]]
      : process.platform === "darwin"
        ? [["pbcopy", []]]
        : [
            ["xclip", ["-selection", "clipboard"]],
            ["wl-copy", []],
            ["xsel", ["--clipboard", "--input"]],
          ];
  for (const [cmd, cmdArgs] of candidates) {
    const result = spawnSync(cmd, cmdArgs, { input: text, encoding: "utf-8" });
    if (!result.error && result.status === 0) return true;
  }
  return false;
}

function parseArgs(argv) {
  const args = {
    mode: "password",
    length: 20,
    count: 1,
    noUpper: false,
    noLower: false,
    noDigits: false,
    noSymbols: false,
    noAmbiguous: false,
    words: 6,
    separator: "-",
    capitalize: false,
    addNumber: false,
    wordlist: DEFAULT_WORDLIST,
    clipboard: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case "--mode": args.mode = next(); break;
      case "--length": args.length = parseInt(next(), 10); break;
      case "--count": args.count = parseInt(next(), 10); break;
      case "--no-upper": args.noUpper = true; break;
      case "--no-lower": args.noLower = true; break;
      case "--no-digits": args.noDigits = true; break;
      case "--no-symbols": args.noSymbols = true; break;
      case "--no-ambiguous": args.noAmbiguous = true; break;
      case "--words": args.words = parseInt(next(), 10); break;
      case "--separator": args.separator = next(); break;
      case "--capitalize": args.capitalize = true; break;
      case "--add-number": args.addNumber = true; break;
      case "--wordlist": args.wordlist = next(); break;
      case "--clipboard": args.clipboard = true; break;
      default: fail(`Unknown argument: ${a}`);
    }
  }
  return args;
}

function buildCharset(useLower, useUpper, useDigits, useSymbols, noAmbiguous) {
  const classes = [];
  if (useLower) classes.push(LOWER);
  if (useUpper) classes.push(UPPER);
  if (useDigits) classes.push(DIGITS);
  if (useSymbols) classes.push(SYMBOLS);
  if (classes.length === 0) fail("At least one character class must be enabled.");
  let out = classes;
  if (noAmbiguous) {
    out = classes.map((cls) => [...cls].filter((c) => !AMBIGUOUS.has(c)).join(""));
    if (out.some((cls) => cls.length === 0)) {
      fail("--no-ambiguous removed an entire character class; disable that class instead.");
    }
  }
  return out;
}

function genPassword(length, classes, maxAttempts = 10000) {
  const alphabet = classes.join("");
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    let candidate = "";
    for (let i = 0; i < length; i++) candidate += choice(alphabet);
    if (classes.every((cls) => [...candidate].some((c) => cls.includes(c)))) {
      return candidate;
    }
  }
  fail("Could not satisfy character-class coverage; increase length or reduce required classes.");
}

function entropyBits(length, alphabetSize) {
  return length * Math.log2(alphabetSize);
}

function loadWordlist(p) {
  const words = readFileSync(p, "utf-8").split("\n").map((w) => w.trim()).filter(Boolean);
  if (words.length < 2) fail(`Wordlist at ${p} looks empty or malformed.`);
  return words;
}

function genPassphrase(wordCount, wordlist, separator, capitalize, addNumber) {
  let words = Array.from({ length: wordCount }, () => wordlist[randomInt(0, wordlist.length)]);
  if (capitalize) words = words.map((w) => w[0].toUpperCase() + w.slice(1));
  let bits = wordCount * Math.log2(wordlist.length);
  if (addNumber) {
    const digit = choice(DIGITS);
    words.push(digit);
    bits += Math.log2(10);
  }
  return [words.join(separator), bits];
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.count < 1) fail("--count must be >= 1");
  if (args.clipboard && args.count !== 1) {
    fail("--clipboard only makes sense with --count 1 (it can hold one value); drop --clipboard or set --count 1.");
  }

  const results = [];
  if (args.mode === "password") {
    const classes = buildCharset(!args.noLower, !args.noUpper, !args.noDigits, !args.noSymbols, args.noAmbiguous);
    if (args.length < classes.length) {
      fail(`--length must be >= number of required character classes (${classes.length})`);
    }
    const alphabetSize = new Set(classes.join("")).size;
    for (let i = 0; i < args.count; i++) {
      const pw = genPassword(args.length, classes);
      results.push({ value: pw, entropy_bits: Math.round(entropyBits(args.length, alphabetSize) * 10) / 10 });
    }
  } else if (args.mode === "passphrase") {
    if (args.words < 1) fail("--words must be >= 1");
    const wordlist = loadWordlist(args.wordlist);
    for (let i = 0; i < args.count; i++) {
      const [phrase, bits] = genPassphrase(args.words, wordlist, args.separator, args.capitalize, args.addNumber);
      results.push({ value: phrase, entropy_bits: Math.round(bits * 10) / 10 });
    }
  } else {
    fail(`Unknown --mode: ${args.mode}`);
  }

  if (args.clipboard) {
    const copied = copyToClipboard(results[0].value);
    if (copied) {
      results[0].value = "(copied to clipboard -- not printed)";
      results[0].clipboard = true;
    } else {
      results[0].clipboard = false;
      console.error("Clipboard copy failed (no clip/pbcopy/xclip/wl-copy/xsel found) -- printing value instead.");
    }
  }

  console.log(JSON.stringify(results, null, 2));
}

main();
