"""
Bing Search - indexed URLs for the dork (best-effort).

Bing frequently serves a Cloudflare Turnstile challenge instead of results; when
that happens the module contributes nothing and never errors. It ships anyway
because the block is IP/reputation-based and may lift from another network or
through `--proxy`. Zero results here is the expected outcome on a flagged IP,
not a bug - reach for `yahoo`/`googlecse` for reliable coverage.
"""
import base64
import re
from urllib.parse import quote_plus, unquote

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

# first= offsets, 10 results/page
_TEMPLATE = 'https://www.bing.com/search?q={q}&filt=rf&first={first}&FORM=PERE'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')
_CK_RE = re.compile(r'[?&]u=a1([A-Za-z0-9_\-]+)')


class Bing(BaseSource):
    NAME = 'bing'
    DESCRIPTION = 'Bing Search - full operator support (best-effort: often challenged)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://www.bing.com/', self.user_agent)
            ) as client:
                for i in range(self.pages):
                    first = 1 + i * 10
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, first=first))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    page = self._extract(resp.text)
                    if page:
                        urls |= page
                        self._vlog(1, f'first={first}: {len(page)} url(s)')
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - Bing is most likely serving a bot challenge')
        return self._filter_urls(urls)

    @staticmethod
    def _extract(html: str) -> set[str]:
        html = re.sub(r'</?strong>', '', html)
        found: set[str] = set(_HREF_RE.findall(html))
        for token in _CK_RE.findall(html):
            try:
                padded = token + '=' * (-len(token) % 4)
                decoded = base64.urlsafe_b64decode(padded).decode('utf-8', 'ignore')
            except Exception:
                continue
            if decoded.startswith(('http://', 'https://')):
                found.add(unquote(decoded))
        return found
