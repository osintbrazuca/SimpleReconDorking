#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SimpleReconDorking v1
# https://github.com/osintbrazuca/SimpleReconDorking
#
# WARNING
# +------------------------------------------------------------------------------+
# |  [!] Legal disclaimer: Usage of SimpleReconDorking for attacking             |
# |  targets without prior mutual consent is illegal.                            |
# |  It is the end user's responsibility to obey all applicable                  |
# |  local, state and federal laws.                                              |
# |  Developers assume no liability and are not responsible for any misuse or    |
# |  damage caused by this program.                                              |
# +------------------------------------------------------------------------------+

import asyncio
import sys

from cli.parser import (
    build_parser, print_sources, print_profiles, print_categories, print_examples,
    print_db_list, print_watch_list,
)
from core.banner import AsciiBanner
from core.engine import Engine
from core import settings
import core.colors as colors


def _banner_footer() -> str:
    """Build the fixed footer printed under the random banner art.

    Built at call time rather than import time so it honours colors.init(),
    which runs inside main() once --no-color has been parsed.
    """
    return '\n'.join([
        f"    {colors.bold(f'SimpleReconDorking v{settings.__version__}')} "
        f"{colors.gray('-')} {colors.white(settings.__description__)}",
        f"    {colors.bold('By:')} {colors.bold(settings.__author__)} {colors.gray('-')} "
        f"{colors.white(settings.__git_project__)}",
    ])


def _print_banner() -> None:
    """Print a random banner plus the fixed footer."""
    art = AsciiBanner().show_random()
    if art:
        print(art)
    print(_banner_footer())


def main() -> None:
    # Pre-initialize colors before building the parser so --help output is colored.
    # Check sys.argv directly since args are not parsed yet.
    colors.init(no_color='--no-color' in sys.argv)

    # Quiet flags have to be read from argv here: --help exits inside
    # parse_args(), so the banner must be printed before args exist.
    banner_ok = not any(
        flag in sys.argv for flag in ('-q', '--quiet', '--no-banner')
    )
    if banner_ok and ('-h' in sys.argv or '--help' in sys.argv):
        _print_banner()

    parser = build_parser()
    args = parser.parse_args()

    # Informational listings are human-facing, so they get the banner too.
    # --db-list is deliberately excluded: it emits pipe-friendly data lines.
    if banner_ok and (args.list_sources or args.list_profiles or args.list_category or args.list_examples):
        _print_banner()

    if args.list_sources:
        print_sources()
        sys.exit(0)

    if args.list_profiles:
        print_profiles()
        sys.exit(0)

    if args.list_category:
        print_categories()
        sys.exit(0)

    if args.list_examples:
        print_examples()
        sys.exit(0)

    if getattr(args, 'db_list', None):
        # 'history' reads the fixed config/system.db; the rest read the --db file
        if args.db_list != 'history' and not getattr(args, 'db', None):
            print(colors.format_msg(f'[!] --db-list {args.db_list} requires --db FILE.'))
            sys.exit(1)
        print_db_list(args.db_list, getattr(args, 'db', None), args.target)
        sys.exit(0)

    if getattr(args, 'watch_list', False):
        print_watch_list()
        sys.exit(0)

    if getattr(args, 'watch_clear', False):
        from core import system_db
        n = system_db.clear_watch_jobs()
        print(colors.format_msg(f'[+] [watch] removed {n} job(s).'))
        sys.exit(0)

    if getattr(args, 'watch_del', None) is not None:
        from core import system_db
        if system_db.delete_watch_job(args.watch_del):
            print(colors.format_msg(f'[+] [watch] deleted job #{args.watch_del}.'))
            sys.exit(0)
        print(colors.format_msg(f'[!] [watch] no job with id {args.watch_del}.'))
        sys.exit(1)

    if getattr(args, 'watch_add', None):
        from core.watch import build_command_string, parse_cron
        from core import system_db
        try:
            parse_cron(args.watch_add)  # validate the 5-field cron expression
            cmd = build_command_string(sys.argv)
            system_db.add_watch_job(cmd, args.watch_add)
        except ValueError as exc:
            print(colors.format_msg(f'[!] [watch] invalid cron: {exc}'))
            sys.exit(1)
        print(colors.format_msg(
            f'[+] [watch] registered @ {args.watch_add} -> {system_db.SYSTEM_DB}\n    {cmd}'
        ))
        sys.exit(0)

    if getattr(args, 'watch', False):
        from core.watch import run_daemon
        run_daemon()
        sys.exit(0)

    # Apply run-config preset before engine init (CLI flags already parsed, so
    # they will override config values via apply_run_config's default-comparison).
    if getattr(args, 'config', None):
        from core.run_config import load_run_config, apply_run_config
        cfg = load_run_config(args.config)
        apply_run_config(args, cfg)

    if getattr(args, 'db_news', False) and not getattr(args, 'db', None):
        print(colors.format_msg('[!] --db-news requires --db FILE (the database to compare against and save to).'))
        sys.exit(1)

    has_dork_input = bool(
        args.dork or args.dork_file or getattr(args, 'dork_category', None)
    )
    if not has_dork_input and not getattr(args, 'stdin', False) and sys.stdin.isatty():
        if banner_ok:
            _print_banner()
        parser.print_help()
        sys.exit(1)

    # --no-banner implies quiet mode: suppress banner + all process messages
    if getattr(args, 'no_banner', False):
        args.quiet = True

    # Re-checked against args (not argv) because a --config run-config file
    # can also set quiet, and it is applied just above.
    if not args.quiet:
        _print_banner()

    engine = Engine(args)
    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        print('\n' + colors.format_msg('[!] Interrupted by user.'))
        sys.exit(0)


if __name__ == '__main__':
    main()
