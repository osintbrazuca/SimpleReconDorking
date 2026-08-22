"""
Brave Search API - indexed URLs for the dork.

Brave offers a free tier (rate-limited, roughly 1 query/second), which is why
pages are fetched sequentially rather than concurrently. Full operator support.

Key: `brave` in config/api_keys.json - https://brave.com/search/api/
"""
import asyncio

from sources.base import BaseSource, Dork
from core.config import get_key

_ENDPOINT = 'https://api.search.brave.com/res/v1/web/search'
_PAGE_SIZE = 20


class Brave(BaseSource):
    NAME = 'brave'
    DESCRIPTION = 'Brave Search API - full operator support (needs key)'
    CATEGORY = 'web'
    API_TOKEN_IS_REQUIREMENT = True

    async def fetch(self, dork: Dork) -> set[str]:
        api_key = get_key('brave')
        if not api_key:
            return set()
        urls: set[str] = set()
        headers = {'X-Subscription-Token': api_key, 'Accept': 'application/json'}
        try:
            async with self._make_client(headers=headers) as client:
                for page in range(self.pages):
                    params = {
                        'q': self.query_for(dork),
                        'count': str(_PAGE_SIZE),
                        'offset': str(page),
                    }
                    resp = await self._get(client, _ENDPOINT, params=params)
                    if resp.status_code == 429:
                        self._vlog(1, 'rate limited - stopping pagination')
                        break
                    if resp.status_code != 200:
                        self._vlog(1, f'HTTP {resp.status_code} - check the API key')
                        break
                    results = (resp.json().get('web') or {}).get('results') or []
                    if not results:
                        break
                    for item in results:
                        url = item.get('url', '') if isinstance(item, dict) else ''
                        if url:
                            urls.add(url)
                    if len(results) < _PAGE_SIZE:
                        break
                    await asyncio.sleep(1)
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
