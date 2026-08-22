"""
Google Search (direct scrape) - best-effort.

google.com/search is IP/reputation gated and usually answers a JavaScript shell
page with zero result links. It ships anyway because the block can lift from a
different network or through `--proxy`. **For reliable Google coverage use
`googlecse`**, which reaches Google's index through public Custom Search Engines
and needs no credentials.
"""
import re
from urllib.parse import quote_plus, unquote

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://www.google.com/search?q={q}&num=30&hl=en&start={start}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')
_URLQ_RE = re.compile(r'/url\?q=([^"&]+)')
_CONSENT_COOKIE = {'CONSENT': 'YES+cb.20220301-11-p0.en+FX+111'}


class Google(BaseSource):
    NAME = 'google'
    DESCRIPTION = 'Google Search scrape - full operator support (best-effort: usually blocked)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://www.google.com/', self.user_agent),
                cookies=_CONSENT_COOKIE,
            ) as client:
                for i in range(self.pages):
                    start = i * 30
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, start=start))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = self._extract(resp.text)
                    if not page:
                        break
                    urls |= page
                    self._vlog(1, f'start={start}: {len(page)} url(s)')
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - google.com is most likely blocking; try googlecse')
        return self._filter_urls(urls)

    @staticmethod
    def _extract(html: str) -> set[str]:
        found: set[str] = set(_HREF_RE.findall(html))
        for raw in _URLQ_RE.findall(html):
            decoded = unquote(raw)
            if decoded.startswith(('http://', 'https://')):
                found.add(decoded)
        return found
