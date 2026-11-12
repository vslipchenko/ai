# password-generator

*Generate passwords and passphrases that are actually random.*

Ask for a password or passphrase and it's produced by a real CSPRNG
(Python's `secrets` module or Node's `crypto.randomInt`), never by the model
typing out a "random-looking" string — LLM output is not a source of
entropy, so that would not be a secure password no matter how it looks.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Pick one of the options below, then restart Claude Code (or
reload skills).

### Safe install (recommended)

With the [`safe-install`](../safe-install) skill installed, run:

```text
/safe-install https://github.com/vslipchenko/ai/tree/main/skills/password-generator
```

It scans the skill (fixed rules, Claude Code's manifest validator and an
isolated AI review) before installing it, and blocks the install on any
critical issue.

### Manual install

Clone the repo and put the folder where Claude Code looks for skills:

```bash
git clone https://github.com/vslipchenko/ai.git
cd ai

# personal (available in every project)
cp -r skills/password-generator ~/.claude/skills/password-generator

# or project-local (this project only)
cp -r skills/password-generator /path/to/project/.claude/skills/password-generator
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)

### Quick install via your AI agent (unchecked)

Paste this into Claude Code (or another AI agent):

```text
Install this skill https://github.com/vslipchenko/ai/tree/main/skills/password-generator
```

> [!WARNING]
> Nothing is checked. The agent reads the skill's files in a session that has
> your permissions, so a tampered file could give it instructions while it
> installs. Use [safe install](#safe-install-recommended) if you want a check.

## Modes

| Mode | Produces | Good for |
|---|---|---|
| `password` | random characters (lower/upper/digits/symbols, configurable) | sites/systems with fixed complexity rules |
| `passphrase` | N diceware words from the bundled 7,776-word EFF large wordlist | memorable secrets, master passwords |

## Example

> **You:** Generate a strong password for a new admin account, no symbols
> allowed, 16 characters.
>
> **Claude:** Generated and copied to your clipboard (not shown here) — 16
> characters, letters + digits, ~85 bits of entropy. Paste it into your
> password manager now.

> **You:** Actually just show me this one, I need to type it into a form
> that won't take a paste.
>
> **Claude:**
> ```
> Qx7bNfmZ4hRkT2Lp
> ```

> **You:** And give me a memorable one too — a passphrase, and I do want to
> see it.
>
> **Claude:**
> ```
> Wobble-Kitchen-Doctrine-Amethyst-Culture-Rerun
> ```
> ~77 bits of entropy (6 words from a 7,776-word list).

## Keeping it out of your terminal history

By default, when generating a single value, the skill copies it straight to
your OS clipboard (`clip` / `pbcopy` / `xclip` / `wl-copy` / `xsel`,
depending on platform) instead of printing it — so it never lands in your
terminal scrollback or the chat transcript in the first place. You'll see
something like:

> Generated and copied to your clipboard (not shown here) — 20 characters,
> ~130 bits of entropy.

Ask to "just show it" (or generate more than one at once) to get the
plaintext printed instead.

If it does get printed and you want it out of your terminal, clear your
shell's scrollback (`clear` / `cls` / `Clear-Host`) — **`/clear` is a
different thing**: it only resets Claude's own conversation context, it
does not touch terminal scrollback and can't be triggered on your behalf,
so it's a secondary step at best, not a substitute for not printing the
secret in the first place.

## How it works

1. **Mode and parameters are resolved** from your request — length or word
   count, character classes, separators — falling back to sane, stated
   defaults (20-character password with all classes, or a 6-word passphrase)
   when you don't specify.
2. **The bundled script does the actual generation**, trying `python3` →
   `python` → `py -3` → `node` in order. Character-class coverage (e.g. "must
   contain a digit") is enforced by *rejecting and re-rolling* whole
   candidates that don't qualify, not by force-inserting a character
   afterward — the latter is a common mistake that quietly reduces entropy
   below what the character-set math implies.
3. **Entropy is reported in bits** alongside the value
   (`length * log2(alphabet size)` for passwords, `words * log2(7776)` for
   passphrases), so you can judge whether it's strong enough for the use
   case rather than trusting a gut feeling about a jumble of characters.
4. If no Python or Node runtime is available, it says so and stops — there is
   no "manual fallback" for randomness, unlike a pure encoding task.

## Requirements

[Python 3](https://www.python.org/downloads/) or [Node.js](https://nodejs.org/en/download) (no third-party packages either way — both use only
their standard library's CSPRNG).

## License

MIT (repo default — see the root [README](../../README.md)), except
`references/eff_large_wordlist.txt`, which is the [EFF long
wordlist](https://www.eff.org/dice) (CC BY 3.0 US, © Electronic Frontier
Foundation).
