"""Test-only entry point: safe_install.py's CLI with fake_claude.py injected.

The real CLI has no way to swap out `claude`; only tests run this file.
"""

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import safe_install  # noqa: E402

FAKE_CLAUDE = [sys.executable, "-I", str(HERE / "fake_claude.py")]
_original_init = safe_install.Gate.__init__


def _init_with_fake(self, *args, **kwargs):
    kwargs.setdefault("claude_command", FAKE_CLAUDE)
    _original_init(self, *args, **kwargs)


safe_install.Gate.__init__ = _init_with_fake

if __name__ == "__main__":
    sys.exit(safe_install.main())
