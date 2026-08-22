"""
Loader for the plain-text data files under assets/txt/.

These hold the lists that are data rather than logic - probe paths, User-Agents,
domain blocklists, public CSE IDs - so they can be edited or extended without
touching Python. Format is one entry per line; blank lines and '#' comments are
ignored.

A missing or empty file yields an empty list, which disables whatever depends on
it. That is deliberate: the file is the single source of truth, so there is no
in-code copy to silently diverge from it. Callers are expected to notice the
empty list and say so (see the sources' `_vlog(1, ...)` messages).

Results are cached per filename, mirroring core/config.py's approach.
"""
from __future__ import annotations

from pathlib import Path

ASSETS_DIR = Path(__file__).parent.parent / 'assets' / 'txt'

_cache: dict[str, list[str]] = {}


def load_lines(name: str) -> list[str]:
    """Return the useful lines of assets/txt/*name* ([] if missing/empty)."""
    if name in _cache:
        return _cache[name]

    try:
        raw = (ASSETS_DIR / name).read_text(encoding='utf-8').splitlines()
    except OSError:
        _cache[name] = []
        return []

    lines = [
        stripped for stripped in (line.strip() for line in raw)
        if stripped and not stripped.startswith('#')
    ]
    _cache[name] = lines
    return lines
