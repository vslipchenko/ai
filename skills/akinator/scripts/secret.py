"""Pick, commit to, and reveal the secret for Akinator's reverse mode.

The model has no hidden memory: if it just "thinks of" a secret, it can
quietly drift to a different one mid-game. So the secret is picked here with
a CSPRNG from the bundled per-domain lists (which also avoids the model
picking the same few favourites every time) plus the user's own extension
lists in <state dir>/secrets/, written to a state file, and
only a salted SHA-256 commitment is printed. `reveal` prints the secret and
salt so the user can recompute the hash and confirm the secret never changed.
The salt matters: without it the hash of every list entry could be
precomputed and the commitment would give the answer away.

Usage:
  secret.py commit --domain character|animal|object
  secret.py reveal
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

DOMAINS = {"character": "characters.txt", "animal": "animals.txt", "object": "objects.txt"}
LISTS_DIR = Path(__file__).resolve().parent.parent / "references" / "secrets"
RECENT_LIMIT = 10


def state_dir():
    return Path(os.environ.get("AKINATOR_HOME") or Path.home() / ".akinator")


def read_entries(path):
    """Non-empty, non-comment lines of a list file; [] if it doesn't exist."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return []
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


def load_list(domain):
    """Bundled list merged with the user's extension list, deduplicated
    case-insensitively (first spelling wins). Returns (words, custom_count)."""
    words, seen, custom = [], set(), 0
    sources = ((LISTS_DIR, False), (state_dir() / "secrets", True))
    for directory, is_custom in sources:
        for word in read_entries(directory / DOMAINS[domain]):
            if word.casefold() not in seen:
                seen.add(word.casefold())
                words.append(word)
                custom += is_custom
    return words, custom


def commitment(salt, secret):
    return hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def pick(domain, recent):
    words, custom = load_list(domain)
    fresh = [w for w in words if w not in recent] or words
    return fresh[secrets.randbelow(len(fresh))], len(words), custom


def cmd_commit(domain):
    base = state_dir()
    recent = read_json(base / "recent.json", {})
    secret, pool, custom = pick(domain, recent.get(domain, []))
    salt = secrets.token_hex(16)
    digest = commitment(salt, secret)
    secret_file = base / "secret.json"
    write_json(secret_file, {
        "domain": domain,
        "secret": secret,
        "salt": salt,
        "hash": digest,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    # The secret itself is deliberately NOT printed.
    print(json.dumps({
        "domain": domain,
        "hash": digest,
        "secret_file": str(secret_file),
        "pool_size": pool,
        "custom_entries": custom,
    }))


def cmd_reveal():
    base = state_dir()
    secret_file = base / "secret.json"
    state = read_json(secret_file, None)
    if state is None:
        sys.exit("No committed secret found; start a game with `commit` first.")
    verified = commitment(state["salt"], state["secret"]) == state["hash"]
    recent = read_json(base / "recent.json", {})
    history = [w for w in recent.get(state["domain"], []) if w != state["secret"]]
    recent[state["domain"]] = (history + [state["secret"]])[-RECENT_LIMIT:]
    write_json(base / "recent.json", recent)
    secret_file.unlink()
    preimage = f"{state['salt']}:{state['secret']}"
    print(json.dumps({
        "domain": state["domain"],
        "secret": state["secret"],
        "salt": state["salt"],
        "hash": state["hash"],
        "verified": verified,
        "preimage": preimage,
    }, ensure_ascii=False))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    commit = sub.add_parser("commit", help="pick a secret and print its commitment hash")
    commit.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    sub.add_parser("reveal", help="print the secret, salt and hash, then clear it")
    args = parser.parse_args(argv)
    if args.command == "commit":
        cmd_commit(args.domain)
    else:
        cmd_reveal()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
