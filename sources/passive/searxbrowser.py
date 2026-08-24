"""
SearXNG through a real browser - the instances httpx cannot reach.

Same federated metasearch as `searx`, same instance list, but rendered in
headless Chromium so the JavaScript anti-bot gates can actually run. That is
the entire reason this module exists, and it was measured:

    instance                      via httpx (`searx`)     via this module
    ----------------------------  ----------------------  ------------------
    searxng.canine.tools          Anubis PoW, 0 results   passed in ~9s, results

Roughly 90% of the public pool answers httpx with a challenge (Anubis
proof-of-work, the Cap widget) or with its own home page. Those instances are
not broken - they simply require a JS runtime, which is precisely what a
browser source provides. `searx` remains the cheap path for instances that
answer plain HTTP; this is the expensive path for the rest.

>>> THE STEALTH PATCHES ARE LOAD-BEARING, NOT DECORATION. <<<
Verified live: plain headless Chromium (no patches) sat on "Checking if
wolf..." for 18s without passing, and one instance served Anubis's own
failure page, "Oh noes!" - i.e. the challenge actively detected automation
and rejected it. With `navigator.webdriver` masked, plugins/languages
spoofed and `--disable-blink-features=AutomationControlled`, the same
instance cleared in ~9 seconds. Remove the init script and this source
silently stops finding anything.

>>> THIS RUNS EVERY INSTANCE IN THE LIST, WHICH IS SLOW ON PURPOSE. <<<
Unlike `searx` (which shuffles and stops after a few healthy instances),
this one visits the whole pool and merges everything, because the operator
asked for maximum coverage and because a browser only pays off when it is
used on the instances httpx already failed on. With ~72 instances at roughly
9-15s each, a strictly sequential run would take 15+ minutes per dork, so
pages are opened `_CONCURRENCY` at a time. That is safe here in a way it is
not for a single-host source: the burst is spread across *different* hosts,
so no one instance sees more than its own share.

Completion is detected by SearXNG's own view stamp (`content="results"`),
never by a fixed sleep: challenge solve times vary by instance and by how
much CPU the PoW needs.

>>> SCROLLING WAS MEASURED AND REJECTED - DO NOT ADD IT. <<<
Scrolling to the bottom five times changed the result count by exactly zero
(413 links before and after, with and without an `infinite_scroll` cookie).
Three reasons, and the third is the one that settles it: the `simple` theme
ships a next-page *control*, not a scroll observer, so scrolling fires no
request at all; `&infinite_scroll=1` is not a URL parameter and is ignored;
and even switched on, SearXNG's infinite scroll is UI sugar over the very
same `pageno=N` endpoint this module already walks, so it cannot exceed what
--pages already retrieves. Clicking the real next-page button was also
compared against `goto(pageno=N)` and finished level (591 vs 597 URLs over
three pages). --pages is the knob; scrolling would be dead code.

`_CONCURRENCY` trades throughput against solve rate: the proof-of-work
competes for CPU, and an instance that solves in ~9s on its own can miss its
budget inside a concurrent batch. Lower it to favour coverage over speed.

>>> THE ENGINE ROSTER IS SHARED WITH `searx`, AND IT PAYS OFF BIGGER HERE. <<<
Both modules send the same `enabled_engines` preference, over the same two
channels, from the same `engines` list in config/searx.json (and walk the same
`instances` list in that file); only the transport differs - Playwright context
cookies + query string here, httpx jar + params there. See
sources/passive/searx.py::engine_prefs() for the mechanism.

Measured live (2026-08) on a full 72-instance walk, `site:gov.br filetype:pdf`,
--pages 1, roster off -> on:

    instances answering      35/72  ->   37/72
    unique urls                276  ->    689

The multiplier lands harder here than on `searx` for a structural reason: this
module walks the WHOLE pool and 35-37 instances clear their gates, whereas the
httpx path stops at _WANT_OK and typically gets one instance past them. Engine
expansion multiplies per instance, so it compounds with the instance count.

The obvious risk did NOT materialise, and the number above is the check: a
bigger roster means the instance spends longer querying upstreams before it
renders, and `_await_results` polls for the rendered results view, so that wait
comes out of the SAME budget as the anti-bot challenge
(_FIRST_SOLVE_TIMEOUT_S / _SOLVE_TIMEOUT_S). It could therefore have bought
breadth by timing instances out. Instead the answered count went slightly UP
(35 -> 37, i.e. inside run-to-run noise), so the budgets absorb it. Re-check
that count - not just the URL total - if the roster is ever extended much
further; a rising URL total with a falling instance count is a coverage
regression wearing a win's clothing, and raising the budgets is the fix.
"""
import asyncio
import html
import re
from urllib.parse import urlencode

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua
from sources.passive.searx import (
    _CATEGORIES, _DATA_FILE, _RESULT_RE, _CHALLENGE_MARKERS,
    engine_prefs, load_instances,
)

# SearXNG stamps the view that rendered the page; this is the only reliable
# "the query actually ran" signal (see sources/passive/searx.py).
_ENDPOINT_RESULTS = 'name="endpoint" content="results"'

_CONCURRENCY = 4
_NAV_TIMEOUT_MS = 45_000
_POLL_S = 3

# Two budgets, because the first page of an instance and the ones after it are
# not the same problem. Measured on an Anubis instance: page 1 had not cleared
# after 45s, while pages 2 and 3 came back in 18.1s and 8.8s - the expensive
# part is the initial proof-of-work, after which the `techaro.lol-anubis-auth`
# cookie rides along in the context and later navigations sail through. A
# single 40s budget therefore threw away instances that were seconds from
# solving.
_FIRST_SOLVE_TIMEOUT_S = 90
_SOLVE_TIMEOUT_S = 30

# Masks the automation tells Anubis checks. Verified: without this the
# challenge either never clears or returns Anubis's "Oh noes!" reject page.
_STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
window.chrome = {runtime: {}};
"""


class Searxbrowser(BaseSource):
    NAME = 'searxbrowser'
    DESCRIPTION = 'SearXNG in headless Chromium - solves the JS anti-bot gates (slow, needs Playwright)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            # Deferred on purpose: a module-level import would make the
            # registry drop this source with a traceback-shaped message
            # instead of one actionable line.
            self._vlog(
                1,
                'needs Playwright: pip install -r requirements-browser.txt '
                '&& playwright install chromium',
            )
            return set()

        instances = load_instances()
        if not instances:
            self._vlog(
                1, f'no instances - "instances" in config/{_DATA_FILE} missing or empty'
            )
            return set()

        q = self.query_for(dork)
        urls: set[str] = set()
        healthy = 0

        # Same engine roster as `searx`, same two channels (cookie + query
        # string) - see sources/passive/searx.py::engine_prefs(). Rendered once
        # here rather than per instance: the roster is identical for all of
        # them, and _visit() runs 72 times.
        prefs = engine_prefs()
        engine_qs = urlencode(prefs.params) if prefs else ''
        if prefs is None:
            self._vlog(
                1,
                f'no engine expansion - "engines" in config/{_DATA_FILE} missing or '
                'empty; instances will search their own default engine set',
            )
        try:
            async with async_playwright() as pw:
                launch_kwargs: dict = {
                    'headless': True,
                    'args': ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
                }
                pw_proxy = self.browser_proxy()
                if pw_proxy:
                    launch_kwargs['proxy'] = pw_proxy
                browser = await pw.chromium.launch(**launch_kwargs)
                try:
                    context = await browser.new_context(
                        user_agent=effective_ua(self.user_agent),
                        extra_http_headers=(self.extra_headers or {}),
                        viewport={'width': 1366, 'height': 768},
                        locale='en-US',
                    )
                    await context.add_init_script(_STEALTH)

                    if prefs:
                        # One cookie pair per instance, because Playwright
                        # scopes cookies by origin - there is no "send this to
                        # every host" jar the way httpx has. A failure here is
                        # deliberately not fatal: the query string carries the
                        # identical preference, which is the whole point of
                        # sending it over both channels.
                        try:
                            await context.add_cookies([
                                {'name': name, 'value': value, 'url': base}
                                for base in instances
                                for name, value in prefs.cookies.items()
                            ])
                        except Exception as e:
                            self._log_exc(e)
                            self._vlog(
                                1,
                                'cookie channel unavailable - the engine roster '
                                'rides the query string only',
                            )

                    gate = asyncio.Semaphore(_CONCURRENCY)

                    # Declared so the progress BAR can move inside this
                    # single (source, dork) task: runs stays 0/1 for the whole
                    # walk, so without this the bar sits at 0% for minutes.
                    self._progress.declare_units(len(instances))

                    async def one(base: str) -> set[str]:
                        async with gate:
                            try:
                                found = await self._visit(context, base, q, engine_qs)
                            finally:
                                self._progress.note_unit()
                            # Per instance, for the same reason the unit tick
                            # above exists: this is ONE task, so the URL counter
                            # on the progress line cannot move until the whole
                            # 72-instance walk is over. Outside the finally -
                            # there is nothing to report when _visit() raised.
                            self._progress.note_urls(found)
                            return found

                    for found in await asyncio.gather(
                        *(one(b) for b in instances), return_exceptions=True
                    ):
                        if isinstance(found, BaseException):
                            continue
                        if found:
                            healthy += 1
                            urls |= found
                    self._vlog(
                        1,
                        f'{healthy}/{len(instances)} instance(s) answered, {len(urls)} url(s)',
                    )
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)

    async def _visit(self, context, base: str, q: str, engine_qs: str = '') -> set[str]:
        """Render every requested page of one instance."""
        found: set[str] = set()
        page = await context.new_page()
        try:
            for pageno in range(1, self.pages + 1):
                url = (
                    f'{base}/search?q={q}&pageno={pageno}&categories={_CATEGORIES}'
                    '&language=auto&time_range=&safesearch=0&theme=simple'
                )
                if engine_qs:
                    url += f'&{engine_qs}'
                self._progress.note_request(url)
                try:
                    await page.goto(url, wait_until='domcontentloaded',
                                    timeout=_NAV_TIMEOUT_MS)
                except Exception as e:
                    self._log_exc(e)
                    break
                budget = _FIRST_SOLVE_TIMEOUT_S if pageno == 1 else _SOLVE_TIMEOUT_S
                body = await self._await_results(page, base, budget)
                if body is None:
                    # A gate that did not open in time is NOT a reason to drop
                    # the instance: the attempt itself banks the Anubis auth
                    # cookie, and measurement showed pages 2 and 3 then loading
                    # in 18s and 9s after page 1 had timed out. Only stop once
                    # every requested page has been tried.
                    continue
                hits = {html.unescape(u) for u in _RESULT_RE.findall(body)}
                if not hits:
                    break  # genuinely out of results, unlike a blocked gate
                found |= hits
                self._vlog(2, f'{base} page={pageno}: {len(hits)} url(s)')
        finally:
            try:
                await page.close()
            except Exception:
                pass
        return found

    async def _await_results(self, page, base: str, budget: float) -> str | None:
        """Poll until the results view renders, or give up on this instance.

        Returns the page HTML, or None when the instance never got past its
        gate - polling rather than sleeping a fixed amount because solve time
        varies with the instance's PoW difficulty.

        >>> A FAILING page.content() HERE MEANS PROGRESS, NOT FAILURE. <<<
        Anubis *navigates* the moment its proof-of-work completes, and calling
        content() mid-navigation raises "Unable to retrieve content because the
        page is navigating and changing the content". Treating that as fatal
        (the previous behaviour) discarded the instance at the exact moment it
        was passing the challenge - the closer to solving, the likelier the
        abort. So it is retried inside the budget instead.
        """
        waited = 0.0
        body = ''
        while True:
            try:
                body = await page.content()
            except Exception as e:
                # Almost certainly the mid-navigation race above. Only worth
                # reporting once the budget is gone, which the check below does.
                if waited >= budget:
                    self._log_exc(e)
                    return None
                await asyncio.sleep(_POLL_S)
                waited += _POLL_S
                continue
            if _ENDPOINT_RESULTS in body:
                return body
            if waited >= budget:
                low = body[:4000].lower()
                why = ('challenge not solved'
                       if any(m in low for m in _CHALLENGE_MARKERS)
                       else 'no results view')
                self._vlog(2, f'{base}: {why}')
                return None
            await asyncio.sleep(_POLL_S)
            waited += _POLL_S
