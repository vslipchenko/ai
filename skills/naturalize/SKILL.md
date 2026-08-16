---
name: naturalize
description: Rewrite Claude-generated text so it matches the user's own personal writing voice, calibrated once via writing samples and a togglable checklist, then reused automatically on every later request. Use when the user asks to "naturalize" text, make it "sound like me" / "less like AI", "humanize" a draft, strip AI writing tells (em-dashes, curly quotes, stock phrases like "I hope this helps"), or asks to (re)calibrate their writing-voice profile.
---

# Naturalize

Rewrite text so it reads like the user actually wrote it, not like an LLM
drafted it — grounded in a profile calibrated once from the user's own
writing (not guessed from a generic "sound more human" instruction), then
reused silently on every later request until the user asks to change it.

`<SKILL_DIR>` below is this skill's own announced base directory (the path
shown when this skill loads, ending in `.../skills/naturalize`) —
references live at `<SKILL_DIR>/references/`.

## Step 1 — Check for an existing profile

Look for a profile at `~/.naturalize/profile.md` (the user's home
directory — same external-storage pattern the `estimator` plugin uses for
`~/.estimator`, keeping personal writing samples out of the skill package
itself).

- **Found** → read it and skip straight to Step 4.
- **Not found** → run Step 2 (first-run calibration).

Never re-run calibration just because the skill was invoked again. Only an
explicit ask ("recalibrate," "redo my profile," "start over") re-triggers
full calibration; smaller asks ("turn off typos," "update my formal
sample") go through Step 3 instead.

## Step 2 — First-run calibration

Run this once, in order. The full toggle catalogue lives in
`references/checklist.md` — load it before Step 2c rather than
reconstructing it from memory. The saved-file structure lives in
`references/profile-template.md` — load it before Step 2g.

**2a. Default voice.** `AskUserQuestion`: Informal or Formal, with
Informal as the recommended option. This becomes `default_voice`, used in
Step 4 whenever a request's register can't be resolved any other way.

**2b. Phase 1 — writing samples.** Ask for a real informal sample (e.g. a
Slack message or text) and a real formal sample (e.g. an email or doc
excerpt). For whichever one the user can't supply, ask them instead to
write a few sentences that span past, present, and future tense — enough
to observe sentence structure and habits even without a real artifact.

**2c. Phase 2 — togglable checklist.** Present `references/checklist.md`'s
groups via `AskUserQuestion` (multiSelect per group): symbols, vocabulary,
structure, openers/closers, formatting, hedging/tone, and typos. State the
protected-content carve-out (code, quotations/citations, URLs, numbers,
proper nouns, domain jargon are never touched) once, up front — don't
repeat it per toggle. Typos default off; everything else defaults on.

**2d. Custom instructions.** Ask if there's anything else to add as free
text (e.g. "always use British spelling," "never start a sentence with
'So'"). Persists by default; can be overridden for a single later request
without changing the saved profile.

**2e. Preview toggle.** Ask whether the user wants a before/after preview
shown each time text is naturalized, or just the rewritten result.
Store as `Preview: enabled`.

**2f. Synthesize and confirm.** Turn each register's sample into a short
characteristic summary — sentence rhythm, formality markers, greeting/
sign-off style, contraction/emoji use — and show the whole assembled
profile back to the user in plain language (not the raw file format). Let
them correct anything before saving.

**2g. Save.** Write the confirmed profile to `~/.naturalize/profile.md`
using the structure in `references/profile-template.md`.

## Step 3 — Partial recalibration (any time, no full redo)

Handle these without re-running all of Step 2:

- **Add/replace a sample** for one register → re-run just 2f's synthesis
  for that register, leave the other register and all rules untouched.
- **Toggle one rule** ("turn off typos," "stop flagging passive voice") →
  flip that single entry in the Rules section.
- **Edit custom instructions** → replace or append to that field.
- **Change default voice or preview setting** → update that single field.

Always write the change back to `~/.naturalize/profile.md` immediately —
don't batch edits across a session.

## Step 4 — Resolve register for this request

1. **Explicit wins** — "as an email," "for Slack," "make it formal" (or
   informal) directly sets the register.
2. **Otherwise infer** from the content/context being naturalized
   (greeting style, recipient cues, subject line) and state the assumption
   briefly so the user can correct it.
3. **Otherwise fall back** to the profile's `default_voice`.

## Step 5 — Apply the profile

Rewrite the input text using the loaded profile:

- Vocabulary: common words over rare synonyms, corporate filler stripped,
  domain jargon left alone — per whichever toggles are on.
- Symbols: ASCII-typeable forms over Unicode lookalikes, per the table in
  `references/checklist.md`, honoring any `symbols_exceptions` the profile
  records.
- Structure / openers-closers / formatting / hedging: apply whichever
  toggles are on, per `references/checklist.md`'s descriptions.
- Typos: only when the resolved register is informal **and** the toggle is
  on, at the stored frequency (`rare`/`occasional`), never in protected
  content.
- Custom instructions: apply as stated, plus any one-off instruction given
  for this specific request.

**Never touch protected content** — code blocks, quoted/cited text, URLs,
numbers, proper nouns, domain terminology — regardless of which toggles
are on.

**Don't over-enforce.** An "on" toggle applied with 100% consistency (e.g.
literally zero dashes, perfectly even sentence lengths) reads as its own
kind of artificial pattern. Allow rare, natural-looking exceptions.

## Step 6 — Deliver the result

- **Preview enabled** → show a before/after (or a short list of what
  changed) and let the user confirm or ask for adjustments before treating
  it as final.
- **Preview disabled** → output the rewritten text directly.

## Error handling

- No profile exists and the request isn't a calibration request → run
  Step 2 first; don't attempt to naturalize text against a profile that
  doesn't exist yet.
- Profile file exists but doesn't match the expected structure → say so
  plainly and offer to recalibrate rather than guessing at a partial read.
- Register genuinely ambiguous and `default_voice` doesn't obviously fit
  (e.g. a message that reads as neither clearly formal nor informal) → ask
  once, don't guess silently.
</content>
