"""
Seznam.cz - dominant search engine in the Czech market.

Verified live against this project's own network (2026-08): a plain HTML GET
returns real, on-domain result links directly in the response body - no JS
rendering required, unlike several other regional portals tested for this
catalog (Qwant, Ecosia, Metager, Swisscows, Sogou, So.com all came back
JS-shell pages with zero organic links in the static HTML and were left out
of the engine catalog for exactly that reason).

Pagination via `from=` (offset) is confirmed empirically: page 2 returned 52
new links not present on page 1. `count=` caps at 20 per the vendor docs.

No API key, no operator translation needed - `site:` passes through and
narrows results correctly (verified: a `site:wikipedia.org` query returned
wikipedia.org hits as most of the external links).
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://search.seznam.cz/?q={q}&from={offset}&count=20'
_PAGE_SIZE = 20
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Seznam(BaseSource):
    NAME = 'seznam'
    DESCRIPTION = 'Seznam.cz - dominant Czech search engine, own index (no auth)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://search.seznam.cz/', self.user_agent)
            ) as client:
                for i in range(self.pages):
                    offset = i * _PAGE_SIZE
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
                    self._vlog(1, f'from={offset}: {len(page)} url(s)')
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
