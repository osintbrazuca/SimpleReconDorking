"""
Source contract for SimpleReconDorking.

Every implementation under the source subpackages subclasses BaseSource and
answers one question: "given this dork string, which URLs does your index
return?"

The unit of work is a Dork, not a host. That is the whole difference from the
rest of the SimpleRecon family: nothing here derives a query from a target -
the operator's string IS the query, and the tool's job is to run it against as
many indexes as possible and merge the answers.
"""
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

import core.colors as colors
from core.progress import NullProgress

_DEFAULT_UA = 'SimpleReconDorking/1'

# Per-source cap on collected URLs. A broad dork ('ext:sql') against a paging
# source can otherwise run for a very long time for diminishing returns.
_MAX_URLS_PER_SOURCE = 2000

# Search operators that only some indexes understand. Used to warn (and to
# down-convert the query) when a source that cannot parse them is asked to.
_OPERATOR_PREFIXES = (
    'site:', 'inurl:', 'intitle:', 'intext:', 'filetype:', 'ext:', 'link:',
    'cache:', 'related:', 'allinurl:', 'allintitle:', 'allintext:', 'inanchor:',
    'define:', 'info:', 'loc:', 'location:', 'feed:', 'hasfeed:', 'contains:',
    'lang:', 'language:', 'before:', 'after:', 'daterange:', 'numrange:',
    'ip:', 'domain:', 'url:', 'instreamset:', 'path:',
)


def _mask(proxy: str | None) -> str:
    """Proxy URL safe to print: credentials replaced with '***'.

    Rotation logs at -v 1 would otherwise print `http://user:pass@host` into
    the operator's terminal and scrollback.
    """
    if not proxy:
        return 'direct'
    if '@' not in proxy:
        return proxy
    scheme, _, rest = proxy.partition('://')
    if not rest:
        return proxy
    _, _, hostpart = rest.rpartition('@')
    return f'{scheme}://***@{hostpart}'


@dataclass(frozen=True)
class Dork:
    """One search query, plus where it came from.

    *query* is what actually gets sent to the sources - already expanded, so
    a template's {TARGET} placeholder is long gone by this point. *raw* keeps
    the unexpanded template and *target*/*category* the expansion context, so
    reports can group results by the dork the operator actually wrote.
    """
    query: str
    raw: str = ''
    target: str | None = None
    category: str | None = None

    @classmethod
    def of(
        cls,
        query: str,
        raw: str = '',
        target: str | None = None,
        category: str | None = None,
    ) -> 'Dork':
        query = ' '.join(query.split())
        return cls(query=query, raw=raw or query, target=target, category=category)

    def has_operators(self) -> bool:
        low = self.query.lower()
        return any(op in low for op in _OPERATOR_PREFIXES)

    def plain_terms(self) -> str:
        """The dork with search operators stripped down to bare terms.

        For indexes that do not parse operators at all (Marginalia, most SearXNG
        text backends): sending `site:example.com ext:sql` returns an error or
        nothing, while `example.com sql` at least returns something related.
        Quotes are kept - every source honours phrase search.
        """
        kept: list[str] = []
        for token in self.query.split():
            low = token.lower()
            matched = next((op for op in _OPERATOR_PREFIXES if low.startswith(op)), None)
            if matched:
                value = token[len(matched):]
                # 'site:example.com' -> 'example.com'; a bare 'ext:' drops out
                if value and not value.startswith('-'):
                    kept.append(value)
                continue
            if token.startswith(('-', '+')) and len(token) > 1:
                continue  # exclusion terms mean nothing without operator support
            kept.append(token)
        return ' '.join(kept).strip()


class BaseSource(ABC):
    NAME: str = ''
    DESCRIPTION: str = ''
    API_TOKEN_IS_REQUIREMENT: bool = False

    # Grouping shown by --list-sources and selectable via --category:
    #   'web'    -> a general web index (google, yahoo, bing, duckduckgo...)
    #   'code'   -> source code in public repositories (github, grep_app)
    #   'source' -> the markup/JS of indexed pages (publicwww)
    #   'legal'  -> public judicial/legal-process records (jusbrasil)
    #   'leak'   -> leak/paste/dump corpora (intelx)
    CATEGORY: str = 'web'

    # False when the index cannot parse search operators. The source still runs;
    # BaseSource.query_for() hands it Dork.plain_terms() instead, and the source
    # reports the downgrade at -v 1 rather than silently returning nothing.
    SUPPORTS_OPERATORS: bool = True

    # False when a proxy swap in the middle of fetch() would corrupt the run
    # rather than rescue it. Two shapes need this: multi-step flows whose token
    # is bound to the IP that obtained it (googlecse fetches cse_token on one
    # IP and spends it on the element/v1 call), and sources whose request has a
    # side effect that must not be replayed (intelx's POST opens a billable
    # server-side search job). Those still get a proxy - just one, for the
    # whole fetch, like the browser sources.
    ROTATE_MID_FETCH: bool = True

    def __init__(
        self,
        timeout: int = 30,
        rate_limit: int = 0,
        verbose: int = 0,
        proxy: str | None = None,
        user_agent: str = _DEFAULT_UA,
        pages: int = 2,
        filter_host: str | None = None,
        filter_strings: list[str] | None = None,
        filter_regex=None,
        extra_headers: dict | None = None,
        proxy_pool=None,
        progress=None,
    ) -> None:
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.verbose = verbose
        # Engine's own live progress bar (core/progress.py), shared by
        # reference across every source instance for the run. _vlog()/
        # _log_exc() clear it before printing - without this, a source's own
        # stdout print can land mid-line after the progress bar's last write
        # to stderr (which ends without a newline by design, so the next
        # render can overwrite it in place), splicing the two together on
        # screen. NullProgress() when unset (e.g. direct instantiation in
        # tests) makes .clear() a safe no-op.
        self._progress = progress if progress is not None else NullProgress()
        # A pool (core/proxy.py::ProxyPool) owned by Engine and shared across
        # every source instance - it has to be, because Engine builds a fresh
        # instance per (source, dork) pair, so rotation/ban state kept here
        # would die with each task. Resolving one proxy per instance at
        # construction is what gives per-task rotation for free: no source
        # module needs to know the pool exists.
        self._pool = proxy_pool
        # NOT resolved here on purpose. Engine evaluates _make_source() eagerly
        # inside a list comprehension, so every instance for the whole plan is
        # built before the first task runs. Acquiring in __init__ would mean
        # (a) round-robin degenerating - the plan is dork-major, so a given
        # source would land on the same proxy for every dork; (b) ban feedback
        # arriving too late to influence any assignment; and (c) pool
        # exhaustion raising at plan-build time, outside the run's error
        # handling. Resolution happens on first use instead: see _proxy().
        self.proxy = proxy
        self._proxy_resolved = proxy_pool is None
        self.user_agent = user_agent
        # How many result pages to walk. Every paging source clamps this to its
        # own ceiling - a free API tier or an anti-bot threshold is a harder
        # limit than anything the operator can ask for.
        self.pages = max(1, pages)
        # Set from --filter-host/--filter-string/--filter-regex: keeps only
        # results that pass every active filter, routing the rest to extras.
        # None/empty (the default) means "keep every result", which is the
        # honest default for dorking: a dork like `"target.com"
        # site:pastebin.com` is *supposed* to return third-party URLs, and
        # filtering them away would defeat the whole query.
        self.filter_host = (filter_host or '').lower().strip('.') or None
        self.filter_strings = [s.lower() for s in filter_strings] if filter_strings else None
        self.filter_regex = filter_regex
        # Set from --header/--header-file (gated by --header-source/
        # --header-profile): merged in last by _make_client(), after this
        # source's own headers(), so it can override anything - including the
        # User-Agent - regardless of casing (see _make_client()).
        self.extra_headers = extra_headers or None
        self.extras: dict[str, set] = {'urls_filtered': set()}
        # Set by _make_client() so a rotated client can be rebuilt with the
        # SAME custom headers the source asked for. Rebuilding without them
        # (browser_headers(...) in particular) would get blocked instantly.
        self._client_kwargs: dict | None = None
        self._rotated_client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _proxy(self) -> str | None:
        """The proxy for this task, drawn from the pool on first use.

        Lazy so that the draw happens when the task actually starts rather than
        when Engine builds the plan - see the note in __init__.
        """
        if not self._proxy_resolved:
            self.proxy = self._pool.acquire()
            self._proxy_resolved = True
        return self.proxy

    def _make_client(self, **kwargs) -> httpx.AsyncClient:
        """A pre-configured AsyncClient with proxy and User-Agent applied.

        Callers can override any default by passing kwargs; 'headers' are
        merged (caller values win) rather than replaced. Built as an
        httpx.Headers rather than a plain dict specifically so --header/
        --header-file (self.extra_headers, merged in last) can override a
        header regardless of casing - a plain dict.update() would let
        'User-Agent' and 'user-agent' coexist as two distinct entries and
        send both.
        """
        self._proxy()
        merged_headers = httpx.Headers({'User-Agent': self.user_agent})
        if 'headers' in kwargs:
            merged_headers.update(kwargs.pop('headers'))
        if self.extra_headers:
            merged_headers.update(self.extra_headers)
        client_kwargs: dict = {
            'timeout': self.timeout,
            'follow_redirects': True,
            'headers': merged_headers,
        }
        if self.proxy:
            client_kwargs['proxy'] = self.proxy
        client_kwargs.update(kwargs)
        # Remembered without the proxy so _rebuild_client() can swap in a new
        # one while keeping everything else the source configured.
        self._client_kwargs = {k: v for k, v in client_kwargs.items() if k != 'proxy'}
        return httpx.AsyncClient(**client_kwargs)

    def _rebuild_client(self, carry_cookies_from=None) -> httpx.AsyncClient:
        """An equivalent client on the current self.proxy.

        Reuses the kwargs captured in _make_client(), which is why the custom
        headers each source passes (browser_headers(...)) survive the swap -
        rebuilding without them would fall back to the tool's own User-Agent
        and get blocked on sight.

        Server-set cookies are carried over when possible: several sources
        accumulate them across pagination (google's consent, startpage,
        jusbrasil) and dropping them mid-run looks like a new session.
        """
        kwargs = dict(self._client_kwargs or {'timeout': self.timeout, 'follow_redirects': True})
        if self.proxy:
            kwargs['proxy'] = self.proxy
        client = httpx.AsyncClient(**kwargs)
        if carry_cookies_from is not None:
            try:
                client.cookies.update(carry_cookies_from.cookies)
            except Exception:
                pass
        return client

    async def _close_rotated(self) -> None:
        if self._rotated_client is not None:
            try:
                await self._rotated_client.aclose()
            except Exception:
                pass
            self._rotated_client = None

    async def aclose(self) -> None:
        """Release the rotated client, if any. Called by Engine._run_one."""
        await self._close_rotated()

    def _vlog(self, level: int, msg: str) -> None:
        if self.verbose >= level:
            self._progress.clear()
            print(colors.format_msg(f'[*] [{self.NAME}] {msg}'))

    def _log_exc(self, e: Exception) -> None:
        if self.verbose >= 4:
            self._progress.clear()
            print(colors.format_msg(f'[!] [{self.NAME}] {type(e).__name__}: {e}'))

    async def _get(self, client, url: str, **kwargs):
        """Wrap client.get(); enforces rate_limit, logs HTTP status and body preview."""
        if self._sem:
            async with self._sem:
                return await self._do_get(client, url, **kwargs)
        return await self._do_get(client, url, **kwargs)

    async def _post(self, client, url: str, **kwargs):
        """POST counterpart of _get().

        Exists because _get() is GET-only, so any source POSTing directly on the
        client escaped both the --rate-limit semaphore and (now) proxy rotation.
        duckduckgo and intelx were doing exactly that.
        """
        if self._sem:
            async with self._sem:
                return await self._do_post(client, url, **kwargs)
        return await self._do_post(client, url, **kwargs)

    async def _do_get(self, client, url: str, **kwargs):
        return await self._request('GET', client, url, **kwargs)

    async def _do_post(self, client, url: str, **kwargs):
        return await self._request('POST', client, url, **kwargs)

    async def _issue(self, method: str, client, url: str, **kwargs):
        resp = await (
            client.post(url, **kwargs) if method == 'POST' else client.get(url, **kwargs)
        )
        if self.verbose >= 2:
            self._vlog(2, f'HTTP {resp.status_code}')
        if self.verbose >= 3:
            preview = resp.text[:400].replace('\n', ' ')
            self._vlog(3, preview)
        return resp

    async def _request(self, method: str, client, url: str, **kwargs):
        """Issue one request, rotating the proxy if a trigger fires.

        The client arrives as a PARAMETER (the source owns it in an `async
        with`), so this method is free to substitute a rotated one without the
        caller ever knowing - which is why none of the source modules needed
        changing, including the ones that pass their client down into helpers
        (googlecse._search_with, searx._search_instance).
        """
        pool = self._pool
        if pool is None:
            return await self._issue(method, client, url, **kwargs)

        if not self.ROTATE_MID_FETCH:
            # One proxy for the whole fetch: rotating here would break an
            # IP-bound token or replay a side-effecting request. Failures still
            # count toward --proxy-ban-after so the proxy leaves the pool for
            # the tasks that follow.
            try:
                resp = await self._issue(method, client, url, **kwargs)
            except httpx.HTTPError:
                # Still counts against the proxy even though this source
                # cannot retry on a new one.
                pool.report_failure(self.proxy)
                raise
            body = resp.text if pool.wants_body() else None
            if pool.should_rotate(resp.status_code, body):
                if pool.report_failure(self.proxy):
                    self._vlog(1, f'proxy {_mask(self.proxy)} banned after repeated failures')
                self._vlog(
                    1,
                    f'HTTP {resp.status_code} would rotate, but {self.NAME} pins one '
                    'proxy per fetch (IP-bound token or non-replayable request)',
                )
            return resp

        attempts = max(1, pool.retries + 1)
        resp = None
        for attempt in range(attempts):
            if pool.rotate == 'random':
                # True per-request rotation: a fresh proxy needs a fresh client,
                # since httpx pins the proxy at construction. Costs the
                # connection pool - documented, and opt-in via --proxy-rotate.
                self.proxy = pool.acquire()
                await self._close_rotated()
                self._rotated_client = self._rebuild_client()

            active = self._rotated_client or client
            pool.note_request()

            # A dead proxy raises here instead of answering, so transport
            # errors have to count as a rotation trigger in their own right -
            # otherwise the single most common failure (proxy simply down)
            # would never reach report_failure and never get banned.
            reason: str
            try:
                resp = await self._issue(method, active, url, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == attempts - 1:
                    pool.report_failure(self.proxy)
                    raise
                reason = type(exc).__name__
            else:
                # Only decode the body when --proxy-rotate-body is armed:
                # result pages here run 350-450KB and this would otherwise be
                # paid per request for nothing.
                body = resp.text if pool.wants_body() else None
                if not pool.should_rotate(resp.status_code, body):
                    pool.report_success(self.proxy)
                    return resp
                if attempt == attempts - 1:
                    # Out of retries - hand back the last response rather than
                    # inventing a failure; the source decides what to do.
                    self._vlog(1, f'proxy retries exhausted (HTTP {resp.status_code})')
                    return resp
                reason = f'HTTP {resp.status_code}'

            previous = self.proxy
            if pool.report_failure(previous):
                self._vlog(1, f'proxy {_mask(previous)} banned after repeated failures')
            self.proxy = pool.rotate_now(previous)
            self._vlog(
                1,
                f'rotating proxy after {reason}: '
                f'{_mask(previous)} -> {_mask(self.proxy)}',
            )
            previous_client = self._rotated_client or client
            await self._close_rotated()
            self._rotated_client = self._rebuild_client(carry_cookies_from=previous_client)
        return resp

    # ------------------------------------------------------------------
    # Browser-source helpers
    # ------------------------------------------------------------------

    def browser_proxy(self) -> dict | None:
        """Playwright's proxy dict for this task, or None to launch direct.

        Two things happen here that a bare `{'server': self.proxy}` got wrong:

        * the proxy is drawn from the pool lazily, like the httpx path;
        * credentials are split into separate 'username'/'password' keys.
          Chromium **ignores userinfo embedded in `server`**, so an
          authenticated proxy - what commercial rotating pools hand out - used
          to 407 here while the httpx sources, which do accept inline
          credentials, worked fine.

        Playwright pins the proxy at browser launch, so these sources get one
        proxy per fetch() and cannot rotate mid-run. That is not merely a cost
        question: `so`'s psid and `mojeek`'s chv are bound to the IP that
        obtained them, so swapping mid-fetch would corrupt results rather than
        just slow them down. They report blocks via report_block() instead, so
        --proxy-ban-after still retires a burned proxy for later tasks.
        """
        from core.proxy import playwright_proxy

        proxy = self._proxy()
        if not proxy:
            return None
        self._vlog(
            1,
            f'proxy {_mask(proxy)} (fixed for this browser session - '
            'status/body triggers do not rotate it)',
        )
        if proxy.lower().startswith('socks') and '@' in proxy:
            self._vlog(
                1,
                'note: Chromium does not support SOCKS authentication - '
                'this proxy will likely be refused',
            )
        return playwright_proxy(proxy)

    def report_block(self) -> None:
        """Tell the pool this proxy looks blocked.

        The browser sources cannot rescue the current fetch, but they *can*
        recognise a block (dogpile reads resp.status, ecosia checks the "Just a
        moment..." title, mojeek handles 403 explicitly). Reporting it makes
        --proxy-ban-after work for them too: the burned proxy leaves the pool
        for subsequent tasks.
        """
        if self._pool is not None and self._pool.report_failure(self.proxy):
            self._vlog(1, f'proxy {_mask(self.proxy)} banned after repeated blocks')

    # Semaphore capping concurrent requests per source (0 = unlimited).
    # Built lazily so it binds to the running loop rather than import time.
    @property
    def _sem(self) -> asyncio.Semaphore | None:
        if self.rate_limit <= 0:
            return None
        if getattr(self, '_sem_obj', None) is None:
            self._sem_obj = asyncio.Semaphore(self.rate_limit)
        return self._sem_obj

    # ------------------------------------------------------------------
    # Query / result plumbing
    # ------------------------------------------------------------------

    def query_for(self, dork: Dork) -> str:
        """The string this source should actually send for *dork*."""
        if self.SUPPORTS_OPERATORS or not dork.has_operators():
            return dork.query
        plain = dork.plain_terms()
        self._vlog(1, f'operators not supported here - querying {plain!r}')
        return plain

    @abstractmethod
    async def fetch(self, dork: Dork) -> set[str]:
        """Run *dork* against this index and return the URLs found.

        Must never raise: a blocked or broken source contributes nothing and
        the rest of the run carries on.
        """

    def _passes_filters(self, candidate: str, host: str) -> bool:
        """AND across active filter types; OR within --filter-string's list."""
        if self.filter_host and not (
            host == self.filter_host or host.endswith(f'.{self.filter_host}')
        ):
            return False
        if self.filter_strings:
            low = candidate.lower()
            if not any(s in low for s in self.filter_strings):
                return False
        if self.filter_regex and not self.filter_regex.search(candidate):
            return False
        return True

    def _filter_urls(self, urls: set[str]) -> set[str]:
        """Normalize, drop source chrome, and apply --filter-* when set.

        Unlike the host-anchored SimpleRecon tools, the default here keeps
        every result: a dork's answer is whatever the index returned, on any
        domain. An active --filter-* narrows it, and anything it rejects is
        preserved under extras['urls_filtered'] rather than dropped.
        """
        from sources._search_common import is_source_chrome

        has_filters = bool(self.filter_host or self.filter_strings or self.filter_regex)

        result: set[str] = set()
        for u in urls:
            if not u or len(result) >= _MAX_URLS_PER_SOURCE:
                continue
            candidate = u.strip()
            if not candidate:
                continue
            if '://' not in candidate:
                candidate = f'http://{candidate}'
            try:
                host = (urlparse(candidate).hostname or '').lower().rstrip('.')
            except Exception:
                continue
            if not host:
                continue
            if is_source_chrome(host, keep_host=self.filter_host):
                continue
            if has_filters:
                if self._passes_filters(candidate, host):
                    result.add(candidate)
                elif len(self.extras['urls_filtered']) < _MAX_URLS_PER_SOURCE:
                    self.extras['urls_filtered'].add(candidate)
                continue
            result.add(candidate)
        return result
