"""
So.com (360 Search / Haosou) - Qihoo 360's search engine, previously known as
so.360.cn and haosou.com.

Requires a real browser for two independent reasons, confirmed live (2026-08):
  1. The result list is client-rendered - a plain HTTP GET returns a 200 shell
     with zero real result links (same failure mode as Swisscows).
  2. **The visible `href` on every result is a `so.com/link?m=<opaque token>`
     redirect wrapper, not the destination.** The real target lives in the
     `data-mdurl="..."` attribute on the same `<a>` - confirmed by inspecting
     the rendered DOM (`<a href="https://www.so.com/link?m=..." data-mdurl=
     "http://gov.br/" ...>`). Extracting `href` the way every other engine in
     this catalog does would return nothing but tracking links; this is the
     one engine that scrapes `data-mdurl` instead.

Pagination follows the operator's own guidance: **click the actual "next
page" control (`#snext`) rather than constructing the paginated URL by
hand.** Each page's URL carries a `psid` (search session id) and other
tokens generated server-side for that specific search session - a URL typed
by hand with a guessed or reused `psid` is not guaranteed to behave like the
real click, so this drives the click through Playwright like a user would,
confirmed live to correctly advance `pn=2`, `pn=3`, ... with a fresh, valid
`psid` each time.

The page is heavy (~350KB, many related-search/CDN widgets) and its `load`
event sometimes never fires within a normal timeout even though the DOM
finished rendering long before - waiting on `domcontentloaded` instead
(confirmed reliable across repeated runs; `load` was not) is what the
extraction actually needs anyway, since it only reads markup, not assets.

Requires the optional `playwright` package plus its browser binary:
    pip install -r requirements-browser.txt
    playwright install chromium
Without it the engine self-disables with a single message instead of failing.
"""
import html
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua

_QUERY_URL = 'https://www.so.com/s?src=home_so.com&q={q}'
_SETTLE_MS = 2000
_MDURL_RE = re.compile(r'data-mdurl="([^"]+)"')

_INSTALL_HINT = (
    'playwright not installed - run: '
    'pip install -r requirements-browser.txt && playwright install chromium'
)


def _extract(content: str) -> set[str]:
    return {html.unescape(u) for u in _MDURL_RE.findall(content) if u.startswith('http')}


class So(BaseSource):
    NAME = 'so'
    DESCRIPTION = (
        'So.com (360 Search) - headless-browser render, paginates via the '
        'real "next page" control (needs requirements-browser.txt)'
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

                    await page.goto(
                        _QUERY_URL.format(q=q), wait_until='domcontentloaded', timeout=self.timeout * 1000
                    )
                    await page.wait_for_timeout(_SETTLE_MS)
                    urls |= _extract(await page.content())
                    self._vlog(1, f'pn=1: {len(urls)} url(s)')

                    for page_no in range(2, self.pages + 1):
                        try:
                            await page.click('#snext', timeout=5000)
                            await page.wait_for_load_state('domcontentloaded', timeout=self.timeout * 1000)
                        except Exception:
                            # No "next page" control - fewer results than
                            # requested pages, not an error.
                            break
                        await page.wait_for_timeout(_SETTLE_MS)
                        found = _extract(await page.content())
                        new_found = found - urls
                        if not new_found:
                            break
                        urls |= new_found
                        self._vlog(1, f'pn={page_no}: {len(new_found)} url(s)')
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)

        if not urls:
            self.report_block()
            self._vlog(1, 'no results')
        return self._filter_urls(urls)
