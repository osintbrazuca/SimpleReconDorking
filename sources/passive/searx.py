"""
SearXNG - federated metasearch, queried through its JSON API.

SearXNG aggregates dozens of upstream engines (Google, Bing, Brave, Startpage,
Wikipedia, and more) behind one privacy-respecting front. Public instances vary
in uptime and often rate-limit aggressively, so this rotates through a short
list of known-public instances (assets/txt/searx_instances.txt) and treats a
non-200/non-JSON response as "try the next instance", not an error.

Because it fans out to multiple upstream engines per query, one working
instance can be worth several of the direct scrapers combined - when a public
instance is healthy and not rate-limiting, this tends to be the highest-yield
keyless engine in the catalog.
"""
import json

from core.assets import load_lines
from sources.base import BaseSource, Dork
from sources._search_common import browser_headers, polite_sleep

_INSTANCES_FILE = 'searx_instances.txt'
_PAGE_SIZE = 10


class Searx(BaseSource):
    NAME = 'searx'
    DESCRIPTION = 'SearXNG - federated metasearch across public instances (no key)'
    CATEGORY = 'web'

    async def fetch(self, dork: Dork) -> set[str]:
        instances = load_lines(_INSTANCES_FILE)
        if not instances:
            self._vlog(1, f'no instances - assets/txt/{_INSTANCES_FILE} missing or empty')
            return set()

        q = self.query_for(dork)
        urls: set[str] = set()
        try:
            async with self._make_client(
                headers=browser_headers(configured_ua=self.user_agent)
            ) as client:
                for instance in instances:
                    found = await self._search_instance(client, instance.rstrip('/'), q)
                    if found:
                        self._vlog(1, f'{len(found)} url(s) from {instance}')
                        urls |= found
                        break  # one healthy instance is enough; don't hammer the pool
                    await polite_sleep(1.0)
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)

    async def _search_instance(self, client, instance: str, q: str) -> set[str]:
        found: set[str] = set()
        for page in range(1, self.pages + 1):
            try:
                resp = await self._get(
                    client, f'{instance}/search',
                    params={'q': q, 'format': 'json', 'pageno': page},
                )
            except Exception as e:
                self._log_exc(e); return found
            if resp.status_code != 200:
                return found
            try:
                data = json.loads(resp.text)
            except (json.JSONDecodeError, ValueError):
                return found
            results = data.get('results') or []
            if not results:
                return found
            for item in results:
                url = item.get('url', '') if isinstance(item, dict) else ''
                if url:
                    found.add(url)
            if len(results) < _PAGE_SIZE:
                return found
            if page < self.pages:
                await polite_sleep(1.0)
        return found
