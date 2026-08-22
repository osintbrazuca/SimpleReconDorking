"""
Startpage - Google results proxied without tracking (best-effort scrape).

Startpage relays Google's index, so it honours the Google operator set. It has
no public API and applies anti-bot checks, so this is a best-effort HTML scrape:
a challenged request yields nothing and never errors.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://www.startpage.com/sp/search?query={q}&page={page}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')
_SKIP_HOSTS = ('startpage.com', 'ixquick.com', 'startpage.eu')


class Startpage(BaseSource):
    NAME = 'startpage'
    DESCRIPTION = 'Startpage - Google results via privacy proxy (best-effort scrape)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://www.startpage.com/', self.user_agent)
            ) as client:
                for i in range(self.pages):
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, page=i + 1))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = {
                        u for u in _HREF_RE.findall(resp.text)
                        if not any(s in u for s in _SKIP_HOSTS)
                    }
                    if not page:
                        break
                    urls |= page
                    self._vlog(1, f'page {i + 1}: {len(page)} url(s)')
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - Startpage most likely served a challenge')
        return self._filter_urls(urls)
