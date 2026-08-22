"""
Yahoo Japan - operated independently by LY Corporation, same search-tech
lineage as global Yahoo (hence the shared `p=` query param and `b=` paging
offset convention, both confirmed live).

Verified live (2026-08): a plain HTML GET returns real result links directly -
a `site:wikipedia.org` query returned pt/es/en/fr.wikipedia.org hits among the
external links, and `b=11` returned 23 links not present on the first page,
confirming pagination actually works (unlike Naver/Daum, tested alongside
this and left single-page for lack of a working offset).
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://search.yahoo.co.jp/search?p={q}&b={offset}'
_OFFSETS = (1, 11, 21, 31, 41, 51, 61, 71)
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Yahoojp(BaseSource):
    NAME = 'yahoojp'
    DESCRIPTION = 'Yahoo Japan - independent JP operation, same search stack as global Yahoo'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        offsets = _OFFSETS[:self.pages]
        try:
            async with self._make_client(
                headers=browser_headers('https://search.yahoo.co.jp/', self.user_agent)
            ) as client:
                for i, offset in enumerate(offsets):
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, offset=offset))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = set(_HREF_RE.findall(resp.text))
                    if not page:
                        break
                    urls |= page
                    self._vlog(1, f'b={offset}: {len(page)} url(s)')
                    if i + 1 < len(offsets):
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
