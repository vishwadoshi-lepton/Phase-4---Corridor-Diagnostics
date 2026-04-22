"""Load project-root `.env` into os.environ without adding a dependency.

Usage:
    from _env import load_dotenv
    load_dotenv()   # idempotent, no-op if .env is missing
    os.environ["POSTGRES_HOST"]  # now populated

Parsing rules:
  - one KEY=VALUE per line
  - blank lines and lines starting with `#` are ignored
  - values may be wrapped in single or double quotes; the quotes are stripped
  - existing os.environ values are NOT overwritten (shell exports win)
"""
from __future__ import annotations
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))


def load_dotenv(path: str | None = None) -> int:
    """Load .env at project root (or at `path`). Returns # of vars set."""
    target = path or os.path.join(_PROJECT_ROOT, ".env")
    if not os.path.isfile(target):
        return 0
    n = 0
    with open(target) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if (val.startswith('"') and val.endswith('"')) or \
               (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val
                n += 1
    return n
