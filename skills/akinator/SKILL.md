---
name: akinator
description: Play an Akinator-style guessing game in either direction — the user thinks of a character, animal, or object and Claude asks yes/no questions to guess it, or Claude secretly picks one (committed up front with a salted SHA-256 hash, revealed and verifiable at the end) and the user asks the questions. Tracks a best/worst-run leaderboard per mode and question limit. Use when the user wants to play Akinator, 20 questions, "guess what I'm thinking", "think of something and I'll guess it", asks to see their Akinator leaderboard, or wants to add entries to their Akinator secret lists.
---

# Akinator

A two-way guessing game named after [Akinator](https://en.wikipedia.org/wiki/Akinator).
Akinator relies on a crowdsourced database; here Claude's own world knowledge
plays that role, so any character, animal or object the user thinks of is fair
game.

`<SKILL_DIR>` below is this skill's own announced base directory (the path
shown when this skill loads, ending in `.../skills/akinator`). State lives in
`~/.akinator/` (overridable with the `AKINATOR_HOME` environment variable).

**Running the scripts.** Try runtimes in order, first one that works, and
reuse it for the rest of the session:

1. `python3 "<SKILL_DIR>/scripts/<name>.py" ...`
2. else `python "<SKILL_DIR>/scripts/<name>.py" ...`
3. else `py -3 "<SKILL_DIR>/scripts/<name>.py" ...`
4. else `node "<SKILL_DIR>/scripts/<name>.mjs" ...`

Both versions take identical arguments and print JSON. If no runtime is
available, "You think, I guess" still works (without a leaderboard — say so).
"I think, you guess" does **not**: Claude has no hidden memory to hold a
secret honestly, so refuse that mode rather than improvising one.

## Step 1 — Set up the game

Three settings. Take any the user already gave ("let's play akinator with
animals, classic 20") and ask only for the missing ones, all in **one**
`AskUserQuestion` call (one question per missing setting):

| Setting | Options (in this order) | Stored as |
|---|---|---|
| Mode | "You think, I guess" · "I think, you guess" | `claude-guesses` · `user-guesses` |
| Domain | Character · Animal · Object | `character` · `animal` · `object` |
| Limit | "25 — Akinator (Recommended)" · "20 — Classic" · "No limit" | `25` · `20` · `none` |

"Character" covers real and fictional people and personified characters.

If the user only asked for the leaderboard, skip to Step 5.

## Step 2 — Shared rules

- **Questions count.** Every question asked counts, and so does every guess
  (a wrong guess costs one question). Questions taken back with `back` don't
  count.
- **Limits.** With `20` or `25`, the guesser has that many questions in
  total, and the last one must be a guess. The game is lost when the budget
  runs out without a correct guess. With `none` there's no budget.
- **Three wrong guesses** end the game as a loss for the guesser, in every
  limit.
- **Quitting** ends the game with no leaderboard entry.
- Show the running count as `Q{n}/{limit}` (or `Q{n}` with no limit).

## Step 3A — "You think, I guess" (`claude-guesses`)

Tell the user to think of a {domain} and start asking right away; there is
no separate "ready" step.

### Asking

Ask **one question per `AskUserQuestion` call**, `multiSelect: false`, with
exactly these four options in this order:

| Label | Description |
|---|---|
| Yes | Definitely true |
| Probably | Leaning yes, or mostly true |
| Probably not | Leaning no, or mostly false |
| No | Definitely false |

Header: `Q{n}/{limit}`. The tool always adds a free-text **Other** — it is
reserved for two commands:

- `back` → undo the last answered question (or guess): drop its answer,
  decrement the count, and re-ask it. Repeatable. Undoing a wrong guess also
  gives that guess back.
- `quit` → end the game (not recorded). Offer to name the answer anyway, for
  fun.

Anything else typed into Other: map it only when the meaning is unambiguous
(`y`, `yeah` → Yes; `nope` → No; `kinda` → Probably). "Don't know" and
similar are **not** an answer — say "pick whichever way you lean; a wrong
lean is recoverable" and re-ask the same question. Anything unrecognised →
re-ask the same question. Re-asks never count.

### Question strategy

- Keep a private shortlist of plausible candidates and ask the question that
  splits it closest to half ("Is your character from a video game?"). Broad
  first (real/fictional, era, medium, size, habitat, material), narrow later.
- Stick to widely known traits most people could answer. Avoid obscure trivia
  ("Was it created before 1950?") — the user has no "don't know" option.
- Treat every answer as **evidence, not proof**. "Probably" / "Probably not"
  are weak; even a hard Yes/No can be a user mistake ("does Batman have
  superpowers?"). Lower a candidate's likelihood; don't eliminate it on one
  answer.
- No disguised guesses: "Is it a yellow electric mouse Pokémon?" is a guess.
  Guesses are only made as guesses (below).
- Never repeat a question, and never reveal the shortlist mid-game.
- After every 5th answer, print a one-line recap of the answers so far before
  the next question, e.g. `So far: fictional · animated · not an animal ·
  probably from a film · …`.

### Guessing

Guess when confident, and always on the last question of a `20`/`25` game.
Ask via `AskUserQuestion`: header `Q{n}/{limit}`, question
`Guess {k}/3: Is it {candidate}?`, options **"Yes, that's it"** and **"No"**
(Other: `back` / `quit` as above).

- Yes → Claude wins. Go to "End of game".
- No → it counts as a question and a wrong guess; drop the candidate and keep
  asking (unless the budget or the three guesses are used up).

### End of game

- **Claude guessed it** → "Got it in {n} questions!" Outcome `guessed`.
- **Claude lost** (budget or three wrong guesses) → admit defeat and ask, in
  plain text, what it was. Wait for the reply. Outcome `not-guessed`.

Then, when the user revealed the answer (loss case), check each recorded
answer against it. List the ones that don't fit, briefly and without
accusation ("Q6 'Is it an animal?' — you said No, but Garfield is a cat").
If any didn't fit, record the run with `--note "{k} answers didn't fit"`.
Honest mistakes happen; the run is still recorded.

## Step 3B — "I think, you guess" (`user-guesses`)

### Committing to the secret

Run `secret commit --domain {domain}`. It picks the secret with a CSPRNG from
the bundled list plus the user's extension list (see Step 6) and prints
`{"domain", "hash", "secret_file", "pool_size", "custom_entries"}` —
**never the secret**.

Then learn the secret by reading `secret_file` with the **Read tool**. Never
`cat`/`type`/`Get-Content` it, never put the secret in any command, and
never mention it before the game ends: Bash commands and their output are
shown in the user's terminal, while Read output is collapsed.

Announce the game:

> I'm thinking of {a character / an animal / an object} (picked from
> {pool_size}). Commitment: `{hash}` — I'll reveal the salt at the end so you
> can check I never switched.
> Ask yes/no questions, guess any time with "Is it …?", or say "give up".
> You have {limit} questions.

### Answering

For every user message during the game:

- **A yes/no question** → counts. Answer truthfully about the secret with
  Yes / Probably / Probably not / No, or "Don't know" / "Doesn't really
  apply" when the question is genuinely unanswerable for it. Prefix the
  count: `Q7/25 — Probably not.` Only a word or two more when the plain
  answer would mislead (e.g. "Yes — in the films, not the books").
- **Several questions in one message** → answer only the first, counted,
  and ask for one at a time.
- **Not a yes/no question** ("what color is it?") → decline without
  counting and ask them to rephrase.
- **A guess** ("Is it a platypus?") → counts. Accept obvious equivalents
  (spelling, alias, "Spidey" for Spider-Man, "T. rex"). Wrong → `Q9/25 — No,
  it's not {guess}. {2} guesses left.`
- **"give up"** → the user loses. **"quit"** → ends without recording.
- No hints unless the user asks; if they do, give a small one and don't
  count it.

Stay consistent: before answering, re-check earlier answers so the facts
never contradict each other.

### End of game

On a correct guess, a loss (budget or three wrong guesses), give-up or quit,
run `secret reveal` — even for quit, so the secret isn't left on disk. It
prints `{"secret", "salt", "hash", "verified", "preimage"}`. Show:

> It was **{secret}**. Salt `{salt}` · hash `{hash}` · verified ✓
> Check it yourself: `printf '%s' '{preimage}' | sha256sum`
> (macOS: `shasum -a 256`)

If `verified` is false, say so plainly — something is wrong with the state
file. Outcome: `guessed` if the user got it, otherwise `not-guessed`.

## Step 4 — Record the run

Skip for quit. Otherwise run:

```
leaderboard record --mode {mode} --limit {limit} --secret "{secret}"
                   --domain {domain} --questions {n} --outcome guessed|not-guessed
                   [--note "{note}"]
```

The script ranks from the user's point of view (best = the user did well):

| Mode | Best | Worst |
|---|---|---|
| `claude-guesses` | stumped Claude > Claude guessed; then more questions | Claude guessed in the fewest questions |
| `user-guesses` | guessed > lost; guessed in fewer questions | lost; lost sooner is worse |

Ties keep the earlier run. The output includes `new_best` / `new_worst`; if
either is true, celebrate (or commiserate) in one line and show the board.
Otherwise just offer another round.

## Step 5 — Show the leaderboard

Run `leaderboard show` (optionally `--mode` / `--limit`). There is one board
per mode and limit; show only boards that exist, as a compact table:

| Board | | Secret | Domain | Questions | Outcome | Date |
|---|---|---|---|---|---|---|
| You think, I guess · 25 | Best | Gollum | character | 25 | stumped Claude | 2026-09-25 |
| | Worst | cat | animal | 6 | Claude guessed | 2026-09-24 |

Render the outcome from the user's side ("stumped Claude", "Claude guessed",
"you guessed", "you lost") and append any note. Empty → "No games recorded
yet."

## Step 6 — User extension lists

"I think, you guess" draws from the bundled lists in
`<SKILL_DIR>/references/secrets/` plus the user's own lists in
`~/.akinator/secrets/` with the same file names: `characters.txt`,
`animals.txt`, `objects.txt`. One entry per line; blank lines and lines
starting with `#` are ignored; entries already in the bundled list
(case-insensitive) are skipped.

When the user asks to add entries ("add shoebill and blobfish to my animals"),
append them to the right file, creating it if needed, and skip ones already
present in either list. Adding entries mid-game doesn't change the committed
secret. Only suggest well-known entries if they ask for ideas — obscure ones
make the game unfair.

## Error handling

- `secret reveal` with no committed secret → the state was lost (e.g. the
  file was deleted). Tell the user the game can't be verified and don't
  record it.
- `leaderboard record` refuses a question count above the limit or below 1 →
  recount from the conversation and retry; don't pad or clamp.
- A leftover `secret.json` from an abandoned game is simply overwritten by
  the next `commit`.
