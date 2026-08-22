"""
Yandex - best-effort (currently serves a captcha challenge from this project's
network, verified 2026-08: the response body contains a 'captcha'/'checkbox'
challenge page rather than a title tag or result markup).

It ships anyway because the block is IP/reputation-based and may lift from a
different network or through `--proxy` - the exact same reasoning already
applied to `google`/`bing` in this catalog. When blocked it contributes
nothing, without erroring.

Yandex's operator vocabulary genuinely differs from Google's (`mime:` instead
of `filetype:`, `title:` instead of `intitle:`, plus unique operators `host:`,
`rhost:` for reverse-host/TLD-wide search, and `date:YYYYMMDD..YYYYMMDD`
ranges). Only `site:` is shared verbatim with the Google-style dorks this tool
otherwise assumes - a dork using the Yandex-native names works as literal
text since SUPPORTS_OPERATORS is True (no translation layer), a dork using
`filetype:`/`intitle:` simply won't be understood by Yandex's parser.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_TEMPLATE = 'https://yandex.com/search/?text={q}&p={page}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Yandex(BaseSource):
    NAME = 'yandex'
    DESCRIPTION = 'Yandex - own index, unique operators (best-effort: usually challenged)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://yandex.com/', self.user_agent)
            ) as client:
                for page in range(self.pages):
                    try:
                        resp = await self._get(client, _TEMPLATE.format(q=q, page=page))
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    found = set(_HREF_RE.findall(resp.text))
                    if not found:
                        break
                    urls |= found
                    self._vlog(1, f'page={page}: {len(found)} url(s)')
                    if page + 1 < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - Yandex is most likely serving a captcha challenge')
        return self._filter_urls(urls)
