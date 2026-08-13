"""Cryptographically secure password / diceware passphrase generator.

All randomness comes from `secrets` (a CSPRNG) — never from the model
typing out characters itself, which would not be uniformly random.
Character-class coverage (e.g. "must contain a digit") is enforced by
rejection sampling on the whole candidate string, not by force-inserting
a character afterward, so the output stays uniformly random over the
constrained space instead of losing entropy to a biased construction.
"""

import argparse
import json
import math
import platform
import secrets
import subprocess
import sys
from pathlib import Path

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/~"
AMBIGUOUS = set("O0Il1|`'\"")

DEFAULT_WORDLIST = Path(__file__).resolve().parent.parent / "references" / "eff_large_wordlist.txt"


def build_charset(use_lower, use_upper, use_digits, use_symbols, no_ambiguous):
    classes = []
    if use_lower:
        classes.append(LOWER)
    if use_upper:
        classes.append(UPPER)
    if use_digits:
        classes.append(DIGITS)
    if use_symbols:
        classes.append(SYMBOLS)
    if not classes:
        sys.exit("At least one character class must be enabled.")
    if no_ambiguous:
        classes = ["".join(c for c in cls if c not in AMBIGUOUS) for cls in classes]
        if any(not cls for cls in classes):
            sys.exit("--no-ambiguous removed an entire character class; disable that class instead.")
    return classes


def copy_to_clipboard(text):
    """Tries platform clipboard tools in order; returns True on the first that
    accepts the text. All generated values are pure ASCII, so no encoding/
    codepage concerns across clip/pbcopy/xclip/wl-copy/xsel."""
    system = platform.system()
    if system == "Windows":
        candidates = [["clip"]]
    elif system == "Darwin":
        candidates = [["pbcopy"]]
    else:
        candidates = [
            ["xclip", "-selection", "clipboard"],
            ["wl-copy"],
            ["xsel", "--clipboard", "--input"],
        ]
    for cmd in candidates:
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, OSError):
            continue
    return False


def gen_password(length, classes, max_attempts=10000):
    alphabet = "".join(classes)
    for _ in range(max_attempts):
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in cls for c in candidate) for cls in classes):
            return candidate
    sys.exit("Could not satisfy character-class coverage; increase length or reduce required classes.")


def entropy_bits(length, alphabet_size):
    return length * math.log2(alphabet_size)


def load_wordlist(path):
    with open(path, encoding="utf-8") as f:
        words = [line.strip() for line in f if line.strip()]
    if len(words) < 2:
        sys.exit(f"Wordlist at {path} looks empty or malformed.")
    return words


def gen_passphrase(word_count, wordlist, separator, capitalize, add_number):
    words = [secrets.choice(wordlist) for _ in range(word_count)]
    if capitalize:
        words = [w.capitalize() for w in words]
    bits = word_count * math.log2(len(wordlist))
    if add_number:
        digit = secrets.choice(DIGITS)
        words.append(digit)
        bits += math.log2(10)
    return separator.join(words), bits


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["password", "passphrase"], default="password")
    p.add_argument("--length", type=int, default=20, help="password mode: character length")
    p.add_argument("--count", type=int, default=1, help="how many to generate")
    p.add_argument("--no-upper", action="store_true")
    p.add_argument("--no-lower", action="store_true")
    p.add_argument("--no-digits", action="store_true")
    p.add_argument("--no-symbols", action="store_true")
    p.add_argument("--no-ambiguous", action="store_true", help="drop visually-confusable chars (0/O, 1/l/I, quotes, backtick)")
    p.add_argument("--words", type=int, default=6, help="passphrase mode: number of words")
    p.add_argument("--separator", default="-", help="passphrase mode: word separator")
    p.add_argument("--capitalize", action="store_true", help="passphrase mode: capitalize each word")
    p.add_argument("--add-number", action="store_true", help="passphrase mode: append a random digit")
    p.add_argument("--wordlist", default=str(DEFAULT_WORDLIST))
    p.add_argument("--clipboard", action="store_true", help="copy the value to the OS clipboard instead of printing it")
    args = p.parse_args()

    if args.count < 1:
        sys.exit("--count must be >= 1")
    if args.clipboard and args.count != 1:
        sys.exit("--clipboard only makes sense with --count 1 (it can hold one value); drop --clipboard or set --count 1.")

    results = []
    if args.mode == "password":
        classes = build_charset(
            not args.no_lower, not args.no_upper, not args.no_digits, not args.no_symbols, args.no_ambiguous
        )
        if args.length < len(classes):
            sys.exit(f"--length must be >= number of required character classes ({len(classes)})")
        alphabet_size = len(set("".join(classes)))
        for _ in range(args.count):
            pw = gen_password(args.length, classes)
            results.append({"value": pw, "entropy_bits": round(entropy_bits(args.length, alphabet_size), 1)})
    else:
        if args.words < 1:
            sys.exit("--words must be >= 1")
        wordlist = load_wordlist(args.wordlist)
        for _ in range(args.count):
            phrase, bits = gen_passphrase(args.words, wordlist, args.separator, args.capitalize, args.add_number)
            results.append({"value": phrase, "entropy_bits": round(bits, 1)})

    if args.clipboard:
        if copy_to_clipboard(results[0]["value"]):
            results[0]["value"] = "(copied to clipboard -- not printed)"
            results[0]["clipboard"] = True
        else:
            results[0]["clipboard"] = False
            print(
                "Clipboard copy failed (no clip/pbcopy/xclip/wl-copy/xsel found) -- printing value instead.",
                file=sys.stderr,
            )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
