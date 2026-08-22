"""
JusBrasil - consulta processual (public judicial process search, Brazil).

Different corpus than every other engine in this catalog: the query is a
name / CPF / CNPJ / process number, not a boolean web query, and the index is
Brazilian court records rather than the general web. `SUPPORTS_OPERATORS` is
False because JusBrasil's search box does not parse `site:`/`filetype:`-style
operators - a Google-style dork is downgraded to plain terms automatically.

Best-effort: verified live (2026-08) that this endpoint is currently behind a
Cloudflare Turnstile challenge ("Just a moment...") from this project's
network - the same IP/reputation-based block already documented for
`google`/`bing`/`yandex`/`baidu`. It ships anyway because the block may lift
from a different network or through `--proxy`; when challenged it contributes
nothing without raising.

Pagination follows the exact scheme the site uses: `p=2`, `p=3`, ... (page 1
is the bare query, no `p` param). Since the challenge page could not be
gotten past to inspect real result markup, this extracts every `<a href>`
like the rest of the catalog and lets `_filter_urls`/`--filter-host` sort out what's
a real process link versus JusBrasil's own navigation chrome.
"""
import re
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_ENDPOINT = 'https://www.jusbrasil.com.br/consulta-processual/busca?q={q}'
_HREF_RE = re.compile(r'href="(https?://[^"]+)"')


class Jusbrasil(BaseSource):
    NAME = 'jusbrasil'
    DESCRIPTION = 'JusBrasil - consulta processual pública, BR (best-effort: usually challenged)'
    CATEGORY = 'legal'
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers('https://www.jusbrasil.com.br/', self.user_agent)
            ) as client:
                for page in range(1, self.pages + 1):
                    url = _ENDPOINT.format(q=q)
                    if page > 1:
                        url += f'&p={page}'
                    try:
                        resp = await self._get(client, url)
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    found = set(_HREF_RE.findall(resp.text))
                    if not found:
                        break
                    urls |= found
                    self._vlog(1, f'p={page}: {len(found)} url(s)')
                    if page < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        if not urls:
            self._vlog(1, 'no results - JusBrasil is most likely serving a Cloudflare challenge')
        return self._filter_urls(urls)
