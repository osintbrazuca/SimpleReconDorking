"""
Swisscows - Swiss privacy-focused search engine, own index.

Unlike Mojeek/Ecosia, Swisscows has no interactive or behavioral challenge to
pass - it's simply a client-rendered SPA. A plain HTTP GET always returns a
200 with the page shell and zero organic links (confirmed live: only social/
CDN chrome - flocdn.com, teleguard.com - show up in the static HTML), because
the actual result list is built by client-side JS after load. Rendering it in
a real (headless) browser is the whole fix; no click, checkbox or wait-out-a-
challenge step is needed the way Mojeek/Ecosia require.

Verified live (2026-08) via the Portuguese-locale endpoint: `site:` narrows
results correctly (10 of 12 non-chrome links were on-domain for a
`site:wikipedia.org` query), and `offset=10`/`offset=20` paginate for real
(10 new links per page, confirmed by diffing against the previous page).

Requires the optional `playwright` package plus its browser binary:
    pip install -r requirements-browser.txt
    playwright install chromium
Without it the engine self-disables with a single message instead of failing.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua

_QUERY_URL = 'https://swisscows.com/pt/web?query={q}'
_PAGE_URL = 'https://swisscows.com/pt/web?query={q}&offset={offset}'
_PAGE_SIZE = 10
_SETTLE_MS = 2500
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')

_INSTALL_HINT = (
    'playwright not installed - run: '
    'pip install -r requirements-browser.txt && playwright install chromium'
)


class Swisscows(BaseSource):
    NAME = 'swisscows'
    DESCRIPTION = (
        'Swisscows - Swiss privacy-focused index, headless-browser render '
        '(needs requirements-browser.txt; JS-rendered SPA, no challenge to solve)'
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
                        _QUERY_URL.format(q=q), wait_until='load', timeout=self.timeout * 1000
                    )
                    await page.wait_for_timeout(_SETTLE_MS)
                    urls |= set(_HREF_RE.findall(await page.content()))
                    self._vlog(1, f'offset=0: {len(urls)} url(s)')

                    for i in range(1, self.pages):
                        offset = i * _PAGE_SIZE
                        try:
                            await page.goto(
                                _PAGE_URL.format(q=q, offset=offset),
                                wait_until='load',
                                timeout=self.timeout * 1000,
                            )
                        except Exception as e:
                            self._log_exc(e)
                            break
                        await page.wait_for_timeout(_SETTLE_MS)
                        found = set(_HREF_RE.findall(await page.content()))
                        new_found = found - urls
                        if not new_found:
                            break
                        urls |= new_found
                        self._vlog(1, f'offset={offset}: {len(new_found)} url(s)')
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)

        if not urls:
            self.report_block()
            self._vlog(1, 'no results')
        return self._filter_urls(urls)
