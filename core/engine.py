"""
Dorking core.

The unit of work is a Dork (see sources/base.py), not a host. Engine's job is:
  1. Build the dork list - from -d/--dork, -D/--dork-file, or the built-in
     catalog via --dork-category, each expanded with -t/--target when the
     template needs one.
  2. Run every selected source over every dork.
  3. Merge, dedupe, and hand the union to output/formatter.py.

This mirrors SimpleReconURL's Engine (dedup set, semaphore gate, per-source
counters) with the seed-URL/round-loop machinery removed -
dorking has no crawl frontier to recurse into, only a flat query list.
"""
import asyncio
import contextlib
import json
import random
import re
import sys
from argparse import Namespace

import core.colors as colors
from core.dedup import DeduplicatedSet
from core.profiles import get_profile, profile_options
from core.progress import NullProgress, Progress
from sources import SOURCES
from sources.base import Dork


def _read_lines(path: str) -> list[str]:
    try:
        with open(path, 'r') as fh:
            return [
                line.strip() for line in fh
                if line.strip() and not line.strip().startswith('#')
            ]
    except FileNotFoundError:
        print(colors.format_msg(f'[!] File not found: {path}'))
        sys.exit(1)


def _read_json_object(path: str) -> dict:
    """Load a JSON object of header name/value pairs from *path*.

    Same hard-fail style as core/run_config.py::load_run_config() - this is
    an operator-supplied path passed explicitly via --header-file, so a
    missing file or malformed JSON should stop the run with a clear message,
    not degrade to an empty dict.
    """
    try:
        with open(path, 'r') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(colors.format_msg(f'[!] File not found: {path}'))
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(colors.format_msg(f'[!] Invalid JSON in {path}: {exc}'))
        sys.exit(1)
    if not isinstance(data, dict):
        print(colors.format_msg(f'[!] {path} must be a JSON object of header name/value pairs'))
        sys.exit(1)
    return {str(k): str(v) for k, v in data.items()}


def build_dorks(args: Namespace) -> list[Dork]:
    """Resolve -d / -D / --dork-category (+ --stdin) into the final Dork list.

    Every source is additive - an operator can combine a one-off -d with a
    whole --dork-category run in a single invocation. Templates that need
    {TARGET} and get no -t are skipped with a warning rather than sent
    verbatim (a literal '{TARGET}' in a live query is noise, not a query).
    """
    from core import dorks as catalog

    target: str | None = getattr(args, 'target', None)
    templates: list[tuple[str, str | None]] = []  # (template, category)

    if getattr(args, 'dork', None):
        templates.append((args.dork, None))

    if getattr(args, 'dork_file', None):
        for line in _read_lines(args.dork_file):
            templates.append((line, None))

    if getattr(args, 'stdin', False) or (
        not templates and not getattr(args, 'dork_category', None) and not sys.stdin.isatty()
    ):
        for line in sys.stdin:
            line = line.strip()
            if line and not line.startswith('#'):
                templates.append((line, None))

    categories: list[str] = []
    if getattr(args, 'dork_category', None):
        requested = {c.strip() for c in args.dork_category.split(',') if c.strip()}
        available = set(catalog.categories())
        unknown = requested - available
        if unknown:
            print(colors.format_msg(
                f'[!] Unknown dork categor{"y" if len(unknown) == 1 else "ies"}: '
                f'{", ".join(sorted(unknown))}. Run --list-category to see the available ones.'
            ), file=sys.stderr)
            sys.exit(2)
        categories = sorted(requested)

    family = catalog.family_for_target(target)
    for cat in categories:
        for line in catalog.load_category(cat, family):
            templates.append((line, cat))

    dorks: list[Dork] = []
    seen: set[str] = set()
    skipped = 0
    for template, category in templates:
        expanded = catalog.expand(template, target)
        if expanded is None:
            skipped += 1
            continue
        d = Dork.of(expanded, raw=template, target=target, category=category)
        if d.query in seen:
            continue
        seen.add(d.query)
        dorks.append(d)

    if skipped:
        print(colors.format_msg(
            f'[!] {skipped} dork(s) skipped: need -t/--target to fill in {{TARGET}}'
        ), file=sys.stderr)

    return dorks


class Engine:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.verbose: int = getattr(args, 'verbose', 0) or 0
        self.quiet: bool = getattr(args, 'quiet', False)
        self._progress: Progress = NullProgress()

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def log(self, msg: str) -> None:
        if not self.quiet:
            self._progress.clear()
            print(colors.format_msg(msg))

    def vlog(self, level: int, msg: str) -> None:
        if self.verbose >= level and not self.quiet:
            self._progress.clear()
            print(colors.format_msg(msg))

    def _abort(self, msg: str) -> None:
        """Stop the run on a selection mistake rather than falling through to
        'run every source' - printed directly so it survives --quiet/--no-banner.
        """
        print(colors.format_msg(f'[!] {msg}'), file=sys.stderr)
        sys.exit(2)

    def _parse_gate(self, raw: str | None, valid: set[str], flag: str, kind: str = 'source') -> set[str]:
        """Comma-separated allow-list, validated fail-closed against *valid*.

        Shared by --proxy-source/--proxy-profile, --ua-source/--ua-profile and
        --header-source/--header-profile - same idiom as --sources/--exclude/
        --category: an unknown name aborts (exit 2) instead of silently
        matching nothing. An empty return means "no restriction" to the
        caller's gate check.
        """
        names = {s.strip() for s in (raw or '').split(',') if s.strip()}
        if names:
            unknown = names - valid
            if unknown:
                self._abort(
                    f'Unknown {kind}(s) in {flag}: {", ".join(sorted(unknown))}.'
                )
        return names

    # ------------------------------------------------------------------
    # Source selection
    # ------------------------------------------------------------------

    def _select_sources(self) -> dict:
        profile_name: str | None = getattr(self.args, 'profile', None)
        if profile_name:
            profile = get_profile(profile_name)
            if profile is None:
                from core.profiles import profile_names
                self._abort(
                    f'Unknown profile: {profile_name!r}. '
                    f'Available: {", ".join(profile_names())}'
                )
            sources_sel = profile.get('sources', 'all')
            from core.run_config import apply_run_config
            apply_run_config(self.args, profile_options(profile_name))
            if sources_sel == 'all' or sources_sel is None:
                sources = dict(SOURCES)
            else:
                requested = set(sources_sel)
                sources = {k: v for k, v in SOURCES.items() if k in requested}
        elif getattr(self.args, 'sources', None) is not None:
            # `is not None`, not truthiness: --sources '' means "none selected",
            # not "unset -> run everything".
            requested = {s.strip() for s in self.args.sources.split(',') if s.strip()}
            unknown = requested - set(SOURCES)
            if unknown:
                self._abort(
                    f'Unknown source(s): {", ".join(sorted(unknown))}. '
                    'Run --list-sources to see the available ones.'
                )
            sources = {k: v for k, v in SOURCES.items() if k in requested}
        elif getattr(self.args, 'category', None):
            from sources import in_categories
            requested = {c.strip() for c in self.args.category.split(',') if c.strip()}
            from sources import categories as all_categories
            unknown = requested - set(all_categories())
            if unknown:
                self._abort(
                    f'Unknown source categor{"y" if len(unknown) == 1 else "ies"}: '
                    f'{", ".join(sorted(unknown))}.'
                )
            sources = in_categories(requested)
        else:
            sources = dict(SOURCES)

        exclude = {
            s.strip()
            for s in (getattr(self.args, 'exclude', '') or '').split(',')
            if s.strip()
        }
        if exclude:
            sources = {k: v for k, v in sources.items() if k not in exclude}

        # --no-tor, applied here for the same reason --exclude is: the four
        # branches above are mutually exclusive, so a filter placed inside any
        # of them would miss the others. It also has to run AFTER the profile
        # branch, which is where apply_run_config() lands a profile's `options`
        # block - a profile setting no_tor would otherwise be read before it
        # was applied.
        #
        # Keyed on REQUIRES_TOR, never on CATEGORY == 'darkweb': six sources are
        # darkweb but only four are onion-only. onionsearch and tor66web reach
        # their indexes over plain clearnet HTTP and are precisely what still
        # answers on a machine with no daemon - dropping them here would gut the
        # flag for the very operator asking for it.
        if getattr(self.args, 'no_tor', False):
            skipped = sorted(
                name for name, cls in sources.items()
                if getattr(cls, 'REQUIRES_TOR', False)
            )
            if skipped:
                sources = {k: v for k, v in sources.items() if k not in skipped}
                # One line for the whole set. Letting these run instead costs
                # len(skipped) x len(dorks) copies of the same "Tor not
                # reachable" hint, since the plan is a cartesian product.
                self.vlog(
                    1,
                    f'[*] [no-tor] skipping {len(skipped)} source(s) that need a Tor '
                    f'daemon: {", ".join(skipped)}',
                )

        return sources

    # ------------------------------------------------------------------
    # Single (source, dork) runner
    # ------------------------------------------------------------------

    async def _run_one(
        self, name: str, source, dork: Dork, dedup: DeduplicatedSet,
        gate: asyncio.Semaphore, counts: dict, extras: dict,
        url_sources: dict, url_dorks: dict,
    ) -> None:
        try:
            pool = getattr(source, '_pool', None)
            if pool is not None and pool.exhausted and not pool.fallback_direct:
                # The pool died in an earlier task. Skip rather than dispatch:
                # gather(return_exceptions=True) waits for every task, and on a
                # catalog-sized run that is thousands of them queuing up
                # against a pool that cannot serve any of them.
                counts.setdefault(name, 0)
                return
            async with gate:
                # Inside the semaphore, not before it: gather() dispatches
                # every task at once, so announcing the dork at dispatch time
                # left 'now' showing the LAST task in the queue rather than
                # one actually running.
                self._progress.start(dork.query)
                found = await source.fetch(dork)
            new_items = dedup.update(found)
            counts[name] = counts.get(name, 0) + len(new_items)
            if new_items:
                self.vlog(1, f'[*] [{name}] "{dork.query}" +{len(new_items)} urls')
            else:
                self.vlog(2, f'[!] [{name}] "{dork.query}" 0 new urls')
            for key in extras:
                extras[key].update(source.extras.get(key, set()))
            for u in found:
                url_sources.setdefault(u, name)
                url_dorks.setdefault(u, dork.query)
        except Exception as exc:
            self.vlog(1, f'[x] [{name}] "{dork.query}" error: {exc}')
            counts.setdefault(name, 0)
        finally:
            # advance() first: aclose() must never be able to skip the progress
            # bar, and since this is a finally block a raise here would replace
            # whatever exception is already in flight (ProxyExhausted included).
            self._progress.advance(len(dedup.as_set()))
            with contextlib.suppress(Exception):
                await source.aclose()

    # ------------------------------------------------------------------
    # Main entrypoint
    # ------------------------------------------------------------------

    async def run(self) -> dict:
        dorks = build_dorks(self.args)
        if not dorks:
            print(colors.format_msg(
                '[!] No dorks to run. Use -d, -D, --dork-category, or pipe them via --stdin.'
            ))
            sys.exit(1)

        sources = self._select_sources()
        if not sources:
            self._abort(
                'No sources selected - check '
                '--sources/--profile/--category/--exclude/--no-tor.'
            )

        rate_limit: int = getattr(self.args, 'rate_limit', 0) or 0
        # Built here, AFTER _select_sources() above - a profile's `options`
        # block is applied inside it, so a profile-supplied proxy would be lost
        # if the pool were assembled any earlier.
        from core.proxy import ProxyPool
        pool = ProxyPool.from_args(self.args)
        if pool:
            self.log(f'[*] [proxy] {pool.summary()}')

        from core.profiles import profile_names
        valid_profiles = set(profile_names())
        active_profile: str | None = getattr(self.args, 'profile', None)

        def _in_gate(name: str, sources_gate: set[str], profiles_gate: set[str]) -> bool:
            if sources_gate and name not in sources_gate:
                return False
            if profiles_gate and active_profile not in profiles_gate:
                return False
            return True

        proxy_sources = self._parse_gate(getattr(self.args, 'proxy_source', None), set(SOURCES), '--proxy-source')
        proxy_profiles = self._parse_gate(getattr(self.args, 'proxy_profile', None), valid_profiles, '--proxy-profile', kind='profile')

        def _wants_proxy(name: str) -> bool:
            return pool is not None and _in_gate(name, proxy_sources, proxy_profiles)

        # --user-agent/--ua stays a raw string; a value equal to the tool's
        # own literal default counts as "not set" (effective_ua() treats it
        # the same way) so a source outside the --ua-source/--ua-profile gate
        # falls back to the normal per-request rotation from
        # assets/txt/user_agents.txt exactly as it does today.
        raw_user_agent: str = getattr(self.args, 'user_agent', 'SimpleReconDorking/1') or 'SimpleReconDorking/1'
        custom_ua: str | None = raw_user_agent if raw_user_agent != 'SimpleReconDorking/1' else None
        ua_pool: list[str] = _read_lines(self.args.ua_file) if getattr(self.args, 'ua_file', None) else []
        ua_sources = self._parse_gate(getattr(self.args, 'ua_source', None), set(SOURCES), '--ua-source')
        ua_profiles = self._parse_gate(getattr(self.args, 'ua_profile', None), valid_profiles, '--ua-profile', kind='profile')

        def _ua_for(name: str) -> str:
            # ua_pool wins over a single --user-agent/--ua value when both
            # are given - not confirmed with the operator, flagged in the plan.
            if not (ua_pool or custom_ua) or not _in_gate(name, ua_sources, ua_profiles):
                return 'SimpleReconDorking/1'
            return random.choice(ua_pool) if ua_pool else custom_ua

        headers_dict: dict = {}
        if getattr(self.args, 'header_file', None):
            headers_dict.update(_read_json_object(self.args.header_file))
        if getattr(self.args, 'header', None):
            # --header (inline) wins over --header-file on key collision -
            # not confirmed with the operator, flagged in the plan.
            headers_dict.update(json.loads(self.args.header))
        header_sources = self._parse_gate(getattr(self.args, 'header_source', None), set(SOURCES), '--header-source')
        header_profiles = self._parse_gate(getattr(self.args, 'header_profile', None), valid_profiles, '--header-profile', kind='profile')

        def _headers_for(name: str) -> dict | None:
            if not headers_dict or not _in_gate(name, header_sources, header_profiles):
                return None
            return headers_dict

        pages: int = max(1, int(getattr(self.args, 'pages', 2) or 2))
        tor_proxy: str = (
            getattr(self.args, 'tor_proxy', None) or 'socks5h://127.0.0.1:9050'
        )

        filter_host: str | None = getattr(self.args, 'filter_host', None)
        filter_strings = [
            s.strip() for s in (getattr(self.args, 'filter_string', '') or '').split(',')
            if s.strip()
        ]
        if getattr(self.args, 'filter_file', None):
            filter_strings += _read_lines(self.args.filter_file)
        filter_regex_raw: str | None = getattr(self.args, 'filter_regex', None)
        filter_regex = re.compile(filter_regex_raw) if filter_regex_raw else None

        dedup = DeduplicatedSet()
        gate = asyncio.Semaphore(max(1, getattr(self.args, 'threads', 8) or 8))
        counts: dict = {}
        extras: dict = {'urls_filtered': set()}
        url_sources: dict = {}
        url_dorks: dict = {}

        from core import system_db
        system_db.log_command(' '.join(sys.argv), targets=getattr(self.args, 'target', '') or '')

        def _make_source(name: str, cls):
            # A Tor-only source gets --tor-proxy through the constructor and
            # no pool: .onion has no public DNS, so the clearnet pool is not a
            # substitute, and the two families are meant to coexist in one run
            # (--proxy keeps governing the clearnet sources only).
            if getattr(cls, 'REQUIRES_TOR', False):
                routing = {'proxy': tor_proxy, 'proxy_pool': None}
            else:
                routing = {'proxy': None, 'proxy_pool': (pool if _wants_proxy(name) else None)}
            return cls(
                timeout=self.args.timeout,
                rate_limit=rate_limit,
                # Quiet wins over verbosity for the SOURCES, because
                # BaseSource._vlog() prints to stdout and has no quiet check of
                # its own (Engine.vlog does). Without this, -q/--no-banner -
                # which promises "only the final URL list" - would splice
                # '[*] [searx] ...' lines into the URL stream that
                # `... --no-banner | httpx -silent` consumes. Latent until -v 1
                # became the default; now it is the default path.
                # self.verbose stays untouched, so `include_extras` (-v 3) still
                # governs data in the output/DB, which quiet is not about.
                verbose=0 if self.quiet else self.verbose,
                **routing,
                user_agent=_ua_for(name),
                pages=pages,
                filter_host=filter_host,
                filter_strings=filter_strings or None,
                filter_regex=filter_regex,
                extra_headers=_headers_for(name),
                progress=self._progress,
            )

        plan = [(name, cls, dork) for dork in dorks for name, cls in sources.items()]

        self.log(f"\n{'-' * 60}")
        self.log(f'[*] Dorks: {len(dorks)}  |  Sources: {len(sources)}  |  Runs: {len(plan)}')
        self.log(f"{'-' * 60}")

        self._progress = Progress(
            total=len(plan), baseline=0,
            enabled=not self.quiet and not getattr(self.args, 'no_progress', False),
        )
        try:
            outcomes = await asyncio.gather(
                *[
                    self._run_one(
                        name, _make_source(name, cls), dork, dedup, gate,
                        counts, extras, url_sources, url_dorks,
                    )
                    for name, cls, dork in plan
                ],
                return_exceptions=True,
            )
        finally:
            self._progress.finish()
            self._progress = NullProgress()

        # ProxyExhausted is a BaseException precisely so it survives every
        # source's own `except Exception`; gather hands it back here as a
        # result rather than raising.
        from core.proxy import ProxyExhausted
        for outcome in outcomes:
            if isinstance(outcome, ProxyExhausted):
                self._abort(f'[proxy] {outcome}')

        urls = dedup.as_set()
        extras['urls_filtered'] -= urls
        self.log(f'\n[+] Total unique URLs found: {len(urls)}')

        include_extras = self.verbose >= 3

        result = {
            'seed': getattr(self.args, 'target', '') or '(no target)',
            'dorks': [d.query for d in dorks],
            'urls': urls,
            'sources': counts,
            'url_sources': url_sources,
            'url_dorks': url_dorks,
            'extras': extras if include_extras else {},
        }

        db_path: str | None = getattr(self.args, 'db', None)
        if db_path:
            from output import db
            db_news: bool = getattr(self.args, 'db_news', False)
            if db_news:
                known = db.load_known(db_path, result['seed'])
                result = db.filter_new(result, known)
                db.save_result(db_path, result)
                self.log(f'[+] [db-news] {len(result["urls"])} new url(s) since last run -> {db_path}')
            else:
                db.save_result(db_path, result)
                self.log(f'[+] [db] saved {len(result["urls"])} url(s) to {db_path}')

        from output.formatter import save_output
        save_output(
            results=[result],
            fmt=self.args.output,
            outfile=getattr(self.args, 'outfile', None),
            quiet=self.quiet,
            network_map=getattr(self.args, 'network_map', False),
            network_html_file=getattr(self.args, 'network_html', None),
        )
        return result
