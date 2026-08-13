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
- **delivery**: clipboard by default when `count` is 1 — see Step 3. Print
  instead when the user asks to see/type it, when `count` > 1, or when
  they're clearly on a remote/headless session (SSH, container, CI) where a
  local clipboard tool won't exist anyway.

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
--clipboard                  copy the value to the OS clipboard instead of printing it (count must be 1)
```

The script prints a JSON array of `{"value": ..., "entropy_bits": ...}`. When
`--clipboard` succeeds, `value` comes back redacted
(`"(copied to clipboard -- not printed)"`) and the object carries
`"clipboard": true` — the real value never reaches stdout, so it never lands
in your terminal scrollback or this chat transcript. `generate_password.mjs`
tries `clip`/`pbcopy`/`xclip`/`wl-copy`/`xsel` depending on platform; if none
is found, the script falls back to printing the value and sets
`"clipboard": false`.

## Step 3 — Deliver the result

**Default (count 1): use `--clipboard`.** This is the main fix for the
password lingering in the terminal — nothing sensitive is ever printed in
the first place, so there's nothing in scrollback or chat history to clean up
afterward. Tell the user plainly what happened:

> Generated and copied to your clipboard (not shown here) — 20 characters,
> ~130 bits of entropy. Paste it into your password manager now; the
> clipboard will still hold it until you copy something else.

If the script reports `"clipboard": false` (no clipboard tool on the
system), or the user asked to see/type it, or `--count` > 1: print the
value(s) in a code block (so nothing gets auto-formatted or mangled) with
the entropy in bits. A one-line rule of thumb, only if useful context: ~60
bits is adequate for most accounts behind reasonable lockout/rate-limiting,
~80+ bits for high-value secrets (master passwords, signing keys). Don't
over-explain unless asked.

If `--count` > 1, present all of them and let the user pick — don't just use
the first one for anything.

## Step 4 — If the value did get printed, reduce residual exposure

Be honest about what actually helps here — don't oversell `/clear`:

- **`/clear` is a REPL command only the user can run — there is no tool call
  that invokes it on their behalf, and it wouldn't fully solve this even if
  there were.** It removes the conversation from the model's *future*
  context; it does **not** erase the terminal's scrollback buffer (the
  printed value is still visible by scrolling up) and does not retroactively
  scrub any transcript/log already persisted by the surrounding tool.
- What actually removes it from the visible terminal: the user clearing
  their own scrollback (`clear` on macOS/Linux, `cls` in cmd.exe,
  `Clear-Host` in PowerShell) — suggest the exact command for their shell if
  known, otherwise mention both.
- If they also want it out of the Claude session's context going forward,
  *then* suggest `/clear` — framed as an added layer, not the fix, and
  something they run themselves.
- Prefer steering to `--clipboard` on the *next* generation instead of
  trying to clean up after the fact — cleanup is best-effort, not printing
  it is reliable.

## Step 5 — Handling the secret afterward

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
- `--clipboard` combined with `--count` > 1 → script refuses (a clipboard
  holds one value); generate one at a time instead.
- Clipboard tool not found → script falls back to printing with
  `"clipboard": false`; treat it like the no-`--clipboard` path (Step 3) and
  optionally mention *why* it printed (no `clip`/`pbcopy`/`xclip`/`wl-copy`/
  `xsel` found).
- No Python or Node runtime available → tell the user directly; do not
  generate a password by any other means.
