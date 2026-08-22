"""
DuckDuckGo - the HTML/Lite endpoint (no JavaScript, no API key).

DuckDuckGo honours the common dork operators (`site:`, `filetype:`, `intitle:`,
`inurl:`) and its lite endpoint returns plain HTML that is trivial to parse.
It is rate/reputation sensitive: a flagged IP gets a 202 "anomaly" page with no
results, in which case this contributes nothing without erroring - the same
best-effort contract as `bing`/`google`.

Results are wrapped in a `/l/?uddg=<urlencoded>` redirect; the real URL is the
`uddg` parameter, unquoted.
"""
import re
from urllib.parse import quote_plus, unquote, urlparse, parse_qs

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_ENDPOINT = 'https://lite.duckduckgo.com/lite/'
_HREF_RE = re.compile(r'href="(https?://[^"]+|/l/\?[^"]+)"')


class Duckduckgo(BaseSource):
    NAME = 'duckduckgo'
    DESCRIPTION = 'DuckDuckGo lite - operator support, no key (best-effort: rate sensitive)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = self.query_for(dork)
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://lite.duckduckgo.com/', self.user_agent)
            ) as client:
                offset = 0
                for i in range(self.pages):
                    data = {'q': q, 'kl': 'wt-wt'}
                    if offset:
                        data['s'] = str(offset)
                        data['dc'] = str(offset + 1)
                    try:
                        # self._post, not client.post: going direct bypassed
                        # the --rate-limit semaphore and, now, proxy rotation.
                        # It also logs the status itself, so the local
                        # verbose>=2 echo that used to live here is gone.
                        resp = await self._post(client, _ENDPOINT, data=data)
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = self._extract(resp.text)
                    if not page:
                        break
                    urls |= page
                    self._vlog(1, f's={offset}: {len(page)} url(s)')
                    offset += 20
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - DuckDuckGo is most likely rate limiting this IP')
        return self._filter_urls(urls)

    @staticmethod
    def _extract(html: str) -> set[str]:
        found: set[str] = set()
        for raw in _HREF_RE.findall(html):
            if raw.startswith('/l/?'):
                qs = parse_qs(urlparse(raw).query)
                target = (qs.get('uddg') or [''])[0]
                if target:
                    found.add(unquote(target))
            elif raw.startswith(('http://', 'https://')):
                found.add(raw)
        return found
