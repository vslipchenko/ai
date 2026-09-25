# akinator

*A two-way guessing game named after [Akinator](https://en.wikipedia.org/wiki/Akinator).*

Think of a character, animal or object and Claude asks yes/no questions until
it guesses it. Or flip it around: Claude secretly picks one and you ask the
questions. Claude's own world knowledge replaces Akinator's database, so
anything reasonably well known works.

## Install

This is a **standalone skill**, not a plugin — there's no `claude plugin
install` for it. Put the folder where Claude Code looks for skills:

```bash
# personal (available in every project)
cp -r skills/akinator ~/.claude/skills/akinator

# or project-local (this project only)
cp -r skills/akinator /path/to/project/.claude/skills/akinator
```

(Symlink instead of `cp -r` if you want it to track updates from this repo.)
Restart Claude Code (or reload skills) afterwards.

## Playing

Say "let's play akinator" (or "20 questions", "guess what I'm thinking"). Claude
asks for whatever you didn't specify, all on one screen:

| Setting | Options |
|---|---|
| Mode | **You think, I guess** · **I think, you guess** |
| Domain | Character (real or fictional) · Animal · Object |
| Limit | **25** like Akinator (default) · **20** classic · no limit |

Rules for both modes:

- Every question counts, and so does every guess, so a wrong guess costs one
  question.
- With a limit, the last question must be a guess.
- Three wrong guesses end the game.
- Quitting ends the game without recording it.

### You think, I guess

Each question comes as a select list, so you can't mistype an answer:

```
Q7/25  Is your character from a video game?
  ( ) Yes
  ( ) Probably
  ( ) Probably not
  ( ) No
  ( ) Other → back | quit
```

There's deliberately no "Don't know". Pick whichever way you lean. Claude
treats every answer as evidence rather than proof, so a wrong lean, or even
a wrong Yes/No, can be recovered from. Type `back` in *Other* to take back
your last answer, or `quit` to stop.

Claude keeps a private shortlist and asks questions that split it roughly in
half. It posts a one-line recap every 5 answers and guesses when it's
confident. If it loses, you tell it the answer, and it points out any of your
answers that didn't fit. Those runs are still recorded, with a note next to
them.

### I think, you guess

The catch with this direction is that a language model has no hidden memory.
If Claude just "thought of" something, nothing would stop it from quietly
switching mid-game. So the skill doesn't let Claude pick at all:

1. A bundled script picks the secret with a CSPRNG from the word lists
   (1000 characters, 500 animals and 1000 objects, plus your own
   additions). Recently used secrets are skipped.
2. It stores the secret in `~/.akinator/secret.json` and prints only a
   **salted SHA-256 commitment**, which Claude shows you before the first
   question.
3. At the end, the salt and secret are revealed so you can check that the
   secret never changed:

   ```bash
   printf '%s' '<salt>:<secret>' | sha256sum    # macOS: shasum -a 256
   ```

The salt is what stops you from hashing every list entry to find the answer.

Ask yes/no questions in plain text, guess with "Is it …?", or say "give up".
Claude answers Yes / Probably / Probably not / No, or "Don't know" when the
question genuinely has no answer for that secret.

> **Avoiding spoilers:** Claude reads the secret with its Read tool, whose
> output Claude Code shows collapsed. Don't expand that tool call
> (`ctrl+o`) during the game.

### Your own secret lists

Add entries to files with the same names under `~/.akinator/secrets/`:

```
~/.akinator/secrets/characters.txt
~/.akinator/secrets/animals.txt
~/.akinator/secrets/objects.txt
```

Put one entry per line. Lines starting with `#` are comments. Entries
already in the bundled list are skipped, ignoring case. You can also just ask
Claude, e.g. "add shoebill and blobfish to my akinator animals".

## Leaderboard

For each mode and question limit, Claude keeps your **best** and **worst**
run: the secret, domain, question count, outcome and date. Each mode has 3
limits, so there are up to 6 boards, and results under different limits are
never ranked together. "Best" always means *you* did well:

| Mode | Best | Worst |
|---|---|---|
| You think, I guess | you stumped Claude; otherwise, Claude needed the most questions | Claude guessed it in the fewest questions |
| I think, you guess | you guessed it in the fewest questions | you lost, the sooner the worse |

A run that stumps Claude beats any run Claude guessed. A loss ranks below any
win. On a tie, the earlier run keeps its place. Ask "show my akinator
leaderboard" to see it.

## Files

| Path | Purpose |
|---|---|
| `scripts/secret.{py,mjs}` | pick and commit to the secret (`commit`), reveal and verify it (`reveal`) |
| `scripts/leaderboard.{py,mjs}` | rank and store runs (`record`), print boards (`show`) |
| `references/secrets/*.txt` | bundled secret lists |
| `~/.akinator/leaderboard.json` | your boards |
| `~/.akinator/secret.json` | the current secret (deleted on reveal) |
| `~/.akinator/recent.json` | the last 10 secrets per domain, skipped when picking |
| `~/.akinator/secrets/*.txt` | your extension lists |

Set `AKINATOR_HOME` to keep state somewhere other than `~/.akinator`.

## Requirements

Python 3 or Node.js, standard library only. Without either, "You think, I
guess" still works but isn't recorded. "I think, you guess" is refused,
because the secret can't be committed to honestly.

Run the tests with:

```bash
node --test skills/akinator/scripts/tests/akinator.test.mjs
python3 -m unittest discover -s skills/akinator/scripts/tests
```

## License

MIT (repo default — see the root [README](../../README.md)).
