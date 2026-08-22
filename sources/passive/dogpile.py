"""
Dogpile - metasearch engine (Infospace/System1 family), aggregates results
from other engines.

Needs a real browser: a plain HTTP GET is blocked outright (confirmed live,
403 regardless of headers) while Playwright rendering passes cleanly (HTTP
202, real results) - the same category of block as Mojeek/Ecosia/Swisscows/
So.com, just resolved by JS execution rather than a challenge.

Best-effort like `mojeek`, not reliable like `swisscows`/`so`: this sits
behind a CloudFront WAF, and a handful of requests from the same IP in a
short window (ordinary local testing is enough) gets a flat HTTP 403 -
"ERROR: The request could not be satisfied" - even for a plain-text query
that worked moments earlier. No checkbox or interstitial to solve, no
recovery available; it just needs the IP's reputation to cool down or a
`--proxy` from elsewhere.

**Dork operators actively trigger a CloudFront WAF block here, not just a
no-op.** Confirmed live: `q=site:wikipedia.org`, `q=filetype:pdf+brasil` and
`q=inurl:admin` all get a hard 403 "The request could not be satisfied" from
CloudFront, while an arbitrary colon in an unrelated term (`test:test`)
passes fine - this is a signature match on known dork/scanner operator
keywords, not a punctuation filter. `SUPPORTS_OPERATORS = False` routes every
dork through `Dork.plain_terms()` before it ever reaches the request, which
is not just "better recall" here the way it is for Marginalia/GitHub - it's
the difference between getting results and getting blocked outright.

Pagination follows the operator-supplied scheme: page 1 is the bare query
(`origin=funnel_home_website` on the seed request), pages 2+ add `&page=2`,
`&page=3`, ... Confirmed live: page 2 returned 10 links not present on page 1.

Requires the optional `playwright` package plus its browser binary:
    pip install -r requirements-browser.txt
    playwright install chromium
Without it the engine self-disables with a single message instead of failing.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua

_QUERY_URL = 'https://www.dogpile.com/search?q={q}&origin=funnel_home_website'
_PAGE_URL = 'https://www.dogpile.com/search?q={q}&page={page}'
_SETTLE_MS = 2500
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')

_INSTALL_HINT = (
    'playwright not installed - run: '
    'pip install -r requirements-browser.txt && playwright install chromium'
)


class Dogpile(BaseSource):
    NAME = 'dogpile'
    DESCRIPTION = (
        'Dogpile - metasearch (Infospace/System1), headless-browser render '
        '(needs requirements-browser.txt; free-text only; best-effort: IP gets rate-limited fast)'
    )
    CATEGORY = 'web'
    SUPPORTS_OPERATORS = False

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
                        _QUERY_URL.format(q=q), wait_until='domcontentloaded',
                        timeout=self.timeout * 1000,
                    )
                    await page.wait_for_timeout(_SETTLE_MS)
                    urls |= set(_HREF_RE.findall(await page.content()))
                    self._vlog(1, f'page=1: {len(urls)} url(s)')

                    for page_no in range(2, self.pages + 1):
                        try:
                            await page.goto(
                                _PAGE_URL.format(q=q, page=page_no),
                                wait_until='domcontentloaded',
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
                        self._vlog(1, f'page={page_no}: {len(new_found)} url(s)')
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)

        if not urls:
            self.report_block()
            self._vlog(1, 'no results')
        return self._filter_urls(urls)
