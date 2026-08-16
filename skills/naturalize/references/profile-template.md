# Naturalize profile — file template

This is the literal structure written to `~/.naturalize/profile.md` (the
user's home directory) at the end of calibration (SKILL.md Step 2g), and
updated in place by partial recalibration (Step 3). It's plain Markdown so
the user can open and hand-edit it directly if they want.

```markdown
# Naturalize Profile

default_voice: informal   # informal | formal

## Informal register
mode: personalized   # personalized | generic
sample: |
  <raw user sample, verbatim, or the past/present/future-tense sentences
  the user wrote during calibration if they had no real sample; empty if
  mode: generic>
characteristics: <synthesized summary — sentence rhythm, formality
  markers, greeting/sign-off style, contraction/emoji use, anything else
  observed; empty if mode: generic>

## Formal register
mode: personalized   # personalized | generic
sample: |
  <raw user sample, verbatim, or the past/present/future-tense sentences
  the user wrote during calibration if they had no real sample; empty if
  mode: generic>
characteristics: <synthesized summary, same shape as above; empty if
  mode: generic>

## Rules
symbols_ascii_only: on
symbols_exceptions: <any user-stated regional/personal deviation, e.g.
  "prefers en dash"; empty if none>
common_words: on
rule_of_three: on
symmetric_constructions: on
uniform_sentence_length: on
stock_openers: on
stock_closers: on
end_recap: on
bullet_overuse: on
bold_overuse: on
header_overuse: on
overqualifying: on
excessive_politeness: on
passive_voice: on
typos: off
typos_frequency: rare   # rare | occasional — only read when typos: on

## Preview
enabled: false

## Custom instructions
<free text the user added during calibration or a later edit; may be
empty>
```

Notes for whichever step reads/writes this file:

- `mode: generic` means the user explicitly declined to provide a sample
  or substitute sentences for that register (SKILL.md Step 2b). Leave
  `sample` and `characteristics` empty in that case — don't fall back to
  the other register's characteristics, since that would silently apply a
  voice the user never confirmed for this register. A `generic` register
  is rewritten using only the Phase 2 checklist rules (Step 5), and every
  delivery for it carries a brief one-line disclosure (Step 6) so the user
  knows it wasn't personalized.
- Partial recalibration (SKILL.md Step 3) rewrites only the touched
  field(s) — one register's sample+characteristics+mode, one Rules entry,
  or Custom instructions — and leaves everything else in the file
  untouched. Adding a sample to a `generic` register flips its `mode` to
  `personalized`.
- If the file exists but doesn't parse as this structure, treat it as
  corrupted per SKILL.md's error handling: say so and offer to
  recalibrate rather than guessing at a partial read.
</content>
