"""
Intelligence X - phonebook URL selectors.

IntelX indexes leaked dumps, paste sites, darkweb captures and public data
breaches, then extracts typed "selectors" from them. The phonebook search picks
the selector type via `target`: 1 = domains, 2 = emails, **3 = URLs**.

The value here is historical reach: IntelX surfaces URLs from documents and
dumps that were never on the live web and are not in any archive. Its search
term is plain text, not web-search operators.

Requires an API key. Add 'intelx_key' to config/api_keys.json
Reference: https://intelx.io/account?tab=developer
"""
import asyncio

from core.config import get_key
from sources.base import BaseSource, Dork

_BASE = 'https://2.intelx.io'
_TARGET_URLS = 3
_MAX_RESULTS = 100000
_POLL_ATTEMPTS = 6
_POLL_DELAY = 2.0
_STATUS_OK = 0
_STATUS_NO_MORE = 1
_STATUS_NOT_FOUND = 2


class IntelX(BaseSource):
    NAME = 'intelx'
    DESCRIPTION = 'Intelligence X - URL selectors from leaks, pastes and dumps (needs key)'
    CATEGORY = 'leak'
    API_TOKEN_IS_REQUIREMENT = True
    SUPPORTS_OPERATORS = False
    # The search POST below opens a billable server-side job and returns an id
    # the poll loop then depends on. A rotate-and-retry would double-charge the
    # quota and orphan the first search, so this source pins one proxy per
    # fetch instead of rotating mid-flight.
    ROTATE_MID_FETCH = False

    async def fetch(self, dork: Dork) -> set[str]:
        api_key = get_key('intelx_key')
        if not api_key:
            return set()
        urls: set[str] = set()
        term = self.query_for(dork)
        try:
            async with self._make_client() as client:
                resp = await self._post(
                    client,
                    f'{_BASE}/phonebook/search',
                    params={'k': api_key},
                    json={
                        'term': term, 'buckets': [], 'lookuplevel': 0,
                        'maxresults': _MAX_RESULTS, 'timeout': 0,
                        'datefrom': '', 'dateto': '', 'sort': 4, 'media': 0,
                        'terminate': [], 'target': _TARGET_URLS,
                    },
                )
                if resp.status_code == 401:
                    self._vlog(1, 'invalid API key'); return set()
                if resp.status_code != 200:
                    self._vlog(1, f'search init failed: HTTP {resp.status_code}'); return set()
                search_id = resp.json().get('id', '')
                if not search_id:
                    self._vlog(1, 'no search id returned'); return set()

                for _ in range(_POLL_ATTEMPTS):
                    await asyncio.sleep(_POLL_DELAY)
                    result = await self._get(
                        client, f'{_BASE}/phonebook/result',
                        params={'k': api_key, 'id': search_id, 'limit': _MAX_RESULTS, 'offset': 0},
                    )
                    if result.status_code != 200:
                        self._vlog(1, f'result fetch failed: HTTP {result.status_code}')
                        break
                    data = result.json()
                    phonebook = data.get('phonebook', data)
                    selectors = phonebook.get('selectors', []) or phonebook.get('urls', [])
                    for entry in selectors:
                        if isinstance(entry, str):
                            candidate = entry.strip()
                        elif isinstance(entry, dict):
                            candidate = (entry.get('selectorvalue') or '').strip()
                        else:
                            continue
                        if candidate:
                            urls.add(candidate)
                    status = data.get('status', _STATUS_OK)
                    if status in (_STATUS_NO_MORE, _STATUS_NOT_FOUND) or urls:
                        break
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
