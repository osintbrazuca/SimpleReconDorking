"""
Shared helpers for the Tor/.onion sources (ahmia, torch, tor66, tordex).

Underscore-prefixed so the dynamic registry in sources/__init__.py skips it,
same mechanism as _search_common.py.

Why these sources need their own module at all
----------------------------------------------
A `.onion` address has no public DNS record - it is resolved by the Tor
daemon itself, which means the request has to go through SOCKS5 with
**remote DNS** (`socks5h://`, the scheme curl spells `--socks5-hostname`).
Plain `socks5://` would try to resolve the hostname locally and fail before
a connection is ever attempted. httpx 0.28 supports `socks5h://` natively
(it hands the raw scheme to httpcore.AsyncSOCKSProxy) - verified live
against these four engines.

The proxy itself is NOT acquired here: Engine passes it to the constructor
as `proxy=` for any source with REQUIRES_TOR = True, so `self.proxy` carries
it and both _make_client() and _rebuild_client() honour it for free.
"""
import re

# A v3 onion address is exactly 56 base32 characters (a-z, 2-7) plus '.onion'.
# Deliberately NOT loosened to also accept the 16-char v2 form: v2 was removed
# from the Tor network in October 2021, so matching it would only ever produce
# dead URLs in the output.
ONION_RE = re.compile(r'https?://[a-z2-7]{56}\.onion[^\s"\'<>]*')
ONION_HREF_RE = re.compile(r'href="(https?://[a-z2-7]{56}\.onion[^"]*)"')


def tor_error_hint(exc: Exception, proxy: str | None) -> str | None:
    """A friendly one-liner for the two failure modes an operator actually
    hits, or None when *exc* is something else (caller falls back to
    _log_exc, which only speaks at -v 4).

    Both cases would otherwise surface as a bare exception type that gives no
    clue what to do about it - and both are entirely about the environment,
    not about the engine being down.
    """
    name = type(exc).__name__
    if isinstance(exc, ImportError) or 'socksio' in str(exc):
        return (
            "SOCKS support missing - install it with: pip install 'httpx[socks]'"
        )
    if name in ('ConnectError', 'ProxyError', 'ConnectTimeout'):
        return (
            f'Tor not reachable at {proxy or "(no --tor-proxy set)"} - is the Tor '
            'daemon running? (test: curl --socks5-hostname localhost:9050 https://ifconfig.ca)'
        )
    return None
