import argparse

from core.profiles import load_profiles, profile_names
from core import dorks as catalog
from core.proxy import ROTATE_MODES
from sources import SOURCES, categories as source_categories

ALL_SOURCES = list(SOURCES)

MAX_PAGES = 20


def _pages(value: str) -> int:
    """Validate --pages: an int in 1..MAX_PAGES.

    Fails closed like the source-selection checks in Engine._abort(): an out
    of range value stops the run (argparse exits 2) instead of being clamped,
    so a typo can never silently turn into a much larger amount of traffic
    against every selected source.
    """
    try:
        pages = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: '{value}'")
    if not 1 <= pages <= MAX_PAGES:
        raise argparse.ArgumentTypeError(
            f'must be between 1 and {MAX_PAGES} (got {pages})'
        )
    return pages


def _nonneg(flag: str):
    """Validator factory for the proxy counters: an int >= 0.

    Same fail-closed spirit as _pages - a typo stops the run instead of being
    quietly clamped, since these numbers govern how much traffic a bad pool can
    generate.
    """
    def _check(value: str) -> int:
        try:
            n = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"invalid int value: '{value}'")
        if n < 0:
            raise argparse.ArgumentTypeError(f'{flag} must be >= 0 (got {n})')
        return n
    return _check


def _status_list(value: str) -> str:
    """Validate --proxy-rotate-status at parse time, returning it unchanged.

    The pool re-parses the string anyway (a run-config can supply it too, and
    that path never touches argparse), but validating here means a typo is
    caught even when no proxy is configured - matching how every other flag in
    this CLI fails closed rather than being quietly ignored.
    """
    from core.proxy import parse_status_list

    ok, bad = parse_status_list(value)
    if bad:
        raise argparse.ArgumentTypeError(
            f'not an HTTP status code: {", ".join(bad)}'
        )
    return value


def _regex(flag: str):
    """Validator factory for a single regex pattern (--filter-regex,
    --proxy-rotate-regex): compiles it to catch a typo before any network
    activity, but returns the ORIGINAL STRING unchanged - a --config file
    value never touches argparse's type=, so the real compile happens again
    at the point of use (same reasoning as _status_list above).
    """
    import re

    def _check(value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise argparse.ArgumentTypeError(f'{flag}: invalid regex: {exc}')
        return value
    return _check


def _json_object(flag: str):
    """Validator factory for a single JSON object (--header): confirms it
    parses and is an object, but returns the ORIGINAL STRING unchanged - same
    reasoning as _regex above, a --config file value never touches this.
    """
    import json

    def _check(value: str) -> str:
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise argparse.ArgumentTypeError(f'{flag}: invalid JSON: {exc}')
        if not isinstance(data, dict):
            raise argparse.ArgumentTypeError(
                f'{flag}: must be a JSON object (got {type(data).__name__})'
            )
        return value
    return _check


class _ColoredFormatter(argparse.RawDescriptionHelpFormatter):
    """Argparse formatter with ANSI color support."""

    def start_section(self, heading: str | None) -> None:
        import core.colors as C
        if heading:
            heading = C.bold(C.cyan(heading))
        super().start_section(heading)

    def _format_usage(self, usage, actions, groups, prefix):
        import core.colors as C
        return super()._format_usage(
            usage, actions, groups,
            prefix if prefix is not None else C.bold(C.cyan('usage')) + ': ',
        )

    def _format_action_invocation(self, action) -> str:
        import core.colors as C
        if not action.option_strings:
            default = self._get_default_metavar_for_positional(action)
            metavar, = self._metavar_formatter(action, default)(1)
            return C.cyan(metavar)
        parts = []
        if action.nargs == 0:
            parts.extend(C.cyan(s) for s in action.option_strings)
        else:
            default = self._get_default_metavar_for_optional(action)
            args_string = self._format_args(action, default)
            for option_string in action.option_strings:
                parts.append(f'{C.cyan(option_string)} {C.yellow(args_string)}')
        return ', '.join(parts)


def build_parser() -> argparse.ArgumentParser:
    import core.colors as C

    description = (
        f'{C.bold(C.white("SimpleReconDorking v1"))}'
        ' - Dorking across search engines: operator dorks in, URLs out'
    )
    epilog = (
        f'{C.bold(C.cyan("quick start:"))}\n'
        f'  {C.gray("python simplerecondorking.py -d \'site:target.com ext:sql\'")}\n'
        f'  {C.gray("python simplerecondorking.py -t target.com --dork-category files,config")}\n'
        f'\n'
        f'{C.bold(C.cyan("see more:"))}\n'
        f'  {C.gray("python simplerecondorking.py --list-sources")}    {C.gray("# all search sources")}\n'
        f'  {C.gray("python simplerecondorking.py --list-profiles")}   {C.gray("# curated source groups")}\n'
        f'  {C.gray("python simplerecondorking.py --list-category")}   {C.gray("# built-in dork catalog")}\n'
        f'  {C.gray("python simplerecondorking.py --list-examples")}   {C.gray("# usage examples + tool chaining")}\n'
    )

    parser = argparse.ArgumentParser(
        prog='simplerecondorking.py',
        description=description,
        formatter_class=_ColoredFormatter,
        epilog=epilog,
    )

    # Dork input
    dork_group = parser.add_argument_group('dork input')
    dork_group.add_argument(
        '-d', '--dork', metavar='QUERY',
        help='A single dork string, e.g. \'site:target.com ext:sql\'. May include '
             '{TARGET}, filled in from -t/--target.',
    )
    dork_group.add_argument(
        '-D', '--dork-file', metavar='FILE',
        help='File with one dork template per line (# comments and blanks ignored). '
             'Combines additively with -d and --dork-category.',
    )
    dork_group.add_argument(
        '--dork-category', metavar='CAT[,CAT...]',
           help='Run one or more built-in dork categories (see --list-category). '
               f'Available: {", ".join(catalog.categories()) or "(none found)"}',
    )
    dork_group.add_argument(
           '-t', '--target', metavar='TARGET',
           help='Domain, host, IP, or free text substituted into {TARGET}. Built-in '
               'categories use operators for hosts/IPs and operators_out for free text. '
               'Not a filter by itself; see --filter-host.',
    )
    dork_group.add_argument(
        '--stdin',
        action='store_true',
        help='Read additional dork strings from stdin (one per line); enables '
             'pipe-friendly use. Implied when no -d/-D/--dork-category is given and '
             'stdin is not a TTY.',
    )

    # Filtering result URLs. Unset by default across all four: a dork answer is
    # kept exactly as the source returned it, on any domain, which is the
    # honest default for dorking. A URL rejected by an active filter is never
    # dropped outright - it moves to extras (visible at -v 3, persisted in
    # --db) alongside the main result set.
    filter_group = parser.add_argument_group('filters')
    filter_group.add_argument(
        '--filter-host', metavar='HOST',
        help='Keep only result URLs on HOST or a subdomain of it.',
    )
    filter_group.add_argument(
        '--filter-string', metavar='LIST',
        help='Keep only result URLs containing any of these strings '
             '(comma-separated, case-insensitive).',
    )
    filter_group.add_argument(
        '--filter-regex', metavar='PATTERN', type=_regex('--filter-regex'),
        help='Keep only result URLs matching this regex. A single pattern - use '
             '`|` for multiple alternatives rather than a comma-separated list, '
             'since a comma is common regex syntax (e.g. `\\d{2,4}`).',
    )
    filter_group.add_argument(
        '--filter-file', metavar='FILE',
        help='File with one string per line (# comments and blank lines ignored). '
             'Adds to whatever --filter-string already contributed.',
    )

    # Output
    parser.add_argument(
        '-o', '--output',
        choices=['txt', 'json', 'csv', 'ndjson', 'html', 'markdown'],
        default='txt',
        help='Output format (default: txt). ndjson = one JSON line per URL; '
             'html = interactive target->dork->URL map; markdown = human-readable report',
    )
    parser.add_argument('--outfile', metavar='FILE', help='Write output to file')
    parser.add_argument(
        '--network-map',
        action='store_true',
        help='Include the target->dork->URL graph (nodes/edges) in JSON output. '
             'Auto-enabled when -o html or --network-html is used.',
    )
    parser.add_argument(
        '--network-html',
        metavar='FILE',
        help='Write an HTML dork-map visualization to FILE alongside the main output. '
             'Combine with any -o format.',
    )
    parser.add_argument(
        '--db',
        metavar='FILE',
        help='SQLite database file used as both store and comparison source. '
             'Without --db-news, saves the full run (URLs, and at -v 3 also '
             'URLs excluded by an active --filter-* flag). With --db-news, also the '
             'baseline to diff against.',
    )
    parser.add_argument(
        '--db-news',
        action='store_true',
        help='Compare this run against the --db database and output only values not seen before, '
             'saving the new ones back to the DB. Requires --db.',
    )
    parser.add_argument(
        '--db-list',
        choices=['urls', 'extras', 'history'],
        metavar='TYPE',
        help='List stored data and exit. urls/extras read the --db database '
             '(extras=URLs excluded by an active --filter-* flag); history reads the '
             'fixed config/system.db command log (no --db needed). Optionally filter '
             'with -t TARGET.',
    )

    # Continuous monitoring (cron scheduler stored in config/system.db)
    watch_group = parser.add_argument_group('continuous monitoring')
    watch_group.add_argument(
        '--watch-add',
        metavar='CRON',
        help='Register the current command in config/system.db to run on a 5-field cron '
             "schedule (e.g. '0,15,30,45 * * * *'); the --watch-add flag itself is stripped "
             'from the stored command. Use --watch to run the scheduler.',
    )
    watch_group.add_argument(
        '--watch',
        action='store_true',
        help='Monitoring daemon: every minute, run any config/system.db job whose cron '
             'schedule matches now (jobs due in the same minute run in parallel). Ctrl-C to stop.',
    )
    watch_group.add_argument(
        '--watch-list',
        action='store_true',
        help='List registered watch jobs (with their IDs) and exit.',
    )
    watch_group.add_argument(
        '--watch-del',
        type=int,
        metavar='ID',
        help='Delete the watch job with the given ID (from --watch-list) and exit.',
    )
    watch_group.add_argument(
        '--watch-clear',
        action='store_true',
        help='Delete all registered watch jobs and exit.',
    )

    # Performance
    perf_group = parser.add_argument_group('performance')
    perf_group.add_argument(
        '--threads',
        type=int, default=8,
        help='Concurrency gate for (source, dork) runs (default: 8)',
    )
    perf_group.add_argument(
        '--timeout',
        type=int, default=30,
        help='HTTP timeout in seconds (default: 30)',
    )
    perf_group.add_argument(
        '--rate-limit',
        type=int, default=0,
        metavar='N',
        help='Max concurrent requests per source (0=unlimited)',
    )
    perf_group.add_argument(
        '--pages', type=_pages, default=2, metavar='N',
        help=f'Result pages to walk per (source, dork) (default: 2, max: {MAX_PAGES}). '
             'Every paging source additionally clamps this to its own ceiling - a free '
             'API tier or an anti-bot threshold is often a harder limit than this.',
    )

    # Source control
    src_group = parser.add_argument_group('source selection')
    src_group.add_argument(
        '--profile',
        metavar='PROFILE',
        help=(
            'Run a predefined source group. Available: '
            + ', '.join(profile_names())
            + '. Overrides --sources/--category if given.'
        ),
    )
    src_group.add_argument(
        '--sources',
        metavar='SOURCES',
        help=f'Comma-separated sources to use (default: all). Available: {", ".join(ALL_SOURCES)}',
    )
    src_group.add_argument(
        '--category',
        metavar='CAT[,CAT...]',
        help=f'Run every source in these categories. Available: {", ".join(source_categories())}',
    )
    src_group.add_argument(
        '--exclude',
        metavar='SOURCES',
        help='Comma-separated sources to exclude. Applied after --sources/--profile/--category selection',
    )
    src_group.add_argument(
        '--list-sources',
        action='store_true',
        help='List all available search sources and exit',
    )
    src_group.add_argument(
        '--list-profiles',
        action='store_true',
        help='List all available profiles and exit',
    )
    src_group.add_argument(
        '--list-category',
        action='store_true',
        help='List the JSON dork catalog by category and exit',
    )
    src_group.add_argument(
        '--list-examples',
        action='store_true',
        help='Print categorized usage examples (incl. tool chaining) and exit',
    )

    # Run-config preset
    parser.add_argument(
        '--config',
        metavar='FILE',
        help=(
            'JSON file with CLI argument presets (run-config). '
            'Explicit CLI flags always override values from the config file. '
            'See config/run_config.example.json for the full format.'
        ),
    )

    # Verbosity
    parser.add_argument(
        '-v', '--verbose',
        nargs='?', const=1, type=int, default=0,
        metavar='LEVEL',
        help='Verbose level (cumulative): 1=per-(source,dork) hit counts, 2=+HTTP codes, '
             '3=+HTTP body +extras (filtered-out URLs in output and DB), 4=full debug+exceptions',
    )
    parser.add_argument(
        '-q', '--quiet', action='store_true', help='Quiet mode (results only)'
    )
    parser.add_argument(
        '--no-banner',
        action='store_true',
        help='Suppress banner and all process output; print only the final URL list',
    )
    parser.add_argument(
        '--no-progress',
        action='store_true',
        help='Disable the live progress line drawn while (source, dork) runs are in '
             'flight. The line only ever appears when stderr is a terminal, so piping '
             'is unaffected either way.',
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable ANSI color output',
    )

    # Network / proxy
    net_group = parser.add_argument_group('network')
    net_group.add_argument(
        '--proxy',
        metavar='URL',
        action='append',
        help='Route HTTP requests through this proxy (e.g. http://127.0.0.1:8080 or '
             'socks5://host:port). Repeatable - pass it more than once to build a pool '
             'without needing a file. Credentials may be inline (http://user:pass@host).',
    )
    net_group.add_argument(
        '--proxy-file',
        metavar='FILE',
        help='File with one proxy per line (# comments and blank lines ignored). '
             'Adds to whatever --proxy already contributed.',
    )
    net_group.add_argument(
        '--tor-proxy',
        metavar='URL',
        default='socks5h://127.0.0.1:9050',
        help='SOCKS5 endpoint of the local Tor daemon, used by the darkweb sources '
             '(ahmia, torch, tor66, tordex) and nothing else (default: '
             'socks5h://127.0.0.1:9050). Keep the socks5h scheme: .onion has no public '
             'DNS, so the hostname must be resolved by Tor, not locally. These sources '
             'never use the --proxy pool, so both can be set in one run.',
    )
    net_group.add_argument(
        '--proxy-source', metavar='LIST',
        help='Restrict the proxy pool to these sources (comma-separated names). '
             'Unset: every source uses the pool. Combines with --proxy-profile as AND.',
    )
    net_group.add_argument(
        '--proxy-profile', metavar='LIST',
        help='Restrict the proxy pool to runs where the active --profile is one of '
             'these (comma-separated names). Unset: no restriction. Without --profile '
             'at all, this gate never opens - the pool is configured but unused. '
             'Combines with --proxy-source as AND.',
    )
    net_group.add_argument(
        '--ua', '--user-agent',
        metavar='UA', dest='user_agent',
        default='SimpleReconDorking/1',
        help='Override the HTTP User-Agent header sent by all sources (default: rotates a '
             'browser UA - see --list-examples). Passing this literal default is treated '
             'as "unset". See --ua-file for a pool instead of a single value.',
    )

    # User-Agent pool and targeting
    ua_group = parser.add_argument_group('user-agent')
    ua_group.add_argument(
        '--ua-file', metavar='FILE',
        help='File with one User-Agent per line (# comments and blank lines ignored). '
             'With more than one line, a User-Agent is drawn at random per (source, dork) '
             'task. Wins over --ua/--user-agent when both are given.',
    )
    ua_group.add_argument(
        '--ua-source', metavar='LIST',
        help='Restrict the custom User-Agent (--ua-file or --ua/--user-agent) to these '
             'sources (comma-separated names). Unset: every source gets it. A source '
             'outside the gate falls back to the normal automatic UA rotation. Combines '
             'with --ua-profile as AND.',
    )
    ua_group.add_argument(
        '--ua-profile', metavar='LIST',
        help='Restrict the custom User-Agent to runs where the active --profile is one of '
             'these (comma-separated names). Unset: no restriction. Combines with '
             '--ua-source as AND.',
    )

    # HTTP headers
    header_group = parser.add_argument_group('headers')
    header_group.add_argument(
        '--header', metavar='JSON', type=_json_object('--header'),
        help='Extra HTTP headers as a JSON object, e.g. '
             '\'{"user-agent": "android", "Cookie": "guest_id=1"}\'. Merged in last, after '
             'everything a source sets on its own - overrides even the User-Agent, '
             'regardless of header-name casing. Wins over --header-file on key collision.',
    )
    header_group.add_argument(
        '--header-file', metavar='FILE',
        help='JSON file with the same object shape as --header. Combines with --header - '
             'both are merged (--header wins on collision).',
    )
    header_group.add_argument(
        '--header-source', metavar='LIST',
        help='Restrict the extra headers (--header/--header-file) to these sources '
             '(comma-separated names). Unset: every source gets them. Combines with '
             '--header-profile as AND.',
    )
    header_group.add_argument(
        '--header-profile', metavar='LIST',
        help='Restrict the extra headers to runs where the active --profile is one of '
             'these (comma-separated names). Unset: no restriction. Combines with '
             '--header-source as AND.',
    )

    # Proxy rotation
    rot_group = parser.add_argument_group('proxy rotation')
    rot_group.add_argument(
        '--proxy-rotate',
        metavar='MODE',
        choices=ROTATE_MODES,
        default='sticky',
        help=f'Rotation mode: {" | ".join(ROTATE_MODES)} (default: sticky). '
             "'sticky' keeps one proxy until something rotates it; 'round-robin' walks "
             "the pool; 'random' draws per request (costs connection reuse).",
    )
    rot_group.add_argument(
        '--proxy-rotate-secs',
        type=_nonneg('--proxy-rotate-secs'), default=0, metavar='N',
        help='Rotate after N seconds on the same proxy (0 = off)',
    )
    rot_group.add_argument(
        '--proxy-rotate-reqs',
        type=_nonneg('--proxy-rotate-reqs'), default=0, metavar='N',
        help='Rotate after N requests on the same proxy (0 = off)',
    )
    rot_group.add_argument(
        '--proxy-rotate-status',
        metavar='LIST', type=_status_list,
        help='Rotate when the response carries one of these HTTP codes '
             '(comma-separated, e.g. 403,429,503)',
    )
    rot_group.add_argument(
        '--proxy-rotate-body',
        metavar='LIST',
        help='Rotate when the response body contains one of these strings '
             '(comma-separated, case-insensitive). Only read when set - matching '
             'needs the whole body, and result pages here run 350-450KB.',
    )
    rot_group.add_argument(
        '--proxy-rotate-regex', metavar='PATTERN', type=_regex('--proxy-rotate-regex'),
        help='Rotate when the response body matches this regex. A single pattern - '
             'use `|` for multiple alternatives, since a comma is common regex '
             'syntax. Only read when set - same body-materialization cost as '
             '--proxy-rotate-body.',
    )
    rot_group.add_argument(
        '--proxy-retries',
        type=_nonneg('--proxy-retries'), default=2, metavar='N',
        help='Rotations to attempt for one request before giving up on it (default: 2). '
             'Without a cap the rotate triggers would loop forever on a bad pool.',
    )
    rot_group.add_argument(
        '--proxy-ban-after',
        type=_nonneg('--proxy-ban-after'), default=3, metavar='N',
        help='Drop a proxy from the pool after N consecutive failures (0 = never). '
             'A success resets the streak.',
    )
    rot_group.add_argument(
        '--proxy-fallback-direct',
        action='store_true',
        help='Allow direct connections when the pool is exhausted. Off by default: '
             'the run aborts instead, because silently going direct leaks the real IP '
             'at exactly the moment the operator believed they were covered.',
    )

    return parser


def print_sources() -> None:
    import core.colors as C
    from sources import by_category

    def _key_badge(cls) -> str:
        if cls.API_TOKEN_IS_REQUIREMENT:
            return C.red('[API key required]')
        return ''

    def _op_badge(cls) -> str:
        if not getattr(cls, 'SUPPORTS_OPERATORS', True):
            return C.gray('[free-text only]')
        return ''

    print(f'\n{C.bold(C.white("Available search sources:"))}\n')
    print(f'  {C.gray("free-text only = does not parse site:/ext:/inurl: etc.; the dork is downgraded automatically")}\n')
    for category, sources in by_category().items():
        print(f'  {C.bold(C.cyan(category.upper()))}')
        for cls in sources.values():
            badges = ' '.join(b for b in (_key_badge(cls), _op_badge(cls)) if b)
            suffix = f'  {badges}' if badges else ''
            print(f'    {C.cyan(f"{cls.NAME:<14}")} {cls.DESCRIPTION}{suffix}')
        print()


def print_profiles() -> None:
    import core.colors as C

    profiles = load_profiles()
    if not profiles:
        print('No profiles found.')
        return

    print(f'\n{C.bold(C.white("Available profiles:"))}\n')
    for name, cfg in profiles.items():
        sources = cfg.get('sources', 'all')
        if isinstance(sources, list):
            src_str = ', '.join(sources)
        else:
            src_str = str(sources)
        opts = cfg.get('options', {})
        opts_str = f'  {C.gray(str(opts))}' if opts else ''
        print(f'  {C.cyan(f"{name:<12}")} {cfg.get("description", "")}')
        print(f'  {" " * 12} {C.gray("sources:")} {src_str}{opts_str}')
    print()


def print_categories() -> None:
    import core.colors as C
    from core import dorks as catalog

    cats = catalog.categories()
    if not cats:
        print(f'No dork categories found in {catalog.CATALOG_FILE}.')
        return

    print(f'\n{C.bold(C.white("Built-in dork catalog:"))}\n')
    print(f'  {C.gray("run with --dork-category NAME[,NAME...] -t TARGET")}\n')
    for cat in cats:
        desc = catalog.describe(cat)
        operators = catalog.load_category(cat, 'operators')
        operators_out = catalog.load_category(cat, 'operators_out')
        total = len(operators) + len(operators_out)
        print(f'  {C.bold(C.cyan(cat))} {C.gray(f"({total} dork(s))")}')
        if desc:
            print(f'    {desc}')
        print(f'    {C.yellow("operators:")}')
        for entry in operators:
            print(f'      {C.gray(entry)}')
        print(f'    {C.yellow("operators_out:")}')
        for entry in operators_out:
            print(f'      {C.gray(entry)}')
        print()


def print_db_list(kind: str, db_path: str | None, seed: str | None = None) -> None:
    """Print stored data of *kind* (pipe-friendly plain lines).

    urls/extras come from the per-target *db_path*; history comes from the
    fixed config/system.db command log.
    """
    if kind == 'history':
        from core import system_db
        for _id, ts, targets, command in system_db.list_command_history(seed):
            print(f'{ts} | {targets or ""} | {command or ""}')
        return

    from output import db
    if kind == 'urls':
        for url, _source, _dork in db.list_urls(db_path, seed):
            print(url)
    elif kind == 'extras':
        for _type, value in db.list_extras(db_path, seed):
            print(value)


def print_watch_list() -> None:
    """Print registered watch jobs as an aligned table (ID first, for --watch-del)."""
    import core.colors as C
    from core import system_db

    jobs = system_db.list_watch_jobs()
    if not jobs:
        print(C.gray('No watch jobs registered. Add one with --watch-add "<cron>".'))
        return

    header = '  {:<4} {:<20} {:<19} {}'.format('ID', 'SCHEDULE', 'LAST RUN', 'COMMAND')
    print('\n' + C.bold(C.white('Watch jobs')) + ' ' + C.gray('(' + system_db.SYSTEM_DB + ')') + '\n')
    print(C.bold(header))
    for j in jobs:
        idc   = C.cyan('{:<4}'.format(j['id']))
        sched = '{:<20}'.format(j['schedule'])
        last  = '{:<19}'.format(j['last_run'] or '-')
        print('  {} {} {} {}'.format(idc, sched, last, C.gray(j['command'])))
    print()


# ---------------------------------------------------------------------------
# Categorized usage examples (printed via --list-examples)
# ---------------------------------------------------------------------------
_EXAMPLES: list[tuple[str, list[str]]] = [
    ('Basics', [
        'python simplerecondorking.py -d \'site:target.com ext:sql\'',
        'python simplerecondorking.py -t target.com --dork-category files',
        'python simplerecondorking.py --list-sources',
        'python simplerecondorking.py --list-profiles',
        'python simplerecondorking.py --list-category',
        'python simplerecondorking.py --list-examples',
    ]),
    ('Built-in dork categories (config/dork_categorys.json)', [
        'python simplerecondorking.py -t target.com --dork-category files',
        'python simplerecondorking.py -t target.com --dork-category config,git_exposure,backup',
        'python simplerecondorking.py -t target.com --dork-category panels,remote_access -o json --outfile panels.json',
        '# every built-in category in one run',
        'python simplerecondorking.py -t target.com --dork-category '
        + ','.join(catalog.categories() or ['files']),
    ]),
    ('Custom dorks', [
        'python simplerecondorking.py -d \'intitle:"index of" site:{TARGET}\' -t target.com',
        'python simplerecondorking.py -D mydorks.txt -t target.com',
        'echo \'site:target.com ext:log\' | python simplerecondorking.py --stdin',
        'cat mydorks.txt | python simplerecondorking.py --stdin -t target.com',
    ]),
    ('Profiles (curated source groups)', [
        'python simplerecondorking.py -d \'site:target.com ext:sql\' --profile fast',
        'python simplerecondorking.py -t target.com --dork-category files --profile web',
        'python simplerecondorking.py -d \'site:target.com\' --profile keyless -v 2',
        'python simplerecondorking.py -t target.com --dork-category files --profile full',
    ]),
    ('Custom source selection', [
        'python simplerecondorking.py -d \'site:target.com ext:env\' --sources googlecse,yahoo,duckduckgo',
        'python simplerecondorking.py -d \'target.com\' --category code',
        'python simplerecondorking.py -d \'site:target.com\' --sources bing,google --exclude google',
    ]),
    ('Filtering results', [
        'python simplerecondorking.py -d \'"target.com" site:pastebin.com\' -t target.com',
        '# without --filter-host: keeps pastebin.com hits, exactly as the dork asked',
        'python simplerecondorking.py -t target.com --dork-category files --filter-host target.com',
        '# with --filter-host: off-host hits move to extras (visible at -v 3)',
        'python simplerecondorking.py -t target.com --dork-category files --filter-string ".pdf,.doc,.xls"',
        'python simplerecondorking.py -t target.com --dork-category files --filter-regex \'\\.(sql|env)$\'',
        'python simplerecondorking.py -t target.com --dork-category files --filter-file keywords.txt',
    ]),
    ('Pagination & pacing', [
        'python simplerecondorking.py -t target.com --dork-category files --pages 5',
        'python simplerecondorking.py -d \'site:target.com\' --rate-limit 2 --timeout 15',
    ]),
    ('Output formats', [
        'python simplerecondorking.py -t target.com --dork-category files --output json --outfile result.json',
        'python simplerecondorking.py -t target.com --dork-category files --output csv  --outfile result.csv',
        'python simplerecondorking.py -t target.com --dork-category files --output markdown --outfile report.md',
        'python simplerecondorking.py -d \'site:target.com\' --no-banner > urls.txt',
    ]),
    ('Debug & verbosity', [
        'python simplerecondorking.py -d \'site:target.com\' --sources bing -v 4',
        'python simplerecondorking.py -t target.com --dork-category files --profile fast --quiet',
        'python simplerecondorking.py -d \'site:target.com\' -v 2     # show HTTP status codes',
        'python simplerecondorking.py -d \'site:target.com\' -v 3     # also show filtered-out URLs',
    ]),
    ('Piping into httpx (HTTP probing)', [
        'python simplerecondorking.py -t target.com --dork-category files --no-banner | httpx -silent',
        'python simplerecondorking.py -t target.com --dork-category panels --no-banner | httpx -silent -mc 200',
    ]),
    ('Piping into nuclei (vulnerability scanning)', [
        'python simplerecondorking.py -t target.com --dork-category files --no-banner | httpx -silent | nuclei -t exposures/ -silent',
    ]),
    ('Dark web / Tor (.onion indexes)', [
        '# needs a running Tor daemon; --tor-proxy defaults to socks5h://127.0.0.1:9050',
        'python simplerecondorking.py -d \'minhaempresa.com\' --category darkweb',
        'python simplerecondorking.py -d \'minhaempresa.com\' --profile tor -v 1',
        '# single engine, or a non-default Tor port (Tor Browser uses 9150)',
        'python simplerecondorking.py -d \'vazamento\' --sources ahmia',
        'python simplerecondorking.py -d \'vazamento\' --category darkweb --tor-proxy socks5h://127.0.0.1:9150',
        '# Tor and a clearnet proxy coexist: --proxy never touches the darkweb sources',
        'python simplerecondorking.py -d \'x\' --sources ahmia,yahoo --proxy http://a:8080',
        '# no Tor daemon at all? the two clearnet ones still answer',
        'python simplerecondorking.py -d \'minhaempresa.com\' --sources tor66web,onionsearch',
        '# onionsearch is clearnet (no Tor needed) but Cloudflare-gated; if it 403s,',
        '# send just that one through Tor - it is a normal --proxy pool participant',
        'python simplerecondorking.py -d \'gov.br\' --sources onionsearch \\\n       --proxy socks5h://127.0.0.1:9050 --proxy-source onionsearch -v 1',
    ]),
    ('Proxy pool & rotation', [
        'python simplerecondorking.py -d \'site:target.com\' --proxy socks5://127.0.0.1:9050',
        '# --proxy is repeatable; --proxy-file adds a file on top',
        'python simplerecondorking.py -d \'site:target.com\' --proxy http://a:8080 --proxy http://b:8080',
        'python simplerecondorking.py -t target.com --dork-category files --proxy-file proxies.txt',
        '# rotate on the codes that mean "blocked", ban a proxy after 2 strikes',
        'python simplerecondorking.py -t target.com --dork-category files --proxy-file proxies.txt \\\n       --proxy-rotate round-robin --proxy-rotate-status 403,429 --proxy-ban-after 2',
        '# restrict the pool to specific sources or profiles',
        'python simplerecondorking.py -t target.com --sources mojeek,dogpile \\\n       --proxy http://a:8080 --proxy-source mojeek,dogpile',
        'python simplerecondorking.py -t target.com --profile browser \\\n       --proxy http://a:8080 --proxy-profile browser',
        '# rotate when the body matches a pattern (blocked/captcha pages)',
        'python simplerecondorking.py -t target.com --dork-category files --proxy-file proxies.txt \\\n       --proxy-rotate-regex \'captcha|unusual traffic\'',
        '# the run ABORTS when the pool dies; opt in to going direct instead',
        'python simplerecondorking.py -d \'site:target.com\' --proxy-file proxies.txt --proxy-fallback-direct',
    ]),
    ('Run-config presets (--config)', [
        'cp config/run_config.example.json myrun.json',
        '# edit myrun.json with your preferred options',
        'python simplerecondorking.py -t target.com --dork-category files --config myrun.json',
    ]),
    ('SQLite persistence & change tracking (--db)', [
        'python simplerecondorking.py -t target.com --dork-category files --db recon.db',
        '# subsequent run: print + store only newly discovered URLs',
        'python simplerecondorking.py -t target.com --dork-category files --db recon.db --db-news',
    ]),
    ('Inspect the database (--db-list)', [
        'python simplerecondorking.py --db recon.db --db-list urls',
        'python simplerecondorking.py --db recon.db --db-list extras',
        'python simplerecondorking.py --db-list history',
        'python simplerecondorking.py --db recon.db --db-list urls -t target.com',
    ]),
    ('Continuous monitoring (--watch / --watch-add)', [
        '# register a command on a cron schedule (stored in config/system.db)',
        'python simplerecondorking.py -t target.com --dork-category files --db target.db --quiet \\\n       --watch-add "0,15,30,45 * * * *"',
        '# run the scheduler daemon (no --db needed); due jobs run in parallel',
        'python simplerecondorking.py --watch',
        '# manage registered jobs',
        'python simplerecondorking.py --watch-list           # show jobs + their IDs',
        'python simplerecondorking.py --watch-del 3          # delete job #3',
        'python simplerecondorking.py --watch-clear          # delete all jobs',
    ]),
]


def print_examples() -> None:
    import core.colors as C

    print(f'\n{C.bold(C.white("SimpleReconDorking - Usage Examples"))}\n')
    for section, cmds in _EXAMPLES:
        print(f'{C.bold(C.cyan("# " + section))}')
        for cmd in cmds:
            if cmd.startswith('#'):
                print(f'  {C.yellow(cmd)}')
            else:
                print(f'  {C.gray(cmd)}')
        print()
