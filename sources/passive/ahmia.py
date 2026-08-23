"""
Ahmia - filtered search over Tor hidden services.

Open source (github.com/ahmia/ahmia-site) and the only engine in this Tor
group that actively blacklists abuse material, which is why it leads the
group. Reached over its own onion address rather than ahmia.fi so the whole
lookup stays inside Tor.

>>> TWO THINGS HERE ARE LOAD-BEARING, BOTH VERIFIED LIVE (2026-08). <<<

1. **The search form carries a per-session hidden token, and without it the
   engine silently answers with its own HOME PAGE.** `/search/?q=test` alone
   returned 4,735 bytes and zero results - a 200 that looks like it worked.
   Replaying the same query with the hidden field copied from the home page
   returned 1,946,240 bytes and 2,338 results. The field's NAME is random too
   (observed `name="7bb4a6" value="cd1c88"`), so both halves have to be
   scraped, not hardcoded.

   The token is reusable across different queries in the same session -
   confirmed by running a second, unrelated query with the same token and
   getting 650KB/831 results back. So it is fetched ONCE per fetch(), the
   same "one solve per fetch, not per request" shape mojeek's `chv` uses.

2. **Every result link is a tracking redirect, not the destination**:
   `href="/search/redirect?search_term=X&redirect_url=<REAL ONION URL>"`.
   Scraping href here would emit ahmia's own redirector for every hit -
   non-empty output that is entirely wrong. The real URL is the
   `redirect_url` query parameter, and it is HTML-escaped in place (a
   destination carrying `?C=S&O=A` appears as `&amp;O=A`), so it needs
   html.unescape() before unquote(). This is the second source in the
   catalog that must scrape something other than a plain href; so.py's
   `data-mdurl` was the first.

No pagination: ahmia returns the whole result set in one response (2,338
entries for a one-word query), and no page/offset parameter exists in its
markup. --pages is therefore ignored, deliberately.
"""
import html
import re
from urllib.parse import quote_plus, unquote

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers
from sources._tor_common import tor_error_hint

_BASE = 'http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion'
_SEARCH = _BASE + '/search/?q={q}&{tok_name}={tok_val}'

# The hidden field is emitted inside the search form; name and value are both
# session-scoped, so capture the pair rather than either half alone.
_TOKEN_RE = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]+)"')
# The destination lives in the query string of ahmia's own redirector.
_REDIRECT_RE = re.compile(r'redirect_url=([^"&]+(?:&amp;[^"&]+)*)')


class Ahmia(BaseSource):
    NAME = 'ahmia'
    DESCRIPTION = 'Ahmia - filtered Tor hidden-service index, open source (needs Tor)'
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
                token = await self._session_token(client)
                if not token:
                    self._vlog(1, 'no session token on the home page - cannot search')
                    return set()
                name, value = token
                resp = await self._get(
                    client, _SEARCH.format(q=q, tok_name=name, tok_val=value)
                )
                if resp.status_code != 200:
                    return set()
                for raw in _REDIRECT_RE.findall(resp.text):
                    target = unquote(html.unescape(raw))
                    if '.onion' in target:
                        urls.add(target)
                self._vlog(1, f'{len(urls)} url(s)')
        except Exception as e:
            hint = tor_error_hint(e, self.proxy)
            if hint:
                self._vlog(1, hint)
            else:
                self._log_exc(e)
        return self._filter_urls(urls)

    async def _session_token(self, client) -> tuple[str, str] | None:
        """Fetch the home page and lift the hidden form field from it.

        Returns (name, value) - both are session-scoped and random, see the
        module docstring for why skipping this silently returns the home page
        instead of results.
        """
        try:
            resp = await self._get(client, _BASE + '/')
        except Exception as e:
            hint = tor_error_hint(e, self.proxy)
            if hint:
                self._vlog(1, hint)
            else:
                self._log_exc(e)
            return None
        if resp.status_code != 200:
            return None
        found = _TOKEN_RE.search(resp.text)
        if not found:
            return None
        self._vlog(2, f'session token {found.group(1)}={found.group(2)}')
        return found.group(1), found.group(2)
