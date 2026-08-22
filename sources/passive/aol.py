"""
AOL Search - a portal frontend, not an independent index: searching on
aol.com redirects to Yahoo's "YHS" (Yahoo Hosted Search) backend, confirmed
live by following the redirect from a real search
(`search.yahoo.com/yhs/search?...&hspart=aol&hsimp=yhs-aol_portal`). Same
result-wrapper mechanism as `yahoo.py` (`.../RU=<urlencoded target>/RK=...`)
because it's the same backend - this module exists as a separate engine
because it's a genuinely different portal/branding surface an operator might
want attributed separately in `sources`/`url_sources`, not because the
underlying search differs.

Unlike the other recently-added engines, this needs no browser at all: a
plain HTTP GET returns real results directly (confirmed live: `site:`
narrows correctly, 10 of 15 non-chrome hits on-domain for
`site:wikipedia.org`), and pagination via `b=` offsets genuinely returns new
results.
"""
import re
from urllib.parse import quote_plus, unquote

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = (
    'https://search.yahoo.com/yhs/search?s_chn=prt_bon&hspart=aol&hsimp=yhs-aol_portal'
    '&fr=yhs-aol-aol_portal&p={q}&b={offset}&pz=7&bct=0&xargs=0'
)
# Result offsets (1, 8, 15, 22 ...) - one per page, same convention as yahoo.py.
_OFFSETS = (1, 8, 15, 22, 29, 36, 43, 50)
_RU_RE = re.compile(r'/RU=([^/]+)/R[A-Za-z]')


class Aol(BaseSource):
    NAME = 'aol'
    DESCRIPTION = 'AOL Search - Yahoo-hosted backend (YHS), full operator support, no key'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        offsets = _OFFSETS[:self.pages]
        try:
            async with self._make_client(
                headers=browser_headers('https://search.aol.com/', self.user_agent)
            ) as client:
                for i, offset in enumerate(offsets):
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, offset=offset))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = self._extract(resp.text)
                    if not page:
                        break
                    urls |= page
                    self._vlog(1, f'b={offset}: {len(page)} url(s)')
                    if i + 1 < len(offsets):
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)

    @staticmethod
    def _extract(html: str) -> set[str]:
        found: set[str] = set()
        for raw in _RU_RE.findall(html):
            decoded = unquote(raw)
            if decoded.startswith(('http://', 'https://')):
                found.add(decoded)
        return found
