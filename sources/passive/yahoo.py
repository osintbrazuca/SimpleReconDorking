"""
Yahoo Search - the one major engine that still answers a raw query without a
challenge, which makes it the scraping backbone of dorking here.

Results are not linked directly: Yahoo wraps every hit in a redirect of the
form `.../RU=<urlencoded target>/RK=...`, so the real URL is recovered by
pulling the RU= segment and unquoting it.

Pagination through the `b=` offset returns genuinely different result sets.
"""
import re
from urllib.parse import quote_plus, unquote

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = (
    'https://search.yahoo.com/search?fr2=piv-web&p={q}&b={offset}'
    '&pz=7&bct=0&xargs=0&ei=UTF-8'
)
# Result offsets (1, 8, 15, 22 ...) - one per page.
_OFFSETS = (1, 8, 15, 22, 29, 36, 43, 50)
_RU_RE = re.compile(r'/RU=([^/]+)/R[A-Za-z]')


class Yahoo(BaseSource):
    NAME = 'yahoo'
    DESCRIPTION = 'Yahoo Search - full operator support, answers without a challenge'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        offsets = _OFFSETS[:self.pages]
        try:
            async with self._make_client(
                headers=browser_headers('https://search.yahoo.com/', self.user_agent)
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
                    self._vlog(1, f'page b={offset}: {len(page)} url(s)')
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
