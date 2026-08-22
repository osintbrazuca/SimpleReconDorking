"""
Marginalia Search - an independent, non-commercial web index.

Marginalia runs its own crawler with an index deliberately biased toward the
small, non-commercial web that Google and Bing rank into oblivion. That makes
it a genuinely different corpus for dorking: it surfaces pages the other
engines never see.

Uses the official API with the documented **public** key, so no credentials
are needed: https://api.marginalia.nu/public/search/<query>

The public API takes a **free-text query, not search operators** - passing
`site:example.com` returns an error. SUPPORTS_OPERATORS = False makes
BaseSource hand this module Dork.plain_terms() automatically.

The service is small and rate-limits hard: an explicit "currently barraged by
queries from bots" page shows up after roughly three queries in a loop, so
paging is short and paced, and any failure just ends pagination quietly.
"""
import json

from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_ENDPOINT = 'https://api.marginalia.nu/public/search/{query}'


class Marginalia(BaseSource):
    NAME = 'marginalia'
    DESCRIPTION = 'Marginalia Search - independent non-commercial index (free-text only)'
    CATEGORY = 'web'
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        from urllib.parse import quote

        urls: set[str] = set()
        q = quote(self.query_for(dork), safe='')
        try:
            async with self._make_client(
                headers=browser_headers(configured_ua=self.user_agent)
            ) as client:
                for page in range(1, self.pages + 1):
                    url = _ENDPOINT.format(query=q)
                    if page > 1:
                        url = f'{url}?page={page}'
                    try:
                        resp = await self._get(client, url)
                    except Exception as e:
                        self._log_exc(e); break
                    if resp.status_code != 200:
                        self._vlog(1, f'HTTP {resp.status_code} - likely rate limited')
                        break
                    try:
                        data = json.loads(resp.text)
                    except (json.JSONDecodeError, ValueError):
                        self._vlog(1, 'non-JSON response - rate limited, stopping')
                        break
                    results = data.get('results') or []
                    if not results:
                        break
                    for item in results:
                        if isinstance(item, dict) and item.get('url'):
                            urls.add(item['url'])
                    total_pages = data.get('pages') or 1
                    if page >= min(total_pages, self.pages):
                        break
                    await polite_sleep()
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
