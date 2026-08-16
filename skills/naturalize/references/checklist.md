# Naturalize checklist

The full Phase 2 catalogue of "AI writing tells" this skill can strip,
grouped for presentation during calibration. Defaults are the recommended
starting toggle state — the user can flip any of them, individually or by
group, during calibration or later via a partial recalibration.

## Symbols (hard rule — default: on)

Prefer whatever a standard keyboard types over the Unicode lookalike —
that's what humans actually produce, and the Unicode form is one of the
most reliable AI tells there is.

| Unicode | Use instead |
|---|---|
| — (em dash), – (en dash) | `-` (hyphen), or restructure with a comma |
| → , ⇒ | `->` |
| ≥ , ≤ | `>=` , `<=` |
| ≠ | `!=` |
| × | `x` |
| ÷ | `/` |
| … | `...` |
| “ ” ‘ ’ (curly quotes) | `"` `'` (straight quotes) |
| • (prose bullet) | `-` or `*` |

Not covered by this rule: `™`, `®`, `©` — these carry legal/brand meaning,
not an AI tell, so leave them as-is.

**Exceptions**, in priority order:
1. **Protected content** (see below) — never rewritten regardless of this
   rule.
2. **User-stated regional/personal preference** — e.g. if the user says
   they genuinely prefer an em dash or en dash in their own writing, that
   overrides the default ban for them specifically; record it as a
   deviation in their profile rather than silently applying the default.

## Vocabulary (default: on)

- **Common words over rare synonyms** — "use" not "utilize," "help" not
  "facilitate," "show" not "demonstrate." If a rarer word is genuinely the
  user's normal register (technical writers, academics), don't force it
  down — this rule targets reaching for an unusual synonym where an
  everyday word says the same thing, not vocabulary level generally.
- **Corporate/marketing filler** — "robust," "seamless," "cutting-edge,"
  "unlock," "elevate," "game-changer."
- **Filler intensifiers** — "essentially," "fundamentally," "arguably,"
  "in many ways" used as padding rather than to add real meaning.
- **Domain-specific jargon is whitelisted** — terminology that's actually
  normal vocabulary in the user's field (e.g. "idempotent," "P95 latency")
  is not a tell for that user and should never be flagged or swapped out.

## Sentence / paragraph structure (default: on)

- **Rule-of-three lists** — adjective/noun triplets ("fast, reliable, and
  scalable") show up constantly in AI text; vary the count or restructure.
- **Symmetric constructions** — "not only... but also," "on one hand... on
  the other."
- **Uniform sentence length** — AI text tends toward evenly medium
  sentences; real writing has more variance, including short fragments
  next to longer ones.
- **Semicolon overuse.**

## Openers / closers (default: on)

- **Stock openers** — "Great question!," "Certainly!," "I'd be happy to
  help."
- **Stock closers** — "I hope this helps!," "Let me know if you have any
  questions!," "Feel free to reach out."
- **Unnecessary end recap** — "In summary...," "To sum up..." tacked onto
  an already-short message.

## Formatting (default: on)

- **Bullet/numbered lists** used where the content reads fine as prose.
- **Bold-text overuse** for emphasis.
- **Headers on short messages** that don't need the structure.

## Hedging / tone (default: on)

- **Over-qualifying claims** — "this could potentially perhaps..."
- **Excessive politeness / apologizing.**
- **Passive voice** where active reads more natural for the user's voice.

## Typos (default: off)

Optional, and scoped tightly when enabled:

- Only in the **informal register** — never applied to formal/precision
  contexts.
- **Low frequency**, randomized placement — comically frequent typos read
  as fake; the goal is the occasional slip a real fast typist makes
  (missed letter, or two adjacent letters swapped).
- Frequency is itself configurable: `rare` or `occasional`.
- **Never** inside protected content (see below), even when typos are
  otherwise on — a swapped letter in a variable name or URL breaks things
  rather than reading as human.

## Protected content (standing rule — not a toggle)

None of the above rules — symbols, vocabulary, structure, typos — ever
apply inside:

- Code blocks/inline code.
- Quoted or cited text (someone else's words, block quotes) — altering a
  quotation misrepresents the source.
- URLs, numbers, proper nouns.
- Domain-specific terminology (see Vocabulary above).

## A note on over-enforcement

Don't apply any "on" toggle with 100% consistency. A human writer who
*never once* uses a dash or *never once* has a slightly uneven sentence is,
itself, suspiciously perfect. Allow rare, low-probability exceptions so
the output doesn't trade one kind of artificial pattern for another.
</content>
