"""
Per-target results store for SimpleReconDorking.

A single `--db FILE` is used as both the comparison source (input) and the save
target (output). It holds **only dorking results** (system/log data lives in
the fixed `config/system.db`, see core/system_db.py). The store is append-only;
rows are keyed by `seed` (the -t/--target value, or '(no target)' when none was
given), so "known" lookups use `SELECT DISTINCT` and the comparison baseline
for `--db-news` is the union of everything ever stored for that seed.

Schema (auto-created on first use)
----------------------------------
  urls    - every discovered URL, tagged with the engine and the dork query
            that returned it
  extras  - URLs excluded by an active --filter-* (type 'url_filtered',
            populated only at -v 3, only when a --filter-* was set)

Public API
----------
init_db(path)              - create schema if needed
save_result(path, result)  - persist one Engine result dict
load_known(path, seed)     - dict of sets of all previously seen values
filter_new(result, known)  - copy of result with only values absent from known
list_urls/list_extras      - read-only helpers for --db-list

Pure stdlib (`sqlite3`); no third-party dependency.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS urls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    seed        TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    source      TEXT,
    dork        TEXT,
    first_seen  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS extras (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    seed       TEXT    NOT NULL,
    type       TEXT    NOT NULL,
    value      TEXT    NOT NULL,
    first_seen TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_url_seed   ON urls(seed);
CREATE INDEX IF NOT EXISTS idx_url_url    ON urls(url);
CREATE INDEX IF NOT EXISTS idx_extra_seed ON extras(seed, type);
"""

_KNOWN_KEYS = ('urls', 'urls_filtered')


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    """Create the schema in *path* if it doesn't already exist."""
    conn = sqlite3.connect(path)
    try:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


def save_result(path: str, result: dict) -> None:
    """Persist a single Engine result dict (results only) into the database at *path*."""
    init_db(path)

    seed: str          = result.get('seed', '')
    urls: set          = result.get('urls', set()) or set()
    url_sources: dict  = result.get('url_sources', {}) or {}
    url_dorks: dict    = result.get('url_dorks', {}) or {}
    extras: dict       = result.get('extras', {}) or {}
    ts = datetime.now(timezone.utc).isoformat()

    conn = _connect(path)
    try:
        with conn:
            for url in urls:
                conn.execute(
                    """INSERT INTO urls
                       (seed, url, source, dork, first_seen)
                       VALUES (?, ?, ?, ?, ?)""",
                    (seed, url, url_sources.get(url), url_dorks.get(url), ts),
                )

            for val in (extras.get('urls_filtered', set()) or set()):
                conn.execute(
                    'INSERT INTO extras (seed, type, value, first_seen) VALUES (?, ?, ?, ?)',
                    (seed, 'url_filtered', val, ts),
                )
    finally:
        conn.close()


def load_known(path: str, seed: str) -> dict[str, set[str]]:
    """
    Return every value ever stored for *seed*, grouped by category.

    Keys: 'urls', 'urls_filtered'. Missing DB file (or any read error)
    yields empty sets, so a first run treats everything as new.
    """
    known: dict[str, set[str]] = {k: set() for k in _KNOWN_KEYS}
    try:
        init_db(path)
        conn = _connect(path)
    except sqlite3.Error:
        return known
    try:
        for row in conn.execute(
            'SELECT DISTINCT url FROM urls WHERE seed = ?', (seed,)
        ):
            known['urls'].add(row['url'])
        for row in conn.execute(
            "SELECT DISTINCT value FROM extras WHERE seed = ? AND type = 'url_filtered'", (seed,)
        ):
            known['urls_filtered'].add(row['value'])
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return known


def _list_query(path: str, sql: str, seed: str | None) -> list:
    """Run a read-only listing query, optionally filtered by seed. Empty on error."""
    try:
        conn = _connect(path)
    except sqlite3.Error:
        return []
    try:
        if seed:
            rows = conn.execute(sql + ' WHERE seed = ?' + _ORDER[sql], (seed,)).fetchall()
        else:
            rows = conn.execute(sql + _ORDER[sql]).fetchall()
        return [tuple(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


_SQL_URLS   = 'SELECT DISTINCT url, source, dork FROM urls'
_SQL_EXTRAS = 'SELECT DISTINCT type, value FROM extras'
_ORDER = {
    _SQL_URLS:   ' ORDER BY url',
    _SQL_EXTRAS: ' ORDER BY type, value',
}


def list_urls(path: str, seed: str | None = None) -> list[tuple[str, str, str]]:
    """All distinct collected URLs as (url, source, dork)."""
    return _list_query(path, _SQL_URLS, seed)


def list_extras(path: str, seed: str | None = None) -> list[tuple[str, str]]:
    """All distinct extras as (type, value) - URLs excluded by an active --filter-*."""
    return _list_query(path, _SQL_EXTRAS, seed)


def filter_new(result: dict, known: dict[str, set[str]]) -> dict:
    """
    Return a copy of *result* containing only values absent from *known*.

    Filters urls, prunes url_sources / url_dorks to the surviving urls, and
    filters the filtered-URL extras. `seed`, `dorks` and `sources` are
    preserved unchanged.
    """
    known_urls          = known.get('urls', set())
    known_urls_filtered = known.get('urls_filtered', set())

    new_urls = {u for u in (result.get('urls') or set()) if u not in known_urls}

    url_sources = result.get('url_sources', {}) or {}
    new_url_sources = {u: s for u, s in url_sources.items() if u in new_urls}

    url_dorks = result.get('url_dorks', {}) or {}
    new_url_dorks = {u: d for u, d in url_dorks.items() if u in new_urls}

    extras = result.get('extras', {}) or {}
    new_extras: dict[str, set] = {}
    filtered_new = {
        u for u in extras.get('urls_filtered', set()) if u not in known_urls_filtered
    }
    if filtered_new:
        new_extras['urls_filtered'] = filtered_new

    return {
        'seed': result.get('seed', ''),
        'dorks': result.get('dorks', []),
        'urls': new_urls,
        'sources': result.get('sources', {}),
        'url_sources': new_url_sources,
        'url_dorks': new_url_dorks,
        'extras': new_extras,
    }
