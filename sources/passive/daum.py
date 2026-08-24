"""
Daum - Kakao's search portal, #2 in South Korea behind Naver.

Verified live (2026-08): returns real external result links in static HTML
(YouTube, Melon and other third-party hits observed alongside Kakao's own
ecosystem links), though with more chrome noise than Naver or Seznam -
Daum interleaves results with links into its own Map/Shopping/Dictionary
sub-services (map.kakao.com, shoppinghow.kakao.com, dic.daum.net), filtered
via config/search_engine_domains.txt like every other engine's chrome.

Pagination: `p=` (page number) was tested and made no measurable difference
to the result set, so this fetches a single page regardless of --pages until
a working pagination parameter is confirmed.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers

_ENDPOINT = 'https://search.daum.net/search?w=tot&q={q}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Daum(BaseSource):
    NAME = 'daum'
    DESCRIPTION = 'Daum (Kakao) - #2 Korean search portal (no auth, single page)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://search.daum.net/', self.user_agent)
            ) as client:
                resp = await self._get(client, _ENDPOINT.format(q=q))
                if resp.status_code == 200:
                    urls = set(_HREF_RE.findall(resp.text))
                    self._vlog(1, f'{len(urls)} url(s)')
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
