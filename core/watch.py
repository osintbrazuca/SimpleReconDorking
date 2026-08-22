"""
Continuous-monitoring scheduler for SimpleReconDorking.

`--watch-add "CRON"` registers the current command (with `--watch-add` stripped)
into the fixed system DB (`core/system_db.py::watch_jobs`) against a 5-field cron
schedule. `--watch` runs a daemon that, every minute, launches the jobs whose cron
matches now - jobs due in the same minute run in parallel.

Minimal in-house cron matcher (stdlib only): supports `*`, lists (`a,b`), ranges
(`a-b`), and steps (`*/n`, `a-b/n`) across the five fields
`minute hour day-of-month month day-of-week` (DOW 0–6 Sun–Sat, 7 = Sun).
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from datetime import datetime

import core.colors as colors
from core import system_db

_FIELD_BOUNDS = (
    (0, 59),   # minute
    (0, 23),   # hour
    (1, 31),   # day of month
    (1, 12),   # month
    (0, 6),    # day of week (0 = Sunday)
)


# ── cron matching ─────────────────────────────────────────────────────────────

def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field into the set of integers it matches. Raises ValueError."""
    values: set[int] = set()
    for token in field.split(','):
        token = token.strip()
        if not token:
            raise ValueError(f'empty cron field token in {field!r}')
        step = 1
        if '/' in token:
            token, step_s = token.split('/', 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f'invalid step in {field!r}')
        if token == '*':
            start, end = lo, hi
        elif '-' in token:
            a, b = token.split('-', 1)
            start, end = int(a), int(b)
        else:
            start = end = int(token)
        if start > end or start < lo or end > hi:
            raise ValueError(f'cron value out of range [{lo},{hi}] in {field!r}')
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> list[set[int]]:
    """Parse a 5-field cron expression into per-field value sets. Raises ValueError."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f'cron must have 5 fields, got {len(fields)}: {expr!r}')
    return [_parse_field(f, lo, hi) for f, (lo, hi) in zip(fields, _FIELD_BOUNDS)]


def cron_matches(expr: str, dt: datetime) -> bool:
    """Return True if *dt* (to the minute) satisfies the 5-field cron *expr*."""
    minute_s, hour_s, dom_s, month_s, dow_s = expr.split()
    sets = parse_cron(expr)
    cron_dow = (dt.weekday() + 1) % 7  # Python Mon=0..Sun=6 → cron Sun=0..Sat=6

    minute_ok = dt.minute in sets[0]
    hour_ok = dt.hour in sets[1]
    month_ok = dt.month in sets[3]
    dom_ok = dt.day in sets[2]
    dow_ok = cron_dow in sets[4]

    # Vixie rule: when both DOM and DOW are restricted, match if EITHER matches.
    if dom_s != '*' and dow_s != '*':
        day_ok = dom_ok or dow_ok
    else:
        day_ok = dom_ok and dow_ok

    return minute_ok and hour_ok and month_ok and day_ok


# ── command reconstruction ────────────────────────────────────────────────────

def build_command_string(argv: list[str]) -> str:
    """Rebuild the command to register: drop `--watch-add` (+ value), abspath argv[0]."""
    out: list[str] = []
    i = 0
    args = list(argv)
    if args:
        out.append(os.path.abspath(args[0]))
        i = 1
    while i < len(args):
        tok = args[i]
        if tok == '--watch-add':
            i += 2  # skip the flag and its value
            continue
        if tok.startswith('--watch-add='):
            i += 1  # inline form: skip just this token
            continue
        out.append(tok)
        i += 1
    return shlex.join(out)


# ── daemon ────────────────────────────────────────────────────────────────────

def _launch(command: str) -> subprocess.Popen:
    """Launch a stored command as a detached subprocess (non-blocking → parallel)."""
    return subprocess.Popen(
        [sys.executable] + shlex.split(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _tick(now: datetime) -> int:
    """Fire every due job for the current minute (in parallel). Returns the count fired.

    Prints one line per launched job showing the scheduled command that ran.
    """
    minute_key = now.strftime('%Y-%m-%dT%H:%M')
    hhmm = now.strftime('%H:%M')
    fired = 0
    for job in system_db.list_watch_jobs():
        if job['last_run'] == minute_key:
            continue
        try:
            if not cron_matches(job['schedule'], now):
                continue
        except ValueError:
            continue  # skip malformed schedules
        system_db.update_watch_last_run(job['id'], minute_key)
        _launch(job['command'])
        fired += 1
        print(colors.format_msg(
            f'[+] [watch] {hhmm} fired job #{job["id"]}: {job["command"]}'
        ))
    return fired


def run_daemon() -> None:
    """Monitoring loop: each minute, launch due jobs in parallel. Ctrl-C to stop."""
    system_db.init()
    n = len(system_db.list_watch_jobs())
    print(colors.format_msg(
        f'[*] [watch] monitoring {n} job(s) from {system_db.SYSTEM_DB} - Ctrl-C to stop'
    ))
    last_minute = None
    try:
        while True:
            now = datetime.now()
            minute_key = now.strftime('%Y-%m-%dT%H:%M')
            if minute_key != last_minute:
                last_minute = minute_key
                _tick(now)  # prints one line per fired command
            time.sleep(2)
    except KeyboardInterrupt:
        print('\n' + colors.format_msg('[!] [watch] stopped.'))
