"""Where the API key comes from.

`sdoc/classify/llm.py` tells you to put `GEMINI_API_KEY` in a `.env` file,
but nothing in the repo read one, so the key only ever worked when it was
exported by hand in the terminal it ran from. This module reads it.

Order of precedence, highest first:

1. a real environment variable, so a host like Render wins over any file
2. `.env` in the repo root
3. nothing, in which case the pipeline degrades rather than fails -- the
   rule classifier and the label extractor both run without a key

Call `load_env()` once at the top of an entry point. It is safe to call more
than once and it never overwrites a variable that is already set.

    from sdoc.config import load_env
    load_env()

python-dotenv is used when it is installed; otherwise the small parser below
does the job. Either way `.env` stays out of git -- `.gitignore` already
excludes it and allows `.env.example`.
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

_loaded = False


def _parse(path: pathlib.Path) -> dict:
    """Read KEY=value lines. Ignores comments, blanks and `export` prefixes."""
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip one matching pair of surrounding quotes, and nothing else:
        # a key is opaque and must survive verbatim.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(path: pathlib.Path | None = None) -> dict:
    """Load .env into os.environ without clobbering anything already set.

    -> the names that were loaded from the file, for a caller that wants to
    report what it found. Values are never returned or printed: a key that
    turns up in a log is a key you have to rotate.
    """
    global _loaded
    path = path or ENV_PATH
    if _loaded and path == ENV_PATH:
        return {}
    if path == ENV_PATH:
        _loaded = True

    if not path.exists():
        return {}

    try:                                  # use the real thing when it is here
        from dotenv import dotenv_values
        values = dotenv_values(path)
    except ImportError:
        values = _parse(path)

    applied = {}
    for key, value in values.items():
        if value is None or key in os.environ:
            continue                      # the environment always wins
        os.environ[key] = value
        applied[key] = True
    return applied


def gemini_key() -> str | None:
    load_env()
    return os.environ.get("GEMINI_API_KEY") or None


def gemini_model() -> str:
    load_env()
    return os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


def describe() -> str:
    """One line for a startup banner. Never prints the key itself."""
    key = gemini_key()
    if not key:
        return ("no GEMINI_API_KEY - running offline on the rule classifier "
                "and the label extractor")
    source = "environment" if not ENV_PATH.exists() else ".env or environment"
    return f"GEMINI_API_KEY found ({source}), model {gemini_model()}"
