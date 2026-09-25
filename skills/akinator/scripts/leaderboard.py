"""Akinator leaderboard: the best and worst run per (mode, question limit).

Every board is ranked from the user's point of view, so "best" always means
"the user did well":

  claude-guesses (user thinks, Claude asks)
      stumping Claude beats any run Claude guessed; within each outcome,
      more questions is better.
  user-guesses (Claude thinks, user asks)
      guessing it beats giving up / running out; guessed runs rank by fewer
      questions, lost runs by more questions (held out longer).

A new run replaces a stored one only when strictly better (best) or strictly
worse (worst), so on a tie the earlier run keeps its place.

Usage:
  leaderboard.py record --mode M --limit L --secret S --domain D
                        --questions N --outcome guessed|not-guessed [--note T]
  leaderboard.py show [--mode M] [--limit L]
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

MODES = ("claude-guesses", "user-guesses")
LIMITS = ("20", "25", "none")
DOMAINS = ("character", "animal", "object")
OUTCOMES = ("guessed", "not-guessed")


def board_file():
    return Path(os.environ.get("AKINATOR_HOME") or Path.home() / ".akinator") / "leaderboard.json"


def load():
    try:
        return json.loads(board_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "boards": {}}


def save(data):
    path = board_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def score(mode, entry):
    """Higher is better for the user; compared as tuples."""
    questions = entry["questions"]
    if mode == "claude-guesses":
        return (entry["outcome"] == "not-guessed", questions)
    guessed = entry["outcome"] == "guessed"
    return (guessed, -questions if guessed else questions)


def apply_run(boards, mode, limit, entry):
    key = f"{mode}/{limit}"
    board = boards.setdefault(key, {})
    new_best = "best" not in board or score(mode, entry) > score(mode, board["best"])
    new_worst = "worst" not in board or score(mode, entry) < score(mode, board["worst"])
    if new_best:
        board["best"] = entry
    if new_worst:
        board["worst"] = entry
    return {"board": key, "new_best": new_best, "new_worst": new_worst, **board}


def validate(args):
    if args.questions < 1:
        sys.exit("--questions must be at least 1.")
    if args.limit != "none" and args.questions > int(args.limit):
        sys.exit(f"--questions ({args.questions}) exceeds the {args.limit}-question limit.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="record a finished game")
    rec.add_argument("--mode", required=True, choices=MODES)
    rec.add_argument("--limit", required=True, choices=LIMITS)
    rec.add_argument("--secret", required=True)
    rec.add_argument("--domain", required=True, choices=DOMAINS)
    rec.add_argument("--questions", required=True, type=int)
    rec.add_argument("--outcome", required=True, choices=OUTCOMES)
    rec.add_argument("--note")
    rec.add_argument("--date", default=date.today().isoformat())
    show = sub.add_parser("show", help="print stored boards")
    show.add_argument("--mode", choices=MODES)
    show.add_argument("--limit", choices=LIMITS)
    args = parser.parse_args(argv)

    data = load()
    if args.command == "record":
        validate(args)
        entry = {
            "secret": args.secret,
            "domain": args.domain,
            "questions": args.questions,
            "outcome": args.outcome,
            "date": args.date,
        }
        if args.note:
            entry["note"] = args.note
        result = apply_run(data["boards"], args.mode, args.limit, entry)
        save(data)
        print(json.dumps(result, ensure_ascii=False))
    else:
        boards = {
            key: board
            for key, board in data["boards"].items()
            if (args.mode is None or key.split("/")[0] == args.mode)
            and (args.limit is None or key.split("/")[1] == args.limit)
        }
        print(json.dumps(boards, ensure_ascii=False))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
