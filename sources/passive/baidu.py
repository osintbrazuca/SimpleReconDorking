"""
Baidu - best-effort (currently serves a "百度安全验证" / Baidu Security
Verification anti-bot page from this project's network, verified 2026-08).

It ships anyway because the block is IP/reputation-based and may lift from a
different network or through `--proxy` - the same reasoning already applied
to `google`/`bing`/`yandex` in this catalog. When blocked it contributes
nothing, without erroring.

Response encoding: Baidu serves UTF-8 (confirmed live), not the GBK/GB2312
some older references warn about - httpx's default decoding handles it
without special-casing.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://www.baidu.com/s?wd={q}&pn={offset}'
_PAGE_SIZE = 10
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Baidu(BaseSource):
    NAME = 'baidu'
    DESCRIPTION = 'Baidu - largest Chinese search engine (best-effort: usually challenged)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://www.baidu.com/', self.user_agent)
            ) as client:
                for i in range(self.pages):
                    offset = i * _PAGE_SIZE
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, offset=offset))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    found = set(_HREF_RE.findall(resp.text))
                    if not found:
                        break
                    urls |= found
                    self._vlog(1, f'pn={offset}: {len(found)} url(s)')
                    if i + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - Baidu is most likely serving its anti-bot verification page')
        return self._filter_urls(urls)
