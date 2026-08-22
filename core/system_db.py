"""
Fixed system database for SimpleReconDorking.

Unlike the per-target `--db` (which stores recon *results*), this is a single,
install-relative SQLite file - `config/system.db` - that holds system/log data:

  command_history - one row per run: the executed command line + targets + time
  watch_jobs      - the cron scheduler registry (see core/watch.py)

The path is fixed (resolved from this module's location), so it is the same file
regardless of the working directory and is never passed as a CLI parameter.

Pure stdlib (`sqlite3`); no third-party dependency.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

# <repo>/config/system.db - resolved relative to this file (core/system_db.py)
SYSTEM_DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config',
    'system.db',
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS command_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    command   TEXT NOT NULL,
    targets   TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    command    TEXT NOT NULL,
    schedule   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_run   TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SYSTEM_DB)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout = 5000')  # parallel watch children write concurrently
    return conn


def init() -> None:
    """Create the system DB schema if absent (idempotent)."""
    os.makedirs(os.path.dirname(SYSTEM_DB), exist_ok=True)
    conn = sqlite3.connect(SYSTEM_DB)
    try:
        conn.execute('PRAGMA journal_mode = WAL')
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


# ── command_history ───────────────────────────────────────────────────────────

def log_command(command: str, targets: str | None = None) -> None:
    """Append one executed command line (with its targets) to command_history."""
    try:
        init()
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    'INSERT INTO command_history (command, targets, timestamp) VALUES (?, ?, ?)',
                    (command, targets, _now()),
                )
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # logging must never break a run


def list_command_history(target: str | None = None) -> list[tuple]:
    """Return command_history rows as (id, timestamp, targets, command), newest last."""
    try:
        init()
        conn = _connect()
        try:
            if target:
                rows = conn.execute(
                    "SELECT id, timestamp, targets, command FROM command_history "
                    "WHERE targets LIKE ? ORDER BY id",
                    (f'%{target}%',),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT id, timestamp, targets, command FROM command_history ORDER BY id'
                ).fetchall()
            return [tuple(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error:
        return []


# ── watch_jobs ────────────────────────────────────────────────────────────────

def add_watch_job(command: str, schedule: str) -> int:
    """Insert a watch job; returns its row id. Caller validates *schedule* first."""
    init()
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                'INSERT INTO watch_jobs (command, schedule, created_at) VALUES (?, ?, ?)',
                (command, schedule, _now()),
            )
            return cur.lastrowid
    finally:
        conn.close()


def list_watch_jobs() -> list[sqlite3.Row]:
    """Return all watch_jobs rows (id, command, schedule, created_at, last_run)."""
    try:
        init()
        conn = _connect()
        try:
            return conn.execute(
                'SELECT id, command, schedule, created_at, last_run FROM watch_jobs ORDER BY id'
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def update_watch_last_run(job_id: int, minute_key: str) -> None:
    """Mark a job as fired for *minute_key* (guards against double-fire in one minute)."""
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    'UPDATE watch_jobs SET last_run = ? WHERE id = ?',
                    (minute_key, job_id),
                )
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def delete_watch_job(job_id: int) -> int:
    """Delete the watch job with *job_id*; return rows deleted (0 ⇒ no such ID)."""
    init()
    conn = _connect()
    try:
        with conn:
            cur = conn.execute('DELETE FROM watch_jobs WHERE id = ?', (job_id,))
            return cur.rowcount
    finally:
        conn.close()


def clear_watch_jobs() -> int:
    """Delete all watch jobs; return how many were removed."""
    init()
    conn = _connect()
    try:
        with conn:
            n = conn.execute('SELECT COUNT(*) FROM watch_jobs').fetchone()[0]
            conn.execute('DELETE FROM watch_jobs')
            return n
    finally:
        conn.close()
