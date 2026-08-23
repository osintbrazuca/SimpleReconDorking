"""
Onion Search Engine - .onion results over a clearnet endpoint.

The odd one out in the darkweb group: it indexes Tor hidden services but is
queried over ordinary HTTPS at onionsearchengine.com, so it is the only
source here that can return .onion URLs **without a running Tor daemon**.
That is why REQUIRES_TOR is False - forcing Tor would remove the one thing
that makes it different from ahmia/torch/tor66/tordex.

>>> ITS CLEARNET ENDPOINT IS CLOUDFLARE-GATED, AND THAT IS IP-DEPENDENT. <<<
Verified live (2026-08) from this project's development network: a plain
HTTPS GET returns **HTTP 403** with Cloudflare's "Attention Required" page -
the whole site, not just /search.php, and a hard block rather than a
solvable interstitial (complete browser headers, Sec-Fetch-* included, did
not change it). The identical request routed through Tor returned 200 with
real results. So this is an IP-reputation block on a datacenter address, the
same failure class as `ecosia`, and it may well answer fine from a
residential IP with no extra flags.

When it does 403, the escape hatch is to send just this source through Tor
while everything else stays direct:

    --proxy socks5h://127.0.0.1:9050 --proxy-source onionsearch

Pagination via `&page=N` is real, confirmed by diffing rather than by
trusting the parameter: for a broad query pages 2/3/4 carried 8, 9 and 7
links absent from the preceding pages (34 unique across four pages). Narrow
queries exhaust the index early and start repeating - normal, and the empty
page below ends the loop.

Result links are plain `href="http://<onion>/..."`. Each hit also carries a
sibling `report_page.php?url=<urlencoded>` abuse-report link, and the page
runs house ads on `ads.onionsearchengine.com`; ONION_HREF_RE excludes both
for free by requiring an http(s) scheme in front of a 56-char v3 address.
"""
from urllib.parse import quote_plus

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep
from sources._tor_common import ONION_HREF_RE

_BASE = 'https://onionsearchengine.com'
_SEARCH = _BASE + '/search.php?q={q}&page={page}'


class Onionsearch(BaseSource):
    NAME = 'onionsearch'
    DESCRIPTION = 'Onion Search Engine - .onion results over clearnet, no Tor needed (best-effort: Cloudflare)'
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
                    if resp.status_code == 403:
                        # Cloudflare, not the engine. Worth naming explicitly:
                        # the fix is a different exit IP, not a retry.
                        self._vlog(
                            1,
                            'HTTP 403 (Cloudflare) - this IP is blocked; retry via Tor with '
                            '--proxy socks5h://127.0.0.1:9050 --proxy-source onionsearch',
                        )
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
            self._log_exc(e)
        return self._filter_urls(urls)
