"""ANSI color helpers.

Call ``init(no_color)`` once at program startup before any output.
Colors are automatically disabled when stdout is not a TTY (piped output)
or when the NO_COLOR environment variable is set (https://no-color.org/).
"""

from __future__ import annotations

import os
import re
import sys

_enabled: bool = True


def init(no_color: bool = False) -> None:
    """Configure the color system. Must be called before any output."""
    global _enabled
    if no_color:
        _enabled = False
        return
    # Respect NO_COLOR env var and dumb terminals
    if os.getenv('NO_COLOR') is not None or os.getenv('TERM') == 'dumb':
        _enabled = False
        return
    # Disable when stdout is not a TTY (e.g. piped to file/grep)
    if not (hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()):
        _enabled = False


def enabled() -> bool:
    """True when ANSI output is active (see init())."""
    return _enabled


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def strip_ansi(text: str) -> str:
    """Remove ANSI SGR sequences from *text*.

    Needed for content that ships with hardcoded escapes - the banner art
    files under core/banner/asciiart/ - so it stays readable under
    --no-color or when stdout is piped.
    """
    return _ANSI_RE.sub('', text)


def _c(code: str, text: str) -> str:
    if not _enabled:
        return text
    return f'\033[{code}m{text}\033[0m'


def bold(text: str)    -> str: return _c('1',  text)
def dim(text: str)     -> str: return _c('2',  text)
def gray(text: str)    -> str: return _c('90', text)
def red(text: str)     -> str: return _c('91', text)
def green(text: str)   -> str: return _c('92', text)
def yellow(text: str)  -> str: return _c('93', text)
def blue(text: str)    -> str: return _c('94', text)
def magenta(text: str) -> str: return _c('95', text)
def cyan(text: str)    -> str: return _c('96', text)
def white(text: str)   -> str: return _c('97', text)


_SEP_RE  = re.compile(r'^-{10,}$')
# Strict IPv4: four 1–3 digit groups separated by dots
_IPv4_RE = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
# FQDN with 3+ labels (e.g. api.example.com); requires an alphabetic TLD
_FQDN_RE = re.compile(
    r'\b((?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.){2,}[a-zA-Z]{2,})\b'
)


def _bracket_label(m: re.Match) -> str:
    """Color a [LABEL] token. Special labels get distinct colors; rest → cyan."""
    word = m.group(1)
    if word == 'x':
        return red(f'[{word}]')
    if word == 'LIVE':
        return bold(green(f'[{word}]'))
    return f'[{cyan(word)}]'


def format_msg(msg: str) -> str:
    """Apply contextual colors to a log message based on its content."""
    if not _enabled:
        return msg

    stripped = msg.strip()

    # Separator lines (e.g. '----...----') → gray
    if _SEP_RE.match(stripped):
        return gray(msg)

    # Status prefix tokens whose content is non-word (safe from the [\w+] rule below)
    if '[+]' in msg:
        msg = msg.replace('[+]', green('[+]'), 1)
    if '[-]' in msg:
        msg = msg.replace('[-]', gray('[-]'), 1)
    if '[*]' in msg:
        msg = msg.replace('[*]', blue('[*]'), 1)
    if '[!]' in msg:
        msg = msg.replace('[!]', yellow('[!]'), 1)

    # Highlight IPv4 addresses
    msg = _IPv4_RE.sub(lambda m: cyan(m.group(1)), msg)

    # Highlight FQDNs with 3+ labels (e.g. api.example.com)
    msg = _FQDN_RE.sub(lambda m: white(m.group(1)), msg)

    # Colorize [word] labels: [brute], [crtsh], [x], [LIVE], etc.
    # Runs last so ANSI codes injected above do not interfere.
    msg = re.sub(r'\[(\w+)\]', _bracket_label, msg)

    return msg
