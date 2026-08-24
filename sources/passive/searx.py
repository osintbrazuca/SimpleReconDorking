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

Expansion is where the yield actually comes from, and there are TWO separate
levers. Do not conflate them - they are different SearXNG mechanisms, and a
measurement of one says nothing about the other.

*Lever 1, categories.* Measured on one instance with the same query: instance
default = 59 results, `&categories=general,it,science,files` = 249. See
_CATEGORIES. images/videos/music/social are left out on purpose - they return
media and profile URLs, which is noise for a tool whose output is meant to be
fed to httpx/nuclei.

The same measurement tried an explicit ten-engine **`&engines=`** list and got
66 (marginal), which is why that parameter is still not used. `&engines=` is a
per-search *selector*, parsed in SearXNG's webadapter, and it can only pick
among engines the instance is already willing to run - so restricting to ten
mainstream ones it already ran changed almost nothing. That result does NOT
generalise to lever 2 below, which is a different parameter reaching a
different part of SearXNG.

*Lever 2, the engine roster* (the `engines` list in config/searx.json, applied
by engine_prefs()). A public
instance only queries the engines its own settings.yml leaves enabled, and most
ship yandex, baidu, sogou, quark, 360search, naver, seznam, mojeek, yacy, wiby
and mwmbl as `disabled: true`. Selecting categories does not turn those on -
inside each category the instance default still applies. `enabled_engines` is
a *preference*, parsed in SearXNG's preferences layer, and it does.

>>> MEASURED LIVE (2026-08), `site:gov.br filetype:pdf`, pages=1. <<<
Two instances, expansion off -> on:

    search.mectov.my.id      20 ->  126 urls
    search.lumy.live         42 ->  134 urls

Raw counts undersell it, because the *baseline was not answering the dork at
all*: of mectov's 20 default-engine URLs, *zero* were on a gov.br host and zero
were PDFs (they were gemini.google.com locale variants and job boards). With
the roster: 36 on gov.br, 23 PDFs, 21 satisfying both halves of the dork.
The honest headline is therefore **0 -> 21 dork-matching URLs**, not 20 -> 126.

The flip side, also measured: the roster includes engines that do not parse
search operators (wiby, mwmbl, yacy, openlibrary, the wikis), which answer the
literal string and contribute junk like `.../…-filetype-pdf/…`. That is
consistent with this tool's keep-everything default - a dork's answer is
whatever the index returned - and --filter-host/--filter-regex is the remedy
when an operator wants it narrowed.

Checked for the regression this could have caused: over a fixed 16-instance
sample the number of instances that answered at all was **identical** with and
without the roster (1 and 1), so the extra ~1.5KB of cookie and ~1.5KB of query
string does not trip WAFs or cost coverage. It buys breadth per instance
without losing instances.

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
from typing import NamedTuple

from core.assets import load_config_list
from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

# Both lists live in one document because they answer two halves of the same
# question - `instances` is WHERE to search, `engines` is WHAT each instance
# searches with - and neither is useful to this source without the other.
_DATA_FILE = 'searx.json'
_PAGE_SIZE = 10

# Textual categories only - see the module docstring for the measurement.
_CATEGORIES = 'general,it,science,files'


def load_instances() -> list[str]:
    """Public SearXNG base URLs from config/searx.json, trailing '/' stripped.

    Shared with sources/passive/searxbrowser.py, which walks the same pool
    through a browser. A fresh list is returned per call so a caller may
    shuffle it in place - core.assets caches the parsed document, and handing
    out the cached list itself would let one task reorder the pool for every
    other task in the run.
    """
    return [i.rstrip('/') for i in load_config_list(_DATA_FILE, 'instances')]


class EnginePrefs(NamedTuple):
    """One engine roster, rendered for each of the two channels it rides on."""

    params: dict[str, str]
    cookies: dict[str, str]


def engine_prefs() -> EnginePrefs | None:
    """SearXNG's `enabled_engines` preference, or None when expansion is off.

    Shared with sources/passive/searxbrowser.py, which sends the identical
    preference through Playwright instead of httpx.

    **Both keys always travel together**, because SearXNG reads them as a pair:
    `Preferences.parse_dict()` only enters its engine branch on seeing
    `disabled_engines`, then picks `enabled_engines` out of the same mapping.
    Sending the roster on its own is silently a no-op.

    **Sent over a cookie AND the query string on purpose.** SearXNG applies
    preferences from the cookies first and from the merged GET args second, so
    the two are idempotent rather than competing, and whichever channel a given
    instance version honours, the roster lands. An instance honouring neither
    just searches its own defaults - the failure mode is today's behaviour, not
    an error, which is what makes the redundancy free.

    Both channels were verified to work *independently* before the redundancy
    was trusted (mectov, `site:gov.br filetype:pdf`, pages=1): baseline 20 urls,
    URL parameter alone 93, cookie alone 93, both together 110-126. Neither is
    dead weight, and the pair beats either alone because SearXNG re-queries its
    upstreams on every render, so two carriers of the same preference still
    sample the engines twice (the same effect the JSON+HTML pass exploits).

    An empty or missing `engines` list in config/searx.json returns None and
    disables expansion. That is deliberately softer than the missing-instances
    case, which ends the source: instances are the input this source cannot run
    without, whereas the roster is an amplifier on top of a run that works
    regardless.
    """
    engines = load_config_list(_DATA_FILE, 'engines')
    if not engines:
        return None
    joined = ','.join(engines)
    return EnginePrefs(
        params={'disabled_engines': '', 'enabled_engines': joined},
        # Quoted, with the separators octal-escaped - byte-for-byte the form the
        # instance itself used when setting this cookie. Not cosmetic: a comma
        # and a semicolon are cookie *syntax*, and two engine names carry a
        # literal space ('ddg definitions', 'duckduckgo web') which is not legal
        # in an unquoted value at all. A plain comma-joined string loses part of
        # the roster or the whole cookie, depending on the parser.
        cookies={
            'disabled_engines': '',
            'enabled_engines': '"{}"'.format(
                joined.replace('\\', '\\\\').replace(',', '\\054').replace(';', '\\073')
            ),
        },
    )


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
        # load_instances() already returns a fresh list, so shuffling in place
        # here cannot reorder the pool for any other task in the run.
        pool = load_instances()
        if not pool:
            self._vlog(
                1, f'no instances - "instances" in config/{_DATA_FILE} missing or empty'
            )
            return set()
        random.shuffle(pool)

        q = self.query_for(dork)
        urls: set[str] = set()
        healthy = 0
        prefs = engine_prefs()
        if prefs is None:
            self._vlog(
                1,
                f'no engine expansion - "engines" in config/{_DATA_FILE} missing or '
                'empty; instances will search their own default engine set',
            )
        try:
            async with self._make_client(
                headers=browser_headers(configured_ua=self.user_agent),
                cookies=(prefs.cookies if prefs else None),
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
                    # Per instance, beside the unit tick: the URL counter on the
                    # progress line only moves when a whole (source, dork) task
                    # ends otherwise, and this task walks up to _MAX_ATTEMPTS
                    # hosts with a polite_sleep() between each.
                    self._progress.note_urls(found)
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
        # The engine roster rides the query string as well as the cookie set on
        # the client - see engine_prefs() for why both. httpx encodes the commas
        # and the two names containing a space, so the raw list goes in as-is.
        prefs = engine_prefs()
        if prefs:
            params.update(prefs.params)
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
