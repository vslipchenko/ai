---
name: naturalize
description: Rewrite Claude-generated text so it matches the user's own personal writing voice, calibrated once via writing samples and a togglable checklist, then reused automatically on every later request. Use when the user asks to "naturalize" text, make it "sound like me" / "less like AI", "humanize" a draft, strip AI writing tells (em-dashes, curly quotes, stock phrases like "I hope this helps"), asks to (re)calibrate their writing-voice profile, or explicitly asks for a generic pass that ignores their profile ("naturalize this generically", "without my profile", "ignore my profile for this one").
---

# Naturalize

Rewrite text so it reads like the user actually wrote it, not like an LLM
drafted it — grounded in a profile calibrated once from the user's own
writing (not guessed from a generic "sound more human" instruction), then
reused silently on every later request until the user asks to change it.

`<SKILL_DIR>` below is this skill's own announced base directory (the path
shown when this skill loads, ending in `.../skills/naturalize`) —
references live at `<SKILL_DIR>/references/`.

## Step 1 — Determine request mode

Default behavior is `profile` mode: the saved profile (if any) governs
everything. The user can override this for a single request by explicitly
asking to skip it — "naturalize this generically," "without using my
profile," "ignore my profile for this one," "just de-AI-ify this, don't
personalize it." That sets `explicit_generic` mode for this request only.

- **`profile` mode** (default) → go to Step 2.
- **`explicit_generic` mode** → **do not read or write
  `~/.naturalize/profile.md` at all** for this request — not even to check
  whether it exists. Skip straight to Step 5, using the checklist's stated
  defaults (`references/checklist.md`): everything on except typos, no
  custom instructions, no voice/sample matching. This is a one-off
  override — it never triggers calibration and never modifies a saved
  profile.

If it's ambiguous whether the user means this request only or wants to
change their standing default, ask; don't silently reinterpret a one-off
request as a permanent profile change (that's what Step 4 is for) or vice
versa.

## Step 2 — Check for an existing profile

Look for a profile at `~/.naturalize/profile.md` (the user's home
directory — same external-storage pattern the `estimator` plugin uses for
`~/.estimator`, keeping personal writing samples out of the skill package
itself).

- **Found** → read it and skip straight to Step 5.
- **Not found** → run Step 3 (first-run calibration).

Never re-run calibration just because the skill was invoked again. Only an
explicit ask ("recalibrate," "redo my profile," "start over") re-triggers
full calibration; smaller asks ("turn off typos," "update my formal
sample") go through Step 4 instead.

## Step 3 — First-run calibration

Run this once, in order. The full toggle catalogue lives in
`references/checklist.md` — load it before Step 3c rather than
reconstructing it from memory. The saved-file structure lives in
`references/profile-template.md` — load it before Step 3g.

**3a. Default voice.** `AskUserQuestion`: Informal or Formal, with
Informal as the recommended option. This becomes `default_voice`, used in
Step 5 whenever a request's register can't be resolved any other way.

**3b. Phase 1 — writing samples.** Ask for a real informal sample (e.g. a
Slack message or text) and a real formal sample (e.g. an email or doc
excerpt). For whichever one the user can't supply, offer two options:

- **Write a substitute** — a few sentences spanning past, present, and
  future tense, enough to observe structure and habits without a real
  artifact. That register still gets personalized.
- **Skip it.** If they skip, say plainly what that means before moving
  on: that register will run in **generic mode** — the Phase 2 checklist
  (de-AI-ifying rules) still applies, but output won't be tailored to
  their specific voice, since nothing was learned about it. It'll read
  like a general humanizer pass for that register, not "sounds like you."
  They can add a sample later (Step 4) to personalize it whenever they
  want.

Track each register's resulting mode — `personalized` or `generic` — for
Step 3g.

**3c. Phase 2 — togglable checklist.** Present `references/checklist.md`'s
groups via `AskUserQuestion` (multiSelect per group): symbols, vocabulary,
structure, openers/closers, formatting, hedging/tone, and typos. State the
protected-content carve-out (code, quotations/citations, URLs, numbers,
proper nouns, domain jargon are never touched) once, up front — don't
repeat it per toggle. Typos default off; everything else defaults on.

**3d. Custom instructions.** Ask if there's anything else to add as free
text (e.g. "always use British spelling," "never start a sentence with
'So'"). Persists by default; can be overridden for a single later request
without changing the saved profile.

**3e. Preview toggle.** Ask whether the user wants a before/after preview
shown each time text is naturalized, or just the rewritten result.
Store as `Preview: enabled`.

**3f. Synthesize and confirm.** For each `personalized` register, turn its
sample into a short characteristic summary — sentence rhythm, formality
markers, greeting/sign-off style, contraction/emoji use. Skip synthesis
for any `generic` register — there's nothing to summarize. Show the whole
assembled profile back to the user in plain language (not the raw file
format), and if either register ended up `generic`, restate that plainly
in the summary — e.g. "your formal writing will use general de-AI-ifying
rules only, not a voice matched to you, since no sample was given." Let
them correct anything before saving.

**3g. Save.** Write the confirmed profile to `~/.naturalize/profile.md`
using the structure in `references/profile-template.md`.

## Step 4 — Partial recalibration (any time, no full redo)

Handle these without re-running all of Step 3:

- **Add/replace a sample** for one register → re-run just 3f's synthesis
  for that register, leave the other register and all rules untouched.
  Adding a sample to a `generic` register switches it to `personalized`.
- **Toggle one rule** ("turn off typos," "stop flagging passive voice") →
  flip that single entry in the Rules section.
- **Edit custom instructions** → replace or append to that field.
- **Change default voice or preview setting** → update that single field.

Always write the change back to `~/.naturalize/profile.md` immediately —
don't batch edits across a session. (This is distinct from Step 1's
`explicit_generic` override, which touches nothing on disk.)

## Step 5 — Resolve register for this request

1. **Explicit wins** — "as an email," "for Slack," "make it formal" (or
   informal) directly sets the register.
2. **Otherwise infer** from the content/context being naturalized
   (greeting style, recipient cues, subject line) and state the assumption
   briefly so the user can correct it.
3. **Otherwise fall back**:
   - `profile` mode → the profile's `default_voice`.
   - `explicit_generic` mode → no profile to fall back to; default to
     informal as a neutral standalone default.

## Step 6 — Apply the rules

Determine this request's **effective mode** for the resolved register:

- `generic` if the request is running in `explicit_generic` mode (Step 1),
  **or** if `profile` mode is active but the resolved register's saved
  mode is `generic` (no sample on file for it).
- `personalized` otherwise — `profile` mode, resolved register's saved
  mode is `personalized`.

Rewrite the input text:

- Vocabulary: common words over rare synonyms, corporate filler stripped,
  domain jargon left alone — per whichever toggles are on.
- Symbols: ASCII-typeable forms over Unicode lookalikes, per the table in
  `references/checklist.md`, honoring any `symbols_exceptions` the profile
  records (`personalized` effective mode only — `generic` uses the hard
  default with no exceptions, since the profile isn't consulted).
- Structure / openers-closers / formatting / hedging: apply whichever
  toggles are on, per `references/checklist.md`'s descriptions.
- Typos: only when the resolved register is informal **and** the toggle is
  on, at the stored frequency (`rare`/`occasional`), never in protected
  content. (`generic` effective mode: typos off, per the checklist
  default.)
- Custom instructions: `personalized` effective mode only — apply the
  profile's stored text plus any one-off instruction given for this
  specific request. `generic` effective mode ignores stored custom
  instructions (there's no profile in play) but still honors a one-off
  instruction given directly in this request.

**Which toggle values to use:**
- `effective mode == personalized` → use the profile's saved Rules
  section.
- `effective mode == generic` → use `references/checklist.md`'s stated
  defaults (everything on except typos), regardless of what any saved
  profile has toggled — a `generic` pass never reflects saved
  customizations, only the standing default checklist.

If `effective mode == generic`, don't attempt to match tone, rhythm, or
greeting style — apply only the toggle-driven rules above. This is the
"no personalization layer" path: functionally a general de-AI-ifier/
humanizer pass rather than a voice match.

**Never touch protected content** — code blocks, quoted/cited text, URLs,
numbers, proper nouns, domain terminology — regardless of which toggles
are on.

**Don't over-enforce.** An "on" toggle applied with 100% consistency (e.g.
literally zero dashes, perfectly even sentence lengths) reads as its own
kind of artificial pattern. Allow rare, natural-looking exceptions.

## Step 7 — Deliver the result

- **`profile` mode, and the profile's `Preview` setting is on** → show a
  before/after (or a short list of what changed) and let the user confirm
  or ask for adjustments before treating it as final. This applies
  regardless of whether the resolved register's effective mode ended up
  `personalized` or `generic` — `Preview` is a standing profile setting,
  not tied to one register.
- **`explicit_generic` mode, or `profile` mode with `Preview` off** →
  output the rewritten text directly.

Add one brief trailing note whenever effective mode is `generic`, so the
user isn't left assuming this was matched to their own voice when it
wasn't. Keep it to one line; don't repeat the full explanation from
calibration. Pick the wording that matches the actual reason:

- Request-level override → "(generic pass, per your request — your
  profile wasn't consulted.)"
- No sample on file for this register → "(generic de-AI-ify pass — no
  voice sample on file for this register; add one anytime to
  personalize.)"

## Error handling

- No profile exists, `profile` mode is active, and the request isn't a
  calibration request → run Step 3 first; don't attempt to naturalize
  text against a profile that doesn't exist yet. (Doesn't apply in
  `explicit_generic` mode — that path never needs a profile.)
- Profile file exists but doesn't match the expected structure, and
  `profile` mode is active → say so plainly and offer to recalibrate
  rather than guessing at a partial read. If the user actually wanted
  `explicit_generic` for this request, that still works fine regardless of
  profile-file health, since it's never read.
- Register genuinely ambiguous and there's no fallback that obviously fits
  (e.g. a message that reads as neither clearly formal nor informal, and
  either there's no `default_voice` in play or it doesn't fit either) →
  ask once, don't guess silently.
</content>
