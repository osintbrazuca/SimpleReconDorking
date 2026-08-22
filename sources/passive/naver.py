"""
Naver - the dominant search engine in South Korea (~55-60% market share).

Verified live (2026-08): a plain HTML GET returns real result links directly -
138 of 223 links in one `site:wikipedia.org` test were on-domain wikipedia.org
hits, confirming both that the page is server-rendered (no JS needed) and that
`site:` actually narrows results rather than being ignored.

Pagination: the historical `start=` offset parameter was tested and made no
measurable difference to the result set (0 new links on a second page), so
this fetches a single page regardless of --pages until a working offset
parameter is confirmed. Naver's own CDN domains (pstatic.net, naver.net) are
filtered via assets/txt/search_engine_domains.txt, same mechanism as every
other engine's chrome links.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers

_ENDPOINT = 'https://search.naver.com/search.naver?query={q}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Naver(BaseSource):
    NAME = 'naver'
    DESCRIPTION = 'Naver - dominant Korean search engine, own index (no auth, single page)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://search.naver.com/', self.user_agent)
            ) as client:
                resp = await self._get(client, _ENDPOINT.format(q=q))
                if resp.status_code == 200:
                    urls = set(_HREF_RE.findall(resp.text))
                    self._vlog(1, f'{len(urls)} url(s)')
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
