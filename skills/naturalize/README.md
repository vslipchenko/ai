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
   sample (an email, a doc excerpt). No samples handy for one? You can
   either write a few substitute sentences spanning past/present/future
   tense, or skip it entirely — in which case that register runs in
   **generic mode**: you still get the AI-tell checklist applied (em-dash,
   stock phrases, rare synonyms, ...), just without matching to your
   specific voice, since nothing was learned about it. Every rewrite in
   generic mode says so, and you can add a sample later to personalize it.
3. Toggle a checklist of AI writing tells — vocabulary, symbols, sentence
   structure, stock openers/closers, formatting, hedging, and an optional
   (off by default) light-typo mode for informal writing.
4. Add any custom instructions in plain language.
5. Choose whether you want a before/after preview each time, or just the
   final rewrite.

Your answers are synthesized into a profile and shown back to you in plain
language before anything is saved.

## Bypassing your profile for one request

By default every rewrite uses your saved profile. If you'd rather get a
plain de-AI-ify pass without your voice applied — say for text you want
scrubbed of AI tells but not made to sound like *you* specifically — just
ask: "naturalize this generically," "without my profile," "ignore my
profile for this one." That request skips your profile file entirely (it's
not even read), uses the checklist's stated defaults, and the reply says
plainly that it ran generically. It's a one-off — your saved profile is
untouched, and the next normal request goes back to using it.

## Example

> **You:** Naturalize this: "I'd be happy to help! Please let me know if
> you have any questions — I hope this helps you move forward seamlessly."
>
> **Claude:** *(after first-run calibration, informal register)*
> "Sure, let me know if anything's unclear."

> **You:** Turn off the typo thing, I don't want that.
>
> **Claude:** Done — typos are off in your profile.

> **You:** *(during calibration, formal register)* I don't have a formal
> sample and don't feel like writing one.
>
> **Claude:** No problem — I'll run your formal register in generic mode:
> the AI-tell checklist still applies, but I won't be matching it to your
> specific voice since I have nothing to learn it from. You can add a
> sample any time to personalize it. *(later, on a formal rewrite)*
> "Attached is the report." *(generic de-AI-ify pass — no voice sample on
> file for this register; add one anytime to personalize.)*

> **You:** Naturalize this generically, don't use my profile: "I would be
> delighted to assist you with this endeavor."
>
> **Claude:** "Happy to help with this." *(generic pass, per your request
> — your profile wasn't consulted.)*

## How it works

1. **Request mode is determined first.** Normally that's `profile` mode —
   your saved profile governs the rewrite. Asking for a generic pass
   switches to a one-off `explicit_generic` mode for that request only:
   your profile file isn't read (or written) at all, and the checklist's
   stated defaults are used instead.
2. **A profile is loaded** from `~/.naturalize/profile.md` (your home
   directory, not this repo) if one exists and `profile` mode is active;
   otherwise calibration runs first.
3. **Register is resolved** for each request — explicit ("as an email")
   wins, then it's inferred from context, then it falls back to your
   default voice (or, in `explicit_generic` mode, to informal, since
   there's no profile default to fall back to).
4. **The text is rewritten** using the effective rules for that mode:
   common words over rare synonyms, ASCII-typeable symbols over Unicode
   lookalikes (em-dash → hyphen, `→` → `->`, curly quotes → straight
   quotes, ...), stock AI phrasing and structure stripped per the active
   toggles, optional light typos in informal writing only. `profile` mode
   uses your saved toggles/custom instructions; `explicit_generic` mode
   (and any register with no sample on file) uses the checklist's stated
   defaults instead — no attempt is made to match your personal voice, and
   the delivery says so.
5. **Protected content is never touched** — code, quotations/citations,
   URLs, numbers, proper nouns, and your field's actual jargon are left
   exactly as they are, regardless of which toggles are on.
6. **You can recalibrate at any time**, in full or partially — add a
   sample, flip one toggle, edit your custom instructions — without
   redoing the whole setup.

## Requirements

None beyond Claude Code itself — this skill is pure instructions/
reference material, no bundled script or runtime dependency.

## License

MIT (repo default — see the root [README](../../README.md)).
</content>
