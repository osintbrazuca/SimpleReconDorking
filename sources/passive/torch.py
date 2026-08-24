"""
Torch - one of the oldest and largest Tor hidden-service indexes.

Reached at the current `torchdeedp3i2...` address; the older
`xmh57jrknzkhv6y3...` v2-era address that circulates in reference lists is
not used - v2 onions were removed from the Tor network in October 2021.

>>> TORCH HAS NO WORKING PAGINATION, AND THAT IS WHY --pages IS IGNORED. <<<
Verified live (2026-08) by requesting the same query with `page=2`, `s=20`,
`start=20`, `offset=20`, `pn=2` and `p=2`: every one of them returned page
one byte-for-byte (same response size, the same 68 unique onion links, zero
links not already on page one). Looping `self.pages` times here would refetch
an identical page over Tor - slow, pointless traffic that would also inflate
the per-source hit count in -v 1 without contributing a single new URL. One
request per fetch(), on purpose.

Results are plain `<a href="http://....onion/...">` links in the static HTML,
so no JS rendering and no redirect wrapper (unlike ahmia). The page does carry
a couple of paid placements pointing at other indexes; those are ordinary
onion links and are left in - they are real results of the query, and
filtering "ads" heuristically would be guesswork.
"""
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers
from sources._tor_common import ONION_HREF_RE, tor_error_hint

_BASE = 'http://torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion'
_SEARCH = _BASE + '/search?query={q}'


class Torch(BaseSource):
    NAME = 'torch'
    DESCRIPTION = 'Torch - long-running, unfiltered Tor index'
    CATEGORY = 'darkweb'
    REQUIRES_TOR = True
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        q = quote_plus(self.query_for(dork))
        urls: set[str] = set()
        if self.pages > 1:
            self._vlog(1, 'single page only - torch ignores every paging param (see module docstring)')
        try:
            async with self._make_client(
                headers=browser_headers(_BASE + '/', self.user_agent)
            ) as client:
                resp = await self._get(client, _SEARCH.format(q=q))
                if resp.status_code != 200:
                    return set()
                urls |= set(ONION_HREF_RE.findall(resp.text))
                self._vlog(1, f'{len(urls)} url(s)')
        except Exception as e:
            hint = tor_error_hint(e, self.proxy)
            if hint:
                self._vlog(1, hint)
            else:
                self._log_exc(e)
        return self._filter_urls(urls)
