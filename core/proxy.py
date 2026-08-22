"""
Proxy pool for SimpleReconDorking.

Why this lives outside the sources
----------------------------------
`core/engine.py` builds a **new source instance per (source, dork) pair**, so
anything a source stores about proxies dies with that one task. Rotation state,
per-proxy failure counters and the ban list therefore have to live in a single
object owned by `Engine.run()` and handed down to every source it creates.

Rotation granularity (the hybrid model)
---------------------------------------
httpx pins the proxy when the *client* is constructed, and every source opens
one client per `fetch()` outside its pagination loop. So:

  * `sticky` / `round-robin` - one proxy per (source, dork) task. The whole
    pagination run of that task shares an IP, which is what the paginated
    sources need: yahoo's `b=` offsets, seznam's `from=`, and above all the
    browser sources, whose session tokens (`so`'s `psid`, `mojeek`'s `chv`)
    are bound to the IP that obtained them.
  * `random` - a fresh proxy, and therefore a fresh client, per request. Real
    per-request rotation, paid for with the connection pool.
  * A trigger firing mid-task (`--proxy-rotate-status`/`-body`/`-secs`/`-reqs`)
    swaps the proxy and rebuilds one client; subsequent requests in that task
    reuse it, so keep-alive is only lost at the moment of rotation.

Fail-closed by default
----------------------
When every proxy is banned or the pool was never populated, `acquire()` and
`rotate()` raise `ProxyExhausted` and the run aborts. Falling back to a direct
connection leaks the operator's real IP at exactly the moment they believed
they were covered, so it is opt-in via `--proxy-fallback-direct`.
"""
from __future__ import annotations

import random
import re
import time
from argparse import Namespace

# Rotation modes accepted by --proxy-rotate.
ROTATE_MODES = ('sticky', 'random', 'round-robin')


class ProxyExhausted(BaseException):
    """Every proxy in the pool is banned (or the pool is empty).

    **Inherits BaseException, not Exception, and that is load-bearing.** Every
    source module wraps its request loop in its own `except Exception`
    (`sources/passive/yahoo.py`, `googlecse.py`, and so on in all 21 httpx
    sources), and `sources/base.py` states "must never raise" as the source
    contract. An `Exception` subclass would therefore be swallowed inside the
    source and never reach `Engine`. Verified against CPython's
    `asyncio/tasks.py`: only KeyboardInterrupt/SystemExit are re-raised into
    the loop, so any other BaseException is handed back normally by
    `gather(return_exceptions=True)` - which is exactly the propagation path
    needed, with zero edits to the 26 sources.
    """


def read_proxy_file(path: str) -> list[str]:
    """One proxy per line; '#' comments and blank lines ignored.

    Mirrors `core/engine.py::_read_lines` (which does the same for --dork-file)
    rather than `core.assets.load_lines`, because that one is hard-wired to
    assets/txt/ and this path comes from the operator.
    """
    import sys

    import core.colors as colors

    try:
        with open(path, 'r') as fh:
            return [
                line.strip() for line in fh
                if line.strip() and not line.strip().startswith('#')
            ]
    except FileNotFoundError:
        print(colors.format_msg(f'[!] [proxy] File not found: {path}'))
        sys.exit(1)


def _as_list(value) -> list[str]:
    """Normalize --proxy / a run-config "proxy" key into a list.

    `--proxy` is `action='append'` on the CLI (a list), but a run-config JSON
    written before this feature carries a bare string, and `_PARSER_DEFAULTS`
    still uses None. All three shapes have to survive.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in value if str(v).strip()]


class ProxyPool:
    """Holds the proxy list plus all rotation/ban state for one run."""

    def __init__(
        self,
        proxies: list[str],
        rotate: str = 'sticky',
        rotate_secs: int = 0,
        rotate_reqs: int = 0,
        rotate_status: set[int] | None = None,
        rotate_body: list[str] | None = None,
        rotate_regex: re.Pattern | None = None,
        retries: int = 2,
        ban_after: int = 3,
        fallback_direct: bool = False,
    ) -> None:
        # dict.fromkeys de-dupes while keeping the operator's order, which is
        # what round-robin walks.
        self.proxies: list[str] = list(dict.fromkeys(proxies))
        self.rotate = rotate
        self.rotate_secs = rotate_secs
        self.rotate_reqs = rotate_reqs
        self.rotate_status: set[int] = rotate_status or set()
        self.rotate_body: list[str] = rotate_body or []
        self.rotate_regex: re.Pattern | None = rotate_regex
        self.retries = retries
        self.ban_after = ban_after
        self.fallback_direct = fallback_direct

        self._index = 0
        self._current: str | None = None
        self._since = time.monotonic()
        self._reqs = 0
        self._fails: dict[str, int] = {}
        self._banned: set[str] = set()
        # Sticky: once the pool runs dry the run is over. Engine checks this
        # BEFORE dispatching each remaining task, so a dead pool stops the run
        # promptly instead of letting all dorks x sources tasks march on
        # against nothing - gather(return_exceptions=True) waits for every one
        # of them, which on a catalog-sized run is thousands of tasks.
        self.exhausted = False
        # Counters for the end-of-run summary, so a misconfigured pool is
        # visible without -vvvv.
        self.rotations = 0
        self.failures = 0

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_args(cls, args: Namespace) -> 'ProxyPool | None':
        """Build a pool from parsed args, or None when no proxy was configured.

        Returning None (rather than an empty pool) keeps the no-proxy path
        byte-identical to how the tool behaved before this feature existed.
        """
        proxies = _as_list(getattr(args, 'proxy', None))
        if getattr(args, 'proxy_file', None):
            proxies += read_proxy_file(args.proxy_file)
        if not proxies:
            return None

        return cls(
            proxies=proxies,
            rotate=getattr(args, 'proxy_rotate', 'sticky') or 'sticky',
            rotate_secs=int(getattr(args, 'proxy_rotate_secs', 0) or 0),
            rotate_reqs=int(getattr(args, 'proxy_rotate_reqs', 0) or 0),
            rotate_status=_parse_status(getattr(args, 'proxy_rotate_status', None)),
            rotate_body=_parse_body(getattr(args, 'proxy_rotate_body', None)),
            rotate_regex=_parse_regex(getattr(args, 'proxy_rotate_regex', None)),
            retries=int(getattr(args, 'proxy_retries', 2) or 0),
            ban_after=int(getattr(args, 'proxy_ban_after', 3) or 0),
            fallback_direct=bool(getattr(args, 'proxy_fallback_direct', False)),
        )

    # ------------------------------------------------------------------
    # Pool state
    # ------------------------------------------------------------------

    @property
    def alive(self) -> list[str]:
        return [p for p in self.proxies if p not in self._banned]

    def _pick(self) -> str:
        """Next proxy per the rotation mode. Caller must ensure alive is non-empty."""
        alive = self.alive
        if self.rotate == 'random':
            return random.choice(alive)
        if self.rotate == 'round-robin':
            self._index = (self._index + 1) % len(alive)
            return alive[self._index % len(alive)]
        return alive[0]  # sticky

    def _exhausted(self) -> str | None:
        """Handle an empty pool: return None to go direct, or raise."""
        self.exhausted = True
        if self.fallback_direct:
            return None
        raise ProxyExhausted(
            f'proxy pool exhausted ({len(self._banned)}/{len(self.proxies)} banned) - '
            'pass --proxy-fallback-direct to allow direct connections instead'
        )

    def acquire(self) -> str | None:
        """A proxy for a new task."""
        if not self.alive:
            return self._exhausted()
        # sticky keeps handing out the same one until something rotates it.
        if self.rotate == 'sticky' and self._current and self._current not in self._banned:
            return self._current
        self._current = self._pick()
        self._since = time.monotonic()
        self._reqs = 0
        return self._current

    def rotate_now(self, current: str | None = None) -> str | None:
        """Force a move off *current*; returns the replacement."""
        if current and len(self.alive) > 1:
            # Advance past the one that just failed so sticky doesn't re-pick it.
            try:
                self._index = self.proxies.index(current)
            except ValueError:
                pass
        if not self.alive:
            return self._exhausted()
        if self.rotate == 'sticky':
            # sticky has no cursor of its own; step through the alive list.
            alive = self.alive
            nxt = alive[(alive.index(current) + 1) % len(alive)] if current in alive else alive[0]
            self._current = nxt
        else:
            self._current = self._pick()
        self._since = time.monotonic()
        self._reqs = 0
        self.rotations += 1
        return self._current

    # ------------------------------------------------------------------
    # Rotation triggers
    # ------------------------------------------------------------------

    def note_request(self) -> None:
        self._reqs += 1

    def wants_body(self) -> bool:
        """True when --proxy-rotate-body or --proxy-rotate-regex is armed.

        Callers check this before touching `resp.text`: matching needs the whole
        decoded body, and result pages here routinely run 350-450KB, so it must
        stay opt-in rather than being paid on every request.
        """
        return bool(self.rotate_body or self.rotate_regex)

    def should_rotate(self, status: int | None = None, body: str | None = None) -> bool:
        """Whether any armed trigger fired for the response just received."""
        if status is not None and status in self.rotate_status:
            return True
        if body and self.rotate_body:
            low = body.lower()
            if any(needle.lower() in low for needle in self.rotate_body):
                return True
        if body and self.rotate_regex and self.rotate_regex.search(body):
            return True
        if self.rotate_secs and (time.monotonic() - self._since) >= self.rotate_secs:
            return True
        if self.rotate_reqs and self._reqs >= self.rotate_reqs:
            return True
        return False

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def report_failure(self, proxy: str | None) -> bool:
        """Count a failure against *proxy*; returns True if it got banned.

        Also called by the browser sources, which cannot rotate mid-fetch but
        can still recognise a block - so a burned proxy leaves the pool for the
        tasks that follow even when this one could not be rescued.
        """
        if not proxy:
            return False
        self.failures += 1
        if not self.ban_after:
            return False
        self._fails[proxy] = self._fails.get(proxy, 0) + 1
        if self._fails[proxy] >= self.ban_after and proxy not in self._banned:
            self._banned.add(proxy)
            return True
        return False

    def report_success(self, proxy: str | None) -> None:
        """Reset the consecutive-failure counter - ban_after counts a streak."""
        if proxy:
            self._fails.pop(proxy, None)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def summary(self) -> str:
        return (
            f'{len(self.alive)}/{len(self.proxies)} proxy(ies) alive, '
            f'{self.rotations} rotation(s), {self.failures} failure(s), '
            f'mode={self.rotate}'
        )


def playwright_proxy(proxy: str | None) -> dict | None:
    """Split a proxy URL into Playwright's {'server','username','password'}.

    Chromium **ignores credentials embedded in the `server` value** - Playwright
    requires them as separate keys. Every browser source here previously passed
    `{'server': self.proxy}` verbatim, so an authenticated proxy (which is what
    commercial rotating pools hand out) silently produced 407s while the httpx
    sources, which do accept inline userinfo, worked fine.

    Note Chromium supports no SOCKS5 authentication at all; a socks5:// proxy
    carrying credentials is reported by the caller rather than failing silently.
    """
    if not proxy:
        return None
    from urllib.parse import urlsplit

    parts = urlsplit(proxy)
    if not parts.hostname:
        return {'server': proxy}
    port = f':{parts.port}' if parts.port else ''
    out: dict = {'server': f'{parts.scheme}://{parts.hostname}{port}'}
    if parts.username:
        out['username'] = parts.username
    if parts.password:
        out['password'] = parts.password
    return out


# ----------------------------------------------------------------------
# CLI value parsing (list flags are opaque strings, split at point of use -
# the same convention as --sources/--exclude/--dork-category)
# ----------------------------------------------------------------------

def parse_status_list(raw: str | None) -> tuple[set[int], list[str]]:
    """'403,429,503' -> ({403, 429, 503}, []). Second item is the junk found.

    Shared with cli/parser.py so the same rule validates the flag at parse time
    and the run-config value at pool-build time.
    """
    if not raw:
        return set(), []
    out: set[int] = set()
    bad: list[str] = []
    for tok in (t.strip() for t in str(raw).split(',')):
        if not tok:
            continue
        try:
            code = int(tok)
        except ValueError:
            bad.append(tok)
            continue
        if not 100 <= code <= 599:
            bad.append(tok)
            continue
        out.add(code)
    return out, bad


def _parse_status(raw: str | None) -> set[int]:
    """parse_status_list(), but exits the run on junk (config-file path)."""
    import sys

    import core.colors as colors

    out, bad = parse_status_list(raw)
    if bad:
        print(colors.format_msg(
            f'[!] [proxy] --proxy-rotate-status: not an HTTP status code: {", ".join(bad)}'
        ), file=sys.stderr)
        sys.exit(2)
    return out


def _parse_body(raw: str | None) -> list[str]:
    """'Access denied,unusual traffic' -> ['Access denied', 'unusual traffic']."""
    if not raw:
        return []
    return [t.strip() for t in str(raw).split(',') if t.strip()]


def _parse_regex(raw: str | None) -> re.Pattern | None:
    """Compile --proxy-rotate-regex, exiting the run on an invalid pattern
    (config-file path - cli/parser.py's `_regex` validator already catches
    this when the value comes from the CLI flag directly).

    A single pattern, not a comma-split list like --proxy-rotate-body: a
    comma is common regex syntax (`\\d{2,4}`), so splitting on it would break
    legitimate patterns. Multiple alternatives use `|` instead.
    """
    if not raw:
        return None
    import sys

    import core.colors as colors

    try:
        return re.compile(raw)
    except re.error as exc:
        print(colors.format_msg(
            f'[!] [proxy] --proxy-rotate-regex: invalid regex: {exc}'
        ), file=sys.stderr)
        sys.exit(2)
