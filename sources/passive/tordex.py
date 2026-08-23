"""
TorDex - Tor hidden-service index, unfiltered.

The heaviest producer of the four Tor sources in live testing: 175 onion
links for a single one-word query against torch's 68, with `&page=N`
pagination confirmed working (the control is emitted as
`/search?query=...&page=2` and returns a different result set).

Unfiltered by design - it applies no blacklist of any kind, which is the
tradeoff against ahmia. Kept because coverage differs materially from the
other three, not because it is safe to point at arbitrary queries.

Results are plain onion `<a href>` links in static HTML, no redirect wrapper.
Each hit is emitted more than once (title link plus URL link plus favicon
link), which the set-based accumulator collapses for free.
"""
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep
from sources._tor_common import ONION_HREF_RE, tor_error_hint

_BASE = 'http://tordexu73joywapk2txdr54jed4imqledpcvcuf75qsas2gwdgksvnyd.onion'
_SEARCH = _BASE + '/search?query={q}&page={page}'


class Tordex(BaseSource):
    NAME = 'tordex'
    DESCRIPTION = 'TorDex - broad unfiltered Tor index, real pagination (needs Tor)'
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
