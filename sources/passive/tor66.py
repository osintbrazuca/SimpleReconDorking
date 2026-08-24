"""
Tor66 - Tor hidden-service index with a fresh/random-service directory.

Unlike torch, `&page=N` is real here - verified live (2026-08), the control
appears in the markup as `/search?q=...&sorttype=rel&page=N` and advances the
result set.

Tor66 renders a lot of its own navigation as absolute onion links (its home,
/about, /fresh, /random, /submit_onion_url, plus a `/serviceinfo/?service=...`
detail link next to every hit), so its own address is listed in
config/search_engine_domains.txt and dropped by BaseSource's
is_source_chrome() check - the same treatment every clearnet engine in this
catalog already gets. Its real results live on other onion domains, which is
exactly the condition that file's convention requires before adding an entry.

>>> THE browser_headers() CALL BELOW IS LOAD-BEARING, NOT COSMETIC. <<<
Verified live: the identical request sent with httpx's default headers comes
back HTTP 200 with ZERO result links, while the same URL with the realistic
browser header set returns 33 per page. Tor66 varies its output on the
User-Agent rather than blocking outright, so dropping browser_headers() here
would leave a source that looks healthy (200, no exception) and silently
contributes nothing.

Pagination confirmed by diffing pages rather than trusting the parameter:
page 2 carried 20 links absent from page 1, page 3 another 20 absent from
both - the trap torch falls into (identical page echoed back for every paging
param) does not apply here.
"""
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep
from sources._tor_common import ONION_HREF_RE, tor_error_hint

_BASE = 'http://tor66sewebgixwhcqfnp5inzp5x5uohhdy3kvtnyfxc2e5mxiuh34iid.onion'
_SEARCH = _BASE + '/search?q={q}&sorttype=rel&page={page}'


class Tor66(BaseSource):
    NAME = 'tor66'
    DESCRIPTION = 'Tor66 - Tor index with fresh-service directory (needs Tor)'
    CATEGORY = 'darkweb'
    REQUIRES_TOR = True
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers(_BASE + '/', self.user_agent)
            ) as client:
                for page in range(1, self.pages + 1):
                    try:
                        resp = await self._get(client, _SEARCH.format(q=q, page=page))
                    except Exception as e:
                        hint = tor_error_hint(e, self.proxy)
                        if hint:
                            self._vlog(1, hint)
                        else:
                            self._log_exc(e)
                        break
                    if resp.status_code != 200:
                        break
                    found = set(ONION_HREF_RE.findall(resp.text))
                    if not found:
                        break
                    urls |= found
                    self._vlog(1, f'page={page}: {len(found)} url(s)')
                    if page < self.pages:
                        await polite_sleep()
        except Exception as e:
            hint = tor_error_hint(e, self.proxy)
            if hint:
                self._vlog(1, hint)
            else:
                self._log_exc(e)
        return self._filter_urls(urls)
