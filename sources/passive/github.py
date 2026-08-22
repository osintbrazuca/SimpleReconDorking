"""
GitHub code search - URLs hardcoded in public source.

Searches GitHub's code index for the dork and extracts full URLs from the
matched code fragments. Highest-yield engine for *API surface* specifically:
base URLs, versioned endpoints and callback paths live in client SDKs, mobile
app config, Terraform, CI pipelines and committed `.env` samples.

GitHub's code search uses its own qualifier syntax (`repo:`, `path:`,
`language:`...), not web-search operators, so this engine downgrades operator
dorks to plain terms automatically.

Requires a GitHub personal access token (scope: `public_repo`).
Add 'github_token' to config/api_keys.json - https://github.com/settings/tokens
"""
import asyncio
import re

from core.config import get_key
from sources.base import BaseSource, Dork

_ENDPOINT = 'https://api.github.com/search/code'
_PER_PAGE = 100
# Authenticated code search is capped at 10 requests/minute. Pacing the pages
# keeps the whole run inside the budget instead of burning it and taking a 403.
_PAGE_DELAY = 6.0
_URL_RE = re.compile(r'''https?://[^\s'"<>)\]}\\`]+''')


class Github(BaseSource):
    NAME = 'github'
    DESCRIPTION = 'GitHub code search - URLs hardcoded in public repositories (needs token)'
    CATEGORY = 'code'
    API_TOKEN_IS_REQUIREMENT = True
    SUPPORTS_OPERATORS = False

    async def fetch(self, dork: Dork) -> set[str]:
        token = get_key('github_token')
        if not token:
            return set()
        headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3.text-match+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        urls: set[str] = set()
        q = self.query_for(dork)
        try:
            async with self._make_client(headers=headers) as client:
                for page in range(1, self.pages + 1):
                    params = {'q': q, 'per_page': _PER_PAGE, 'page': page}
                    resp = await self._get(client, _ENDPOINT, params=params)
                    if resp.status_code == 401:
                        self._vlog(1, 'invalid token'); break
                    if resp.status_code == 403:
                        self._vlog(1, 'rate limit reached - stopping pagination'); break
                    if resp.status_code == 422:
                        self._vlog(1, 'query not accepted by the search API'); break
                    if resp.status_code != 200:
                        self._vlog(1, f'HTTP {resp.status_code}'); break
                    data = resp.json()
                    items = data.get('items', [])
                    if not items:
                        break
                    for item in items:
                        for match in item.get('text_matches', []):
                            fragment = match.get('fragment', '')
                            for m in _URL_RE.finditer(fragment):
                                urls.add(m.group(0).rstrip('.,;:'))
                    total = data.get('total_count', 0)
                    if page * _PER_PAGE >= min(total, 1000):
                        break
                    if page < self.pages:
                        await asyncio.sleep(_PAGE_DELAY)
        except Exception as e:
            self._log_exc(e)
        return self._filter_urls(urls)
