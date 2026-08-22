"""
grep.app - code search across public repositories.

Searches the indexed source of public GitHub repositories for the dork and
pulls full URLs out of the matching code snippets. Reaches a surface no web
index touches: API endpoints hardcoded in client code, CI configs, SDK
examples and `.env` samples.

grep.app's own query language is plain terms / regex, not web-search
operators, so this engine downgrades operator dorks automatically.

No API key required. Reference: https://grep.app
"""
import html
import re

from sources.base import BaseSource, Dork

_ENDPOINT = 'https://grep.app/api/search'
_TAG_RE = re.compile(r'<[^>]+>')
_URL_RE = re.compile(r'''https?://[^\s'"<>)\]}\\]+''')
_HEADERS = {'Accept': 'application/json', 'Accept-Language': 'en-US,en;q=0.9'}


class GrepApp(BaseSource):
    NAME = 'grep_app'
    DESCRIPTION = 'grep.app code search - URLs hardcoded in public repositories (no auth)'
    CATEGORY = 'code'
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        urls: set[str] = set()
        q = self.query_for(dork)
        try:
            async with self._make_client(headers=_HEADERS) as client:
                for page in range(1, self.pages + 1):
                    params = {'q': q, 'page': page, 'format': 'e'}
                    resp = await self._get(client, _ENDPOINT, params=params)
                    if resp.status_code == 429:
                        self._vlog(1, 'rate limited - stopping pagination')
                        break
                    if resp.status_code != 200:
                        self._vlog(1, f'HTTP {resp.status_code}')
                        break
                    hits = resp.json().get('hits', {}).get('hits', [])
                    if not hits:
                        break
                    for hit in hits:
                        snippet = hit.get('content', {}).get('snippet', '')
                        if not snippet:
                            continue
                        text = html.unescape(_TAG_RE.sub('', snippet))
                        for match in _URL_RE.finditer(text):
                            urls.add(match.group(0).rstrip('.,;:'))
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
