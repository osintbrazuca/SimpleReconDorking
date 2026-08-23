"""
Tor66 over its clearnet host - the same index as `tor66`, no Tor required.

Deliberately a separate module from sources/passive/tor66.py rather than a
fallback inside it, because the two endpoints are complementary and an
operator may legitimately want either one alone. Verified live (2026-08)
with the identical query against both:

    endpoint          from clearnet          through Tor
    ----------------  ---------------------  ---------------------------
    .onion (tor66)    unreachable (no DNS)   33 unique links
    tor66.org (here)  15 unique links        0 - serves its home page

So: the onion host indexes more than twice as deep and is the one to prefer
when Tor is available (`tor66`), while this module is what answers on a
machine with no Tor daemon at all.

>>> DO NOT ROUTE THIS SOURCE THROUGH TOR. <<<
Unlike `onionsearch`, whose clearnet host is 403-blocked from datacenter IPs
and *is* rescued by `--proxy socks5h://...`, tor66.org answers a Tor exit
node with HTTP 200 and its own home page - zero results, no error, nothing
to detect. Sending this one through Tor silently costs a request and gains
nothing; use the `tor66` module instead, which talks to the onion host
directly and returns more anyway.

>>> THE browser_headers() CALL IS LOAD-BEARING, NOT COSMETIC. <<<
Same quirk as the onion host: with httpx's default headers the response is
HTTP 200 with ZERO result links; with a realistic browser header set it
returns results. Tor66 varies output on the User-Agent instead of blocking,
so dropping browser_headers() would leave a source that looks perfectly
healthy and contributes nothing.

Pagination confirmed by diffing rather than by trusting the parameter: page
2 carried 10 links absent from page 1.

No entry is needed in assets/txt/search_engine_domains.txt for tor66.org:
ONION_HREF_RE only ever matches a 56-char v3 .onion address, so this host's
own navigation links cannot be captured in the first place.
"""
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep
from sources._tor_common import ONION_HREF_RE

_BASE = 'https://tor66.org'
_SEARCH = _BASE + '/search?q={q}&sorttype=rel&page={page}'


class Tor66web(BaseSource):
    NAME = 'tor66web'
    DESCRIPTION = 'Tor66 via clearnet host - .onion results without Tor (shallower than tor66)'
    CATEGORY = 'darkweb'
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
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        break
                    found = set(ONION_HREF_RE.findall(resp.text))
                    if not found:
                        # Also what a Tor-routed request gets: a 200 carrying
                        # the home page. See the module docstring.
                        break
                    urls |= found
                    self._vlog(1, f'page={page}: {len(found)} url(s)')
                    if page < self.pages:
                        await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
