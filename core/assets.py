"""
Loader for the data files that ship as data rather than logic.

These hold the lists that can be edited or extended without touching Python.
They live in two places, and which one a file belongs in is a judgement about
how often an operator is expected to touch it:

* **assets/txt/** - lists that are effectively fixed fodder for the code
  (User-Agents to rotate, public CSE IDs). Read with load_lines().
* **config/** - the same idea, but for lists an operator is expected to curate
  alongside profiles.json and dork_categorys.json. Read with
  load_config_lines() for one-per-line files and load_config_list() for a list
  nested inside a JSON document.

Line format is shared: one entry per line, blank lines and '#' comments
ignored. JSON files have no comment syntax, so they carry their prose in
'_'-prefixed keys instead, the same convention config/run_config.example.json
uses; load_config_list() reads one named key and ignores everything else.

A missing or empty file yields an empty list, which disables whatever depends on
it. That is deliberate: the file is the single source of truth, so there is no
in-code copy to silently diverge from it. Callers are expected to notice the
empty list and say so (see the sources' `_vlog(1, ...)` messages).

Results are cached per lookup, mirroring core/config.py's approach.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).parent.parent
ASSETS_DIR = _ROOT / 'assets' / 'txt'
CONFIG_DIR = _ROOT / 'config'

_cache: dict[str, list[str]] = {}


def _read_lines(path: Path) -> list[str]:
    """The useful lines of *path* - stripped, no blanks, no '#' comments."""
    try:
        raw = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    return [
        stripped for stripped in (line.strip() for line in raw)
        if stripped and not stripped.startswith('#')
    ]


def load_lines(name: str) -> list[str]:
    """Return the useful lines of assets/txt/*name* ([] if missing/empty)."""
    key = f'assets:{name}'
    if key not in _cache:
        _cache[key] = _read_lines(ASSETS_DIR / name)
    return _cache[key]


def load_config_lines(name: str) -> list[str]:
    """Return the useful lines of config/*name* ([] if missing/empty).

    Same format and same failure mode as load_lines(); the only difference is
    which directory the file is curated in.
    """
    key = f'config:{name}'
    if key not in _cache:
        _cache[key] = _read_lines(CONFIG_DIR / name)
    return _cache[key]


def load_config_list(name: str, key: str) -> list[str]:
    """Return the list under *key* in the JSON document config/*name*.

    Entries are stringified and stripped, and blanks are dropped, so a JSON
    list behaves exactly like the one-per-line files above. Anything unusable -
    file missing, malformed JSON, key absent, or the key holding something that
    is not a list - yields [], because every caller of this module already
    handles "empty means the feature is off" and a data file should never be
    able to abort a run.

    Sibling keys are ignored, which is what lets one document hold several
    unrelated lists plus the '_'-prefixed prose that stands in for the comments
    JSON does not have.
    """
    cache_key = f'config:{name}#{key}'
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        data = json.loads((CONFIG_DIR / name).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        _cache[cache_key] = []
        return []

    raw = data.get(key) if isinstance(data, dict) else None
    if not isinstance(raw, list):
        _cache[cache_key] = []
        return []

    _cache[cache_key] = [
        stripped for stripped in (str(item).strip() for item in raw) if stripped
    ]
    return _cache[cache_key]
