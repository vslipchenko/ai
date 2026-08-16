# naturalize

*Make Claude's writing sound like you actually wrote it.*

Rewrites text to match your own personal writing voice instead of the
generic patterns that make AI output recognizable — em-dashes, curly
quotes, "I hope this helps!," rare synonyms, rule-of-three lists, and the
rest. Calibrated once from your own writing samples and a togglable
checklist, then applied automatically on every later request until you ask
to change it.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Put the folder where Claude Code looks for skills:

```bash
# personal (available in every project)
cp -r skills/naturalize ~/.claude/skills/naturalize

# or project-local (this project only)
cp -r skills/naturalize /path/to/project/.claude/skills/naturalize
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)
Restart Claude Code (or reload skills) afterwards.

## First run: calibration

The first time you ask to naturalize something, the skill walks you
through a short setup instead of guessing at your voice:

1. Pick your default register — informal or formal (informal is the
   suggested default).
2. Give a real informal sample (a Slack message, a text) and a real formal
   sample (an email, a doc excerpt). No samples handy? You'll be asked to
   write a few sentences spanning past/present/future tense instead.
3. Toggle a checklist of AI writing tells — vocabulary, symbols, sentence
   structure, stock openers/closers, formatting, hedging, and an optional
   (off by default) light-typo mode for informal writing.
4. Add any custom instructions in plain language.
5. Choose whether you want a before/after preview each time, or just the
   final rewrite.

Your answers are synthesized into a profile and shown back to you in plain
language before anything is saved.

## Example

> **You:** Naturalize this: "I'd be happy to help! Please let me know if
> you have any questions — I hope this helps you move forward seamlessly."
>
> **Claude:** *(after first-run calibration, informal register)*
> "Sure, let me know if anything's unclear."

> **You:** Turn off the typo thing, I don't want that.
>
> **Claude:** Done — typos are off in your profile.

## How it works

1. **A profile is loaded** from `~/.naturalize/profile.md` (your home
   directory, not this repo) if one exists; otherwise calibration runs
   first.
2. **Register is resolved** for each request — explicit ("as an email")
   wins, then it's inferred from context, then it falls back to your
   default voice.
3. **The text is rewritten** against the profile's rules: common words
   over rare synonyms, ASCII-typeable symbols over Unicode lookalikes
   (em-dash → hyphen, `→` → `->`, curly quotes → straight quotes, ...),
   stock AI phrasing and structure stripped per your toggles, optional
   light typos in informal writing only.
4. **Protected content is never touched** — code, quotations/citations,
   URLs, numbers, proper nouns, and your field's actual jargon are left
   exactly as they are, regardless of which toggles are on.
5. **You can recalibrate at any time**, in full or partially — add a
   sample, flip one toggle, edit your custom instructions — without
   redoing the whole setup.

## Requirements

None beyond Claude Code itself — this skill is pure instructions/
reference material, no bundled script or runtime dependency.

## License

MIT (repo default — see the root [README](../../README.md)).
</content>
