# Naturalize profile — file template

This is the literal structure written to `~/.naturalize/profile.md` (the
user's home directory) at the end of calibration (SKILL.md Step 2g), and
updated in place by partial recalibration (Step 3). It's plain Markdown so
the user can open and hand-edit it directly if they want.

```markdown
# Naturalize Profile

default_voice: informal   # informal | formal

## Informal register
sample: |
  <raw user sample, verbatim, or the past/present/future-tense sentences
  the user wrote during calibration if they had no real sample>
characteristics: <synthesized summary — sentence rhythm, formality
  markers, greeting/sign-off style, contraction/emoji use, anything else
  observed>

## Formal register
sample: |
  <raw user sample, verbatim, or the past/present/future-tense sentences
  the user wrote during calibration if they had no real sample>
characteristics: <synthesized summary, same shape as above>

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

- If a register's `sample` was never provided and the user declined to
  write substitute sentences, leave `sample` and `characteristics` empty
  and fall back to the *other* register's characteristics plus the
  general Rules section when that register is needed — don't block on it.
- Partial recalibration (SKILL.md Step 3) rewrites only the touched
  field(s) — one register's sample+characteristics, one Rules entry, or
  Custom instructions — and leaves everything else in the file untouched.
- If the file exists but doesn't parse as this structure, treat it as
  corrupted per SKILL.md's error handling: say so and offer to
  recalibrate rather than guessing at a partial read.
</content>
