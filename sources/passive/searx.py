"""
SearXNG - federated metasearch across public instances.

SearXNG fans one query out to dozens of upstream engines (Google, Bing,
Brave, Startpage, Wikipedia...) behind one privacy-respecting front, so a
single healthy instance can outproduce several direct scrapers combined.
The cost is that public instances are wildly unreliable, and this module is
shaped almost entirely around that fact.

>>> THREE THINGS WERE MEASURED LIVE (2026-08) AND EACH ONE IS LOAD-BEARING. <<<

1. **Both formats are queried, because neither is a superset.** `?format=json`
   is the cheapest path (structured, no scraping) and goes first, but many
   instances answer it with a **302** because `search.formats` in their
   settings.yml omits `json`. The HTML page is then fetched regardless -
   measured on a healthy instance, JSON and HTML overlap heavily yet each
   run surfaced results the other missed, the union beating JSON alone by
   roughly 1-10%. SearXNG re-queries its upstream engines on every render,
   so the two views are simply two live samples. Cost: two requests/page.

2. **A blocked instance answers HTTP 200, not an error.** From a datacenter
   IP, 11 of 12 instances sampled returned 200 carrying an Anubis
   proof-of-work page ("Checking if wolf..."), a "Making sure you're not a
   bot!" interstitial, or simply their own home page with no results at all.
   Counting 200 as success would silently record those as working instances
   and stop rotating. `_looks_challenged()` exists for that, and an instance
   only "counts" when it actually yields URLs.

3. **Parallel requests get the whole pool rate-limiting you.** Firing 15
   instances at once returned `429 Too Many Requests` from nearly all of
   them; the identical hosts answered fine when queried sequentially with a
   Referer and a pause. Hence one instance at a time, with polite_sleep()
   between them - never gather().

Category expansion is where the yield actually comes from. Measured on one
instance with the same query: instance default = 59 results, adding an
explicit ten-engine `&engines=` list = 66 (marginal), but
`&categories=general,it,science,files` = 249. The `engines` parameter is
therefore NOT used; categories are. images/videos/music/social are left out
on purpose - they return media and profile URLs, which is noise for a tool
whose output is meant to be fed to httpx/nuclei.

Instances are shuffled and queried until _WANT_OK of them produce results,
capped by _MAX_ATTEMPTS so a fully-blocked pool cannot turn one dork into 72
requests. Aggregating a few instances rather than stopping at the first
(the previous behaviour) both survives a blocked head of the list and merges
genuinely different upstream indexes.
"""
import html
import json
import random
import re

from core.assets import load_lines
from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_INSTANCES_FILE = 'searx_instances.txt'
_PAGE_SIZE = 10

# Textual categories only - see the module docstring for the measurement.
_CATEGORIES = 'general,it,science,files'

# Stop once this many instances have actually produced URLs, and never probe
# more than this many in total (a fully-blocked pool would otherwise cost 72
# requests per dork).
_WANT_OK = 3
_MAX_ATTEMPTS = 12

# The real result link in SearXNG's `simple` theme. Deliberately anchored on
# class="url_header": that anchor appears exactly once per result and never on
# the instance's own navigation, so scraping it needs no chrome filtering
# (verified: 248 unique result URLs extracted, zero belonging to the instance).
_RESULT_RE = re.compile(r'<a\s+href="(https?://[^"]+)"\s+class="url_header"')

# Markers of an anti-bot interstitial. Served with HTTP 200 *or* 202 -
# Anubis answers its own challenge page with 202, which is why the status
# check below accepts both instead of only 200.
_CHALLENGE_MARKERS = (
    'checking if',          # Anubis proof-of-work ("Checking if wolf...")
    "you're not a bot",     # Anubis, newer wording
    'you&#39;re not a bot',  # ...the same, HTML-escaped in the <title>
    'making sure you',
    'just a moment',
    'enable javascript and cookies',
    'cap_script_nonce',     # the Cap PoW widget, which keeps the SearXNG title
)
_CHALLENGE_STATUS = (200, 202)

# SearXNG stamps every page with the view that rendered it. A /search request
# answered by `index` means the instance served its HOME PAGE instead of
# running the query - the silent shape bot-blocking takes here, and
# indistinguishable from a healthy 200 without this marker. Verified: a
# working instance returns `results` (421 result links), a blocking one
# returns `index` (zero).
_ENDPOINT_RESULTS = 'name="endpoint" content="results"'
_ENDPOINT_INDEX = 'name="endpoint" content="index"'


class Searx(BaseSource):
    NAME = 'searx'
    DESCRIPTION = 'SearXNG - federated metasearch over public instances (no key)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        instances = load_lines(_INSTANCES_FILE)
        if not instances:
            self._vlog(1, f'no instances - assets/txt/{_INSTANCES_FILE} missing or empty')
            return set()

        # list() before shuffle: load_lines caches and hands back the SAME list
        # object every call, so shuffling in place would reorder the cache for
        # every other task in the run.
        pool = list(instances)
        random.shuffle(pool)

        q = self.query_for(dork)
        urls: set[str] = set()
        healthy = 0
        try:
            async with self._make_client(
                headers=browser_headers(configured_ua=self.user_agent)
            ) as client:
                # Upper bound on instances this task will touch; it may stop
                # earlier once _WANT_OK answer, and the remaining units are
                # settled below so the bar does not stall short of the mark.
                planned = min(len(pool), _MAX_ATTEMPTS)
                self._progress.declare_units(planned)
                walked = 0
                for attempt, instance in enumerate(pool[:_MAX_ATTEMPTS], 1):
                    base = instance.rstrip('/')
                    found = await self._search_instance(client, base, q)
                    walked += 1
                    self._progress.note_unit()
                    if found:
                        healthy += 1
                        urls |= found
                        self._vlog(1, f'{len(found)} url(s) from {base}')
                        if healthy >= _WANT_OK:
                            # Settle the units this task will now never walk,
                            # otherwise an early success leaves the bar short.
                            self._progress.note_unit(planned - walked)
                            break
                    else:
                        self._vlog(2, f'no results from {base}')
                    if attempt < _MAX_ATTEMPTS:
                        await polite_sleep(1.0)
                if not healthy:
                    self._vlog(
                        1,
                        f'no instance answered out of {min(len(pool), _MAX_ATTEMPTS)} tried - '
                        'public SearXNG hosts block datacenter IPs aggressively',
                    )
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)

    @staticmethod
    def _looks_challenged(body: str) -> bool:
        """An anti-bot interstitial (Anubis PoW, Cap widget, and friends)."""
        head = body[:4000].lower()
        return any(marker in head for marker in _CHALLENGE_MARKERS)

    @staticmethod
    def _served_home(body: str) -> bool:
        """True when the instance answered a /search with its home page.

        Checked before scraping because it is the difference between "this
        query found nothing" and "this instance refused to run the query" -
        the two are the same HTTP 200 with zero results otherwise, and only
        the latter means the pool should keep rotating.
        """
        head = body[:4000]
        return _ENDPOINT_INDEX in head and _ENDPOINT_RESULTS not in head

    async def _search_instance(self, client, base: str, q: str) -> set[str]:
        """JSON if the instance allows it, otherwise the HTML page."""
        found: set[str] = set()
        for page in range(1, self.pages + 1):
            hits = await self._page(client, base, q, page)
            if hits is None:
                break
            found |= hits
            if len(hits) < _PAGE_SIZE:
                break
            if page < self.pages:
                await polite_sleep(1.0)
        return found

    async def _page(self, client, base: str, q: str, page: int) -> set[str] | None:
        """One result page, from BOTH formats, merged.

        The two are queried in sequence rather than one as the other's
        fallback: measured on a healthy instance with the same query, the
        JSON and HTML views of the same page overlap heavily but neither is a
        superset - across runs the union beat JSON alone by roughly 1-10%,
        because SearXNG re-queries its upstream engines live and each render
        catches a slightly different slice. Cost is two requests per page.

        None means "this instance is not usable" and ends its page loop; an
        empty set means "answered, nothing found".
        """
        params = {
            'q': q,
            'pageno': page,
            'categories': _CATEGORIES,
            'language': 'auto',
            'time_range': '',
            'safesearch': 0,
        }
        headers = {'Referer': base + '/'}
        found: set[str] = set()
        answered = False

        # 1) JSON - cheapest and structured, but many instances omit `json`
        # from search.formats and answer 302. That is a reason to also try
        # HTML, not to write the instance off.
        try:
            resp = await self._get(
                client, f'{base}/search',
                params={**params, 'format': 'json'}, headers=headers,
            )
        except Exception as e:
            self._log_exc(e)
            return None
        else:
            if resp.status_code not in _CHALLENGE_STATUS and resp.status_code != 302:
                # 302 just means "this instance does not publish JSON" and is
                # handled by the HTML pass below, so it stays quiet. Anything
                # else (429 above all) would otherwise end as a silent None
                # and read as "no results" in the log.
                self._vlog(1, f'HTTP {resp.status_code} from {base}'
                              + (' (rate limited)' if resp.status_code == 429 else ''))
                return None
            if resp.status_code in _CHALLENGE_STATUS:
                body = resp.text
                # The JSON call already reveals a blocked instance: it comes
                # back as HTML, either an interstitial or the home page. Bail
                # here rather than spending the HTML request too - with most
                # of the pool blocking a datacenter IP, that second request is
                # the single biggest source of wasted traffic in this source.
                if self._looks_challenged(body):
                    self._vlog(1, f'anti-bot interstitial from {base}')
                    return None
                if self._served_home(body):
                    self._vlog(1, f'{base} served its home page - query not run (blocked)')
                    return None
                try:
                    data = json.loads(body)
                except (json.JSONDecodeError, ValueError):
                    pass
                else:
                    found |= {
                        item['url'] for item in (data.get('results') or [])
                        if isinstance(item, dict) and item.get('url')
                    }
                    answered = True

        await polite_sleep(1.0)

        # 2) HTML - always, even when JSON already answered: neither format is
        # a superset of the other (see the module docstring).
        try:
            resp = await self._get(
                client, f'{base}/search',
                params={**params, 'theme': 'simple'}, headers=headers,
            )
        except Exception as e:
            self._log_exc(e)
            return found if answered else None
        if resp.status_code not in _CHALLENGE_STATUS:
            self._vlog(1, f'HTTP {resp.status_code} from {base}'
                          + (' (rate limited)' if resp.status_code == 429 else ''))
        else:
            body = resp.text
            if self._looks_challenged(body):
                self._vlog(1, f'anti-bot interstitial from {base}')
            elif self._served_home(body):
                self._vlog(1, f'{base} served its home page - query not run (blocked)')
            else:
                # html.unescape is required, not cosmetic: a result URL whose
                # query string contains '&' is emitted as '&amp;' in the
                # markup, and passing that through produces a malformed URL
                # that also fails to dedupe against the JSON copy of the very
                # same result.
                found |= {html.unescape(u) for u in _RESULT_RE.findall(body)}
                answered = True

        return found if answered else None
        if resp.status_code == 200:
            if self._looks_challenged(resp.text):
                self._vlog(2, f'anti-bot interstitial from {base}')
            else:
                # html.unescape is required, not cosmetic: a result URL whose
                # query string contains '&' is emitted as '&amp;' in the
                # markup, and passing that through produces a malformed URL
                # that also fails to dedupe against the JSON copy of the very
                # same result.
                found |= {html.unescape(u) for u in _RESULT_RE.findall(resp.text)}
                answered = True

        return found if answered else None
