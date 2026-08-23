"""
Ecosia - own/joint (Qwant partnership) index, gated behind a Cloudflare
Turnstile challenge ("Confirm you're not a robot") that behaves very
differently from Mojeek's ALTCHA checkbox: it's a managed/invisible
challenge scored on browser-automation signals (headless fingerprint, IP
reputation, session history), not a client-side puzzle with a checkbox to
click. Confirmed live: from this project's development network, headless
Chromium sits on "Just a moment..." indefinitely - 18s of passive waiting,
clicking inside the Turnstile iframe, and standard `navigator.webdriver`/
plugin stealth patches all failed to pass it. From a real desktop browser
(residential IP, genuine session) the same challenge resolves automatically
with no click at all, per direct operator report - so this is an
environment-dependent pass/fail in a way Mojeek's ALTCHA is not, and the
result here leans more heavily on IP reputation and `--proxy` than any other
best-effort engine in this catalog.

Flow: load the query URL, poll for the "Just a moment..." interstitial to
clear (title change) for up to `_CHALLENGE_TIMEOUT_MS`. If a Turnstile
checkbox happens to render (some risk tiers show one instead of resolving
invisibly), it's clicked opportunistically as a fallback - but the primary
path is simply waiting the managed challenge out, matching what a real
browser session does.

Pagination follows the operator-supplied scheme: page 1 is the bare query
(`method=index`), pages 2+ add `&p=1`, `&p=2`, ... (0-indexed offset, not the
1-indexed `s=`/`b=` convention used elsewhere in this catalog).

Requires the optional `playwright` package plus its browser binary:
    pip install -r requirements-browser.txt
    playwright install chromium
Without it the engine self-disables with a single message instead of failing.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import effective_ua

_QUERY_URL = 'https://www.ecosia.org/search?method=index&q={q}'
_PAGE_URL = 'https://www.ecosia.org/search?method=index&q={q}&p={page}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')

_CHALLENGE_TIMEOUT_MS = 20000
_POLL_INTERVAL_MS = 1000

_INSTALL_HINT = (
    'playwright not installed - run: '
    'pip install -r requirements-browser.txt && playwright install chromium'
)


async def _wait_past_challenge(page, timeout_ms: int) -> bool:
    """Poll until the Cloudflare interstitial title clears, or time out.

    Opportunistically clicks a Turnstile checkbox if one ever renders inside
    its iframe, but never blocks on finding it - most of the time there is
    nothing to click and the challenge just needs to be waited out.
    """
    elapsed = 0
    while elapsed < timeout_ms:
        title = await page.title()
        if 'just a moment' not in title.lower():
            return True
        try:
            checkbox = page.frame_locator(
                'iframe[src*="challenges.cloudflare.com"]'
            ).locator('input[type="checkbox"]')
            await checkbox.click(timeout=200)
        except Exception:
            pass
        await page.wait_for_timeout(_POLL_INTERVAL_MS)
        elapsed += _POLL_INTERVAL_MS
    title = await page.title()
    return 'just a moment' not in title.lower()


class Ecosia(BaseSource):
    NAME = 'ecosia'
    DESCRIPTION = (
        'Ecosia - Qwant-partnership index, headless-browser Cloudflare bypass '
        '(needs requirements-browser.txt; best-effort: leans on IP reputation)'
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

                    self._progress.note_request(_QUERY_URL.format(q=q))
                    await page.goto(
                        _QUERY_URL.format(q=q), wait_until='load', timeout=self.timeout * 1000
                    )
                    passed = await _wait_past_challenge(page, _CHALLENGE_TIMEOUT_MS)
                    if not passed:
                        self._vlog(1, 'Cloudflare Turnstile not resolved in time')
                        return set()

                    urls |= set(_HREF_RE.findall(await page.content()))
                    self._vlog(1, f'p=0: {len(urls)} url(s)')

                    for page_no in range(1, self.pages):
                        try:
                            self._progress.note_request(_PAGE_URL.format(q=q, page=page_no))
                            await page.goto(
                                _PAGE_URL.format(q=q, page=page_no),
                                wait_until='load',
                                timeout=self.timeout * 1000,
                            )
                        except Exception as e:
                            self._log_exc(e)
                            break
                        if not await _wait_past_challenge(page, _CHALLENGE_TIMEOUT_MS):
                            break
                        found = set(_HREF_RE.findall(await page.content()))
                        new_found = found - urls
                        if not new_found:
                            break
                        urls |= new_found
                        self._vlog(1, f'p={page_no}: {len(new_found)} url(s)')
                finally:
                    await browser.close()
        except Exception as e:
            self._log_exc(e)

        if not urls:
            self.report_block()
            self._vlog(1, 'no results - Cloudflare Turnstile likely blocked this IP')
        return self._filter_urls(urls)
