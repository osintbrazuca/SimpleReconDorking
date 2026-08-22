"""
ASCII banner module.

Loads banner art from .txt files in core/banner/asciiart/ and returns one at
random on each run. Mirrors the banner scheme of string-x
(https://github.com/MrCl0wnLab/string-x).

Banner files are plain .txt containing **raw ANSI escape codes** (already
colored art) - unlike string-x, which stores Rich markup tags and renders them
through the `rich` library. Here the file content is printed as-is, so no
extra dependency is needed. When colors are off (--no-color, or stdout not a
TTY) the escapes are stripped instead.

Two placeholders are substituted at display time:
    [VERSION]      -> core.settings.__version__
    [DESCRIPTION]  -> core.settings.__description__

Every method fails soft and returns '' - a missing, empty or unreadable
banner directory must never break startup.

Note: this module and the asciiart/ data directory share a name inside the
same package. That is intentional (string-x does the same) and resolves
correctly because asciiart/ has no __init__.py: CPython's FileFinder prefers
a real module over a namespace-package candidate. Do not add an __init__.py
to the data directory.
"""
from __future__ import annotations

import random
from pathlib import Path

import core.colors as colors
from core import settings

_BANNER_DIR = Path(__file__).parent / 'asciiart'


class AsciiBanner:
    """Loads and displays ASCII banners from a directory of .txt files."""

    def __init__(self, banner_dir: Path | None = None) -> None:
        self._files_path: Path = banner_dir or _BANNER_DIR

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def _get_banner_list(self) -> list[Path]:
        """Return every banner file available, sorted by name."""
        try:
            return sorted(p for p in self._files_path.glob('*.txt') if p.is_file())
        except OSError:
            return []

    def _get_banner_file(self, banner_name: str) -> list[Path]:
        """Return banner files whose stem contains *banner_name*."""
        if not banner_name:
            return []
        return [p for p in self._get_banner_list() if banner_name in p.stem]

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def show(self, banner_name: str) -> str:
        """Return the art for the first banner matching *banner_name* ('' if none)."""
        matches = self._get_banner_file(banner_name)
        if not matches:
            return ''
        try:
            art = matches[0].read_text(encoding='utf-8')
        except OSError:
            return ''
        return self._render(art)

    def show_random(self) -> str:
        """Return the art of a randomly chosen banner ('' if none available)."""
        files = self._get_banner_list()
        if not files:
            return ''
        try:
            art = random.choice(files).read_text(encoding='utf-8')
        except OSError:
            return ''
        return self._render(art)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _render(art: str) -> str:
        """Substitute placeholders and drop ANSI when colors are disabled."""
        art = (
            art.replace('[VERSION]', settings.__version__)
               .replace('[DESCRIPTION]', settings.__description__)
        )
        if not colors.enabled():
            art = colors.strip_ansi(art)
        return art.rstrip('\n')
