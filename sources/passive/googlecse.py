"""
Google via public Custom Search Engines (no API key).

Adapted from string-x's clc/googlecse.py. Instead of Google's official Custom
Search JSON API (which needs a billing-backed key), this drives the CSE *widget*
endpoint that any embedded search box uses, against a list of third-party
**public** CSE IDs shipped in assets/txt/google_cse_id.txt. That is what makes
Google coverage possible with zero credentials - and it works where scraping
google.com/search does not.

Two-step flow per CSE ID:
  1. GET cse.google.com/cse/cse.js?cx=<ID>   -> "cse_token" + "cselibVersion"
  2. GET cse.google.com/cse/element/v1?...   -> JSON-ish body with "url" fields

>>> THE `rurl` PARAMETER IS LOAD-BEARING. <<<
The element/v1 endpoint answers 403 without it and 200 with it - verified
empirically. It must stay a nested, NON-url-encoded copy of the CSE page URL,
exactly as built below. Do not "clean this up" by encoding it or dropping it.

Caveat for dorking: a public CSE can be scoped to specific sites, so an operator
dork with its own `site:` may be intersected with the CSE's own scope. It still
respects free-text and most operators; treat it as broad Google coverage rather
than a precise dork runner.
"""
import random
import re
from urllib.parse import quote

from core.assets import load_lines
from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_CSE_ID_FILE = 'google_cse_id.txt'
_CSE_JS = 'https://cse.google.com/cse/cse.js?cx={cx}'
_ELEMENT = 'https://cse.google.com/cse/element/v1'
_TOKEN_RE = re.compile(r'"cse_token":\s*"([^"]+)"')
_LIBVER_RE = re.compile(r'"cselibVersion":\s*"([^"]+)"')
_URL_RE = re.compile(r'"url":\s*"([^"]+)"')

_IDS_PER_RUN = 3
_PAGE_SIZE = 20


class Googlecse(BaseSource):
    NAME = 'googlecse'
    DESCRIPTION = 'Google via public Custom Search Engines - no API key, works reliably'
    CATEGORY = 'web'
    # The two-step flow binds cse_token to the IP that fetched cse.js; spending
    # it from a different IP on the element/v1 call answers 403. Rotating
    # mid-fetch would therefore manufacture the very failure it is trying to
    # escape, so this source pins one proxy for the whole fetch.
    ROTATE_MID_FETCH = False

    async def fetch(self, dork: Dork) -> set[str]:
        cse_ids = list(load_lines(_CSE_ID_FILE))
        if not cse_ids:
            self._vlog(1, f'no CSE IDs - assets/txt/{_CSE_ID_FILE} missing or empty')
            return set()
        random.shuffle(cse_ids)
        chosen = cse_ids[:_IDS_PER_RUN]
        q = self.query_for(dork)
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers(configured_ua=self.user_agent)
            ) as client:
                for cx in chosen:
                    try:
                        found = await self._search_with(client, cx, q)
                    except Exception as e:
                        self._log_exc(e); continue
                    if found:
                        self._vlog(1, f'{len(found)} url(s) from CSE {cx[:22]}…')
                        urls |= found
                    await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)

    async def _search_with(self, client, cx: str, q: str) -> set[str]:
        resp = await self._get(client, _CSE_JS.format(cx=cx))
        if resp.status_code != 200:
            return set()
        token = _TOKEN_RE.search(resp.text)
        libver = _LIBVER_RE.search(resp.text)
        if not token or not libver:
            return set()
        found: set[str] = set()
        for page in range(self.pages):
            start = page * _PAGE_SIZE
            rurl = f'https://cse.google.com/cse?cx={cx}&q={q}&num=500&hl=en&as_qdr=all&start={start}&sa=N'
            url = (
                f'{_ELEMENT}?rsz=filtered_cse&num={_PAGE_SIZE}&hl=en&source=gcsc'
                f'&start={start}&cselibv={libver.group(1)}&cx={cx}&q={quote(q)}'
                f'&safe=off&rurl={rurl}&cse_tok={token.group(1)}'
                f'&exp=cc,apo&callback=google.search.cse.api5630'
            )
            resp = await self._get(
                client, url, headers={'Referer': f'https://cse.google.com/cse?cx={cx}'}
            )
            if resp.status_code != 200:
                break
            page_urls = {u for u in _URL_RE.findall(resp.text) if u.startswith('http')}
            if not page_urls:
                break
            found |= page_urls
            if page + 1 < self.pages:
                await polite_sleep(1.0)
        return found
