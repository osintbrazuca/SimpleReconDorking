"""
Shared helpers for the search-source modules.

Underscore-prefixed on purpose: source package loaders skip modules
starting with '_', so this stays an importable helper instead of becoming a
selectable source.

Search engines are the one place where the tool's own identity hurts: a
default User-Agent like `SimpleReconDorking/1` gets a request blocked or
challenged immediately. These helpers provide a realistic desktop browser
fingerprint and polite pacing.
"""
import asyncio
import random

from core.assets import load_config_lines, load_lines

# Default from cli/parser.py - used to tell "user left it alone" from
# "user explicitly asked for this UA".
_TOOL_DEFAULT_UA = 'SimpleReconDorking/1'

# Data lives in a file so it can be edited without touching code. The two sit
# in different directories on purpose: the UA pool is fodder the code rotates
# through, while the domain blocklist is a curated list an operator extends
# whenever a new source starts leaking its own chrome - so it lives in config/
# next to profiles.json, and is read with the config/ loader.
_UA_FILE = 'user_agents.txt'
_ENGINE_DOMAIN_FILE = 'search_engine_domains.txt'


def random_ua() -> str:
    """A random desktop User-Agent, or '' when the UA list is unavailable."""
    uas = load_lines(_UA_FILE)
    return random.choice(uas) if uas else ''


def effective_ua(configured_ua: str) -> str:
    """Pick the User-Agent to send to a search engine.

    Honours `--user-agent` when the user actually set one; otherwise rotates a
    browser UA, because the tool's default is an instant block here.

    If assets/txt/user_agents.txt is missing or empty there is nothing to
    rotate - fall back to whatever UA is configured rather than raising. A
    request has to carry *some* User-Agent, so "disable the feature" is not an
    option here the way it is for a dork list.
    """
    if configured_ua and configured_ua != _TOOL_DEFAULT_UA:
        return configured_ua
    return random_ua() or configured_ua or _TOOL_DEFAULT_UA


def browser_headers(referer: str = '', configured_ua: str = '') -> dict:
    """Browser-like headers for a search-engine request."""
    headers = {
        'User-Agent': effective_ua(configured_ua),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
    }
    if referer:
        headers['Referer'] = referer
    return headers


async def polite_sleep(base: float = 2.0) -> None:
    """Pause between paged requests, with jitter.

    Hammering result pages back-to-back is what trips the anti-bot checks.
    Dorking multiplies this risk: one run can fire dozens of distinct queries
    at the same engine, so the pacing here is what keeps a whole run from
    being challenged halfway through.
    """
    await asyncio.sleep(base + random.uniform(0.4, 1.4))


def is_source_chrome(host: str, keep_host: str | None = None) -> bool:
    """True when *host* is a search source's own navigation/domain.

    Result pages are full of links back into the source itself (settings,
    image tabs, other regional domains). Those are never dork results, so every
    source routes its findings through BaseSource._filter_urls(), which calls
    this.

    *keep_host* is the --filter-host value when one is set: if the operator is
    deliberately dorking one of these domains, its URLs must survive the
    filter. When config/search_engine_domains.txt is missing the check
    degrades to a no-op rather than dropping anything.
    """
    if not host:
        return False
    if keep_host and (host == keep_host or host.endswith(f'.{keep_host}')):
        return False
    engine_domains = load_config_lines(_ENGINE_DOMAIN_FILE)
    if not engine_domains:
        return False
    return any(host == d or host.endswith(f'.{d}') for d in engine_domains)
