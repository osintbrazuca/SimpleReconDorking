"""
Run-config preset system for SimpleReconDorking.

A run-config is a JSON file that stores CLI argument defaults, enabling
repeatable dorking runs without long command lines.

Usage:
    python simplerecondorking.py -d 'site:{TARGET} ext:sql' -t example.com \
        --config config/run_config.example.json

Precedence (highest → lowest):
    1. Explicit CLI flags     (always win)
    2. Run-config file values (applied where CLI kept the argparse default)
    3. Argparse defaults      (built into parser)

Only keys present in the JSON and not None are applied; unknown keys are
silently ignored so configs stay forward/backward compatible.
"""
from __future__ import annotations

import json
import os
from argparse import Namespace

# Argparse defaults - used to detect whether the user explicitly supplied a flag.
# Any value equal to the default is assumed to be "not set by the user".
_PARSER_DEFAULTS: dict[str, object] = {
    'output': 'txt',
    'outfile': None,
    'threads': 8,
    'timeout': 30,
    'rate_limit': 0,
    'pages': 2,
    'profile': None,
    'sources': None,
    'category': None,
    'exclude': None,
    'filter_host': None,
    'filter_string': None,
    'filter_regex': None,
    'filter_file': None,
    'network_map': False,
    'network_html': None,
    # 'proxy' stays None (never []): argparse's append action mutates a list
    # default in place, and an [] here would also break the equality test below
    # for a run-config that supplies proxies ([] == None is False). The pool
    # normalizes None / "str" / ["list"] itself, so a config written before
    # --proxy became repeatable still works.
    'proxy': None,
    'proxy_file': None,
    'proxy_source': None,
    'proxy_profile': None,
    'proxy_rotate': 'sticky',
    'proxy_rotate_secs': 0,
    'proxy_rotate_reqs': 0,
    'proxy_rotate_status': None,
    'proxy_rotate_body': None,
    'proxy_rotate_regex': None,
    'proxy_retries': 2,
    'proxy_ban_after': 3,
    'proxy_fallback_direct': False,
    'user_agent': 'SimpleReconDorking/1',
    'ua_file': None,
    'ua_source': None,
    'ua_profile': None,
    'header': None,
    'header_file': None,
    'header_source': None,
    'header_profile': None,
    'verbose': 0,
    'quiet': False,
    'no_banner': False,
    'no_color': False,
    'no_progress': False,
    'config': None,
}


def load_run_config(path: str) -> dict:
    """Load and return a run-config JSON as a flat dict.

    Raises SystemExit on file-not-found or JSON parse error so the caller
    gets a clean error message.
    """
    import sys
    import core.colors as colors

    if not os.path.isfile(path):
        print(colors.format_msg(f'[!] [config] Run-config file not found: {path}'))
        sys.exit(1)

    try:
        with open(path, 'r') as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(colors.format_msg(f'[!] [config] Invalid JSON in {path}: {exc}'))
        sys.exit(1)

    if not isinstance(data, dict):
        print(colors.format_msg(f'[!] [config] Run-config must be a JSON object: {path}'))
        sys.exit(1)

    return data


def apply_run_config(args: Namespace, config: dict) -> None:
    """Apply config values to *args* only where the arg still holds its default.

    CLI-supplied values (i.e. values that differ from the argparse default)
    are never overwritten.
    """
    for key, value in config.items():
        if value is None:
            continue
        if key not in _PARSER_DEFAULTS:
            continue
        current = getattr(args, key, _PARSER_DEFAULTS[key])
        if current == _PARSER_DEFAULTS[key]:
            setattr(args, key, value)
