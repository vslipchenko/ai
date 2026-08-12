---
name: password-generator
description: Generate cryptographically secure passwords or diceware-style passphrases via a bundled CSPRNG script — never by having the model type out a "random-looking" string. Use when the user asks to generate/create a password, passphrase, secret, PIN, or random token, or to check the strength of one.
---

# Password Generator

Produce passwords and passphrases whose randomness actually comes from a
cryptographically secure random number generator, not from the model.

**Why a script and not just "think of a random string": an LLM's output is
not a source of entropy** — sampled tokens are statistically biased and, given
the conversation, effectively predictable. A "random-looking" string typed by
the model is not a secure password no matter how random it looks. This skill
always shells out to `scripts/generate_password.{py,mjs}`, which use a real
CSPRNG (Python's `secrets` module / Node's `crypto.randomInt`), for every
character or word chosen.

`<SKILL_DIR>` below is this skill's own announced base directory (the path
shown when this skill loads, ending in `.../skills/password-generator`).

## Step 1 — Resolve mode and parameters

Two modes:

| Mode | What it produces | Good for |
|---|---|---|
| `password` | random characters from chosen classes (lower/upper/digits/symbols) | sites/systems with fixed complexity rules |
| `passphrase` | N words from the bundled 7,776-word EFF diceware list | memorable, typed-by-hand secrets, master passwords |

Default to `password` unless the user says "passphrase," "memorable," "words,"
or similar, or the target system disallows symbols (in which case a
passphrase is often the better fit than a stripped-down password).

Ask only if genuinely ambiguous; otherwise use sane defaults and mention them
in the result so the user can redirect:

- **password**: length 20, all four classes on, ambiguous characters
  included. If the user mentions a site's specific rules ("no symbols
  allowed", "must be 12-16 characters", "no ambiguous characters"), map those
  directly to `--length`/`--no-*`/`--no-ambiguous` instead of asking.
- **passphrase**: 6 words, `-` separator, no capitalization, no trailing
  number, unless the user asks for those.
- **count**: 1, unless the user asks for multiple (e.g. "give me a few
  options").

## Step 2 — Run the script

Never hand-generate the value yourself. Try runtimes in order, first one that
works:

1. `python3 "<SKILL_DIR>/scripts/generate_password.py" [args]`
2. else `python "<SKILL_DIR>/scripts/generate_password.py" [args]`
3. else `py -3 "<SKILL_DIR>/scripts/generate_password.py" [args]`
4. else `node "<SKILL_DIR>/scripts/generate_password.mjs" [args]`

If none of these runtimes are available, say so plainly and stop — **do not**
fall back to typing out a password yourself. There is no safe manual fallback
here, unlike a pure encoding task.

Common flags (identical between the `.py` and `.mjs` versions):

```
--mode password|passphrase   (default: password)
--length N                   password mode, default 20
--count N                    how many to generate, default 1
--no-upper / --no-lower / --no-digits / --no-symbols
--no-ambiguous                drop visually-confusable chars: 0/O, 1/l/I, quotes, backtick
--words N                    passphrase mode, default 6
--separator STR              passphrase mode, default "-"
--capitalize                 passphrase mode: capitalize each word
--add-number                 passphrase mode: append one random digit
```

The script prints a JSON array of `{"value": ..., "entropy_bits": ...}`.

## Step 3 — Present the result

Show the generated value(s) in a code block (so nothing gets auto-formatted
or mangled) plus the reported entropy in bits. A one-line rule of thumb, only
if useful context: ~60 bits is adequate for most accounts behind reasonable
lockout/rate-limiting, ~80+ bits for high-value secrets (master passwords,
signing keys). Don't over-explain unless asked.

If `--count` > 1, present all of them and let the user pick — don't just use
the first one for anything.

## Step 4 — Handling the secret afterward

- Don't write the generated password to any file, log, or persistent memory
  unless the user explicitly asks you to save it somewhere.
- If the user asks where to put it, a password manager is the right answer —
  don't suggest storing it in plaintext in the repo, a config file, or chat
  history as a substitute.
- If asked to check the strength of a password the user already has (rather
  than generate one), estimate entropy from its actual character-class
  composition and length using the same `entropy_bits` formula
  (`length * log2(alphabet_size)`) — don't just eyeball it.

## Error handling

- `--length` shorter than the number of enabled character classes → the
  script exits with a clear message; relay it and ask whether to shorten the
  requirement list or lengthen the password, don't silently drop a class.
- `--no-ambiguous` would empty an entire enabled class → script refuses;
  relay the message.
- No Python or Node runtime available → tell the user directly; do not
  generate a password by any other means.
