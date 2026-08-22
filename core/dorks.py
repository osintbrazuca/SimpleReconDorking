"""Load and expand the built-in JSON dork catalog."""
from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

CATALOG_FILE = Path(__file__).parent.parent / 'config' / 'dork_categorys.json'

PLACEHOLDER = '{TARGET}'
FAMILIES = ('operators', 'operators_out')

_cache: dict[str, dict] | None = None


def _catalog() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        _cache = {}
        return _cache
    dorks = data.get('dorks', {}) if isinstance(data, dict) else {}
    _cache = dorks if isinstance(dorks, dict) else {}
    return _cache


def categories() -> list[str]:
    """Every catalog category available, sorted by name."""
    return sorted(_catalog())


def load_category(name: str, family: str | None = None) -> list[str]:
    """Return one family, or both families, from a category."""
    category = _catalog().get(name, {})
    families = (family,) if family in FAMILIES else FAMILIES
    return [
        template
        for key in families
        for template in category.get(key, [])
        if isinstance(template, str) and template.strip()
    ]


def describe(name: str) -> str:
    """Return a category's one-line description."""
    description = _catalog().get(name, {}).get('description', '')
    return description if isinstance(description, str) else ''


def counts() -> dict[str, int]:
    return {name: len(load_category(name)) for name in categories()}


def needs_target(template: str) -> bool:
    return PLACEHOLDER in template


def target_is_host(target: str | None) -> bool:
    """Whether target is an IP address or a dotted DNS host name."""
    if not target or any(char.isspace() for char in target):
        return False
    candidate = target.rstrip('.')
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    try:
        ascii_host = candidate.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    if len(ascii_host) > 253 or '.' not in ascii_host:
        return False
    label = re.compile(r'^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$', re.I)
    return all(label.fullmatch(part) for part in ascii_host.split('.'))


def family_for_target(target: str | None) -> str:
    return 'operators' if target_is_host(target) else 'operators_out'


def expand(template: str, target: str | None) -> str | None:
    """Substitute {TARGET} in *template*.

    Returns None when the template needs a target and none was given - the
    caller reports that as a skipped dork instead of sending a query with a
    literal '{TARGET}' in it, which every engine would answer with noise.
    """
    if PLACEHOLDER not in template:
        return template
    if not target:
        return None
    return template.replace(PLACEHOLDER, target)
