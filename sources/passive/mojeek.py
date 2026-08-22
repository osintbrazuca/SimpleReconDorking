"""
Mojeek - own crawler/index (not a Google/Bing proxy), gated behind an ALTCHA
proof-of-work checkbox challenge that a plain HTTP client can't solve -
confirmed live (2026-08): a static GET always returns a "Captcha" shell page
with zero result links, regardless of headers. This is the only engine in the
catalog that needs a real browser, so it is the one exception to "every
engine is an httpx-based BaseSource subclass."

Bypass flow (reverse-engineered by driving a real headless Chromium):
  1. Load the query URL. Mojeek renders an ALTCHA widget
     (`<input type="checkbox" id="altcha-checkbox-...">`).
  2. Click `.altcha-checkbox` with `force=True` - its own checkmark SVG
     overlaps the input and intercepts plain pointer events otherwise.
  3. Wait for `.altcha[data-state="verified"]`: the widget's own JS solves an
     ALTCHA proof-of-work challenge client-side, then (usually) auto-navigates
     to the same query with `&chv=<token>` appended, which is the real
     results page. This auto-navigation is flaky in practice - verified
     live that the widget can reach data-state=verified without the page's
     own redirect listener firing, for no visible reason - so step 3 is
     retried a few times on a fresh page load rather than trusted first-try.
  4. The `chv` token is reusable for the rest of the run: subsequent pages
     load directly at `&s={offset}&chv={same token}` with no further
     challenge (verified: page 2 returned 10 new results with zero captcha
     interaction). One challenge solve per fetch() call, not per page.

Best-effort: a heavily-automated IP eventually gets a flat HTTP 403 instead of
the ALTCHA page (verified live), same failure category as `google`/`bing`/
`yandex`/`baidu` elsewhere in this catalog - no checkbox will ever appear on
that response, so `_solve_challenge` checks the status and bails immediately
instead of burning three rounds of click timeouts finding out.

Requires the optional `playwright` package plus its browser binary:
    pip install -r requirements-browser.txt
    playwright install chromium
Without it the engine self-disables with a single message instead of failing.
"""
import re
from urllib.parse import quote_plus, urlparse, parse_qs

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua

_QUERY_URL = 'https://www.mojeek.com/search?q={q}'
_PAGE_URL = 'https://www.mojeek.com/search?q={q}&s={offset}'
_PAGE_SIZE = 10
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


async def _safe_content(page) -> str:
    """page.content() while a client-side redirect is still landing raises
    'page is navigating and changing the content' - retry briefly instead of
    letting one transient race drop an entire page of results.
    """
    for attempt in range(4):
        try:
            return await page.content()
        except Exception:
            if attempt == 3:
                raise
            await page.wait_for_timeout(500)
    return ''


_INSTALL_HINT = (
    'playwright not installed - run: '
    'pip install -r requirements-browser.txt && playwright install chromium'
)

_SOLVE_ATTEMPTS = 3


async def _solve_challenge(page, query_url: str, timeout_ms: int) -> str | None:
    """Load *query_url* and try to pass the ALTCHA checkbox. Returns the
    `chv` token on success, None if every attempt left the page unsolved.

    Each attempt is a fresh page load: reusing the same failed challenge
    state has no reason to succeed on a second try.
    """
    for attempt in range(_SOLVE_ATTEMPTS):
        try:
            resp = await page.goto(query_url, wait_until='networkidle', timeout=timeout_ms)
            if resp is not None and resp.status == 403:
                # A hard IP-level block, not the ALTCHA challenge - no
                # checkbox will ever appear here, so don't burn the click
                # timeout finding out. Retrying immediately doesn't help
                # either; only a different IP/network does.
                return None
            await page.click('.altcha-checkbox', force=True, timeout=5000)
            await page.wait_for_function(
                "document.querySelector('.altcha')"
                "?.getAttribute('data-state') === 'verified'",
                timeout=15000,
            )
            await page.wait_for_url('**chv=**', timeout=8000)
            await page.wait_for_load_state('load')
            await page.wait_for_timeout(500)
            chv = parse_qs(urlparse(page.url).query).get('chv', [None])[0]
            if chv:
                return chv
        except Exception:
            pass  # no checkbox this time, verify timeout, or redirect never fired
    return None


class Mojeek(BaseSource):
    NAME = 'mojeek'
    DESCRIPTION = (
        'Mojeek - own crawler/index, headless-browser ALTCHA bypass '
        '(needs requirements-browser.txt; best-effort: IP can get hard-blocked)'
    )
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self._vlog(1, _INSTALL_HINT)
            return set()

        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()

        try:
            async with async_playwright() as pw:
                launch_kwargs: dict = {'headless': True}
                # browser_proxy() draws from the pool (lazily) and splits out
                # credentials: Chromium ignores userinfo inside 'server', so
                # {'server': 'http://u:p@host'} silently 407s.
                pw_proxy = self.browser_proxy()
                if pw_proxy:
                    launch_kwargs['proxy'] = pw_proxy
                browser = await pw.chromium.launch(**launch_kwargs)
                try:
                    context = await browser.new_context(
                        user_agent=effective_ua(self.user_agent),
                        extra_http_headers=(self.extra_headers or {}),
                    )
                    page = await context.new_page()

                    chv = await _solve_challenge(
                        page, _QUERY_URL.format(q=q), self.timeout * 1000
                    )
                    urls |= set(_HREF_RE.findall(await _safe_content(page)))
                    self._vlog(
                        1,
                        f's=1: {len(urls)} url(s)'
                        + ('' if chv else ' (no chv - challenge not solved)'),
                    )

                    for i in range(1, self.pages):
                        offset = 1 + i * _PAGE_SIZE
                        url = _PAGE_URL.format(q=q, offset=offset)
                        if chv:
                            url += f'&chv={chv}'
                        try:
                            await page.goto(url, wait_until='load', timeout=self.timeout * 1000)
                        except Exception as e:
                            self._log_exc(e)
                            break
                        found = set(_HREF_RE.findall(await _safe_content(page)))
                        new_found = found - urls
                        if not new_found:
                            break  # likely bounced back to the captcha shell
                        urls |= new_found
                        self._vlog(1, f's={offset}: {len(new_found)} url(s)')
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)

        if not urls:
            self.report_block()
            self._vlog(1, 'no results - blocked outright (403) or the ALTCHA challenge was not solved in time')
        return self._filter_urls(urls)
