"""Single-line live progress for a dorking run.

A run schedules one task per (engine, dork) pair and they all execute
concurrently, so without this nothing at all is printed between "Runs: N
scheduled" and the final tally - on a catalog-sized run (many dorks × many
engines) that can be minutes of silence. This module draws one line that is
rewritten in place with '\\r', so the scrollback the user already has on
screen is never erased:

    [*] [##########------] 62% | runs 148/240 | 1841 urls (+412) | now site:target.com ext:sql

Two things here are load-bearing:

* **It writes to stderr, and only when stderr is a TTY.** Writing to stdout
  would corrupt `simplerecondorking.py ... | httpx`, a documented use case;
  going to stderr instead means that pipe keeps working *and* still shows
  progress, since only stdout was redirected. The isatty() gate is what keeps
  `... > log.txt 2>&1` from collecting thousands of '\\r' fragments.

* **The TTY gate must not be colors.enabled().** That flag is also turned off
  by --no-color and by NO_COLOR, and in those cases progress should still be
  drawn, just without color. Color is decided separately, per render.
"""
from __future__ import annotations

import shutil
import sys
import time
from urllib.parse import urlparse

import core.colors as colors

# Minimum gap between two renders. Hundreds of concurrent (engine, dork) tasks
# would otherwise produce far more writes per second than a human can read.
_MIN_INTERVAL = 0.1

# 16 rather than 20 on purpose: with the labels, a 20-wide bar pushed the line
# to 82 chars and a standard 80-column terminal lost the bar entirely.
_BAR_WIDTH = 16
_ERASE_LINE = '\r\x1b[K'   # carriage return + erase from cursor to end of line


def _display_query(query: str) -> str:
    """Truncate a dork query to something that fits the tail of the line."""
    return ' '.join(query.split())


class Progress:
    """Inert unless stderr is a TTY and *enabled* is True, in which case every
    start()/advance() call redraws the line.
    """

    def __init__(
        self,
        total: int,
        baseline: int = 0,
        enabled: bool = True,
        stream=None,
        round_no: int = 1,
        rounds: int = 1,
    ) -> None:
        # round_no/rounds accepted for call-site symmetry with the rest of the
        # SimpleRecon family's Progress; dorking has no recursive rounds, so
        # they never appear in the rendered line.
        self.total = max(0, total)
        self.baseline = baseline
        self.done = 0
        self.urls = baseline
        self.current = ''
        # Sub-task counters. 'done' only moves when a whole (source, dork)
        # task finishes, which on a one-task run (searxbrowser walking 72
        # instances) means the line never changes for minutes. These two do
        # move, because every request reports itself - see note_request().
        self.requests = 0
        # Sub-task workload, so the BAR can move inside a long task. done/total
        # alone cannot: a run with one (source, dork) task pinned at 0/1 leaves
        # the bar at 0% for its entire duration, which is exactly the case that
        # motivated this (searxbrowser walking dozens of instances). A task that
        # knows its workload declares it with declare_units() and ticks
        # note_unit(); tasks that do not simply leave the bar on done/total.
        self._units_total = 0
        self._units_done = 0
        # A set, not a counter: a single-host source contributes 1 no matter
        # how many pages it walks, while a multi-instance source (searx,
        # searxbrowser) makes the number climb - which is exactly the
        # information the line was missing.
        self._hosts: set[str] = set()
        self._drawn = False
        self._last_render = 0.0
        self._stream = stream if stream is not None else sys.stderr
        self.enabled = bool(enabled) and self._stream_is_tty()

    def _stream_is_tty(self) -> bool:
        try:
            return bool(self._stream.isatty())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Line building
    # ------------------------------------------------------------------

    def _pct(self) -> int:
        """Percentage, counting partial progress of in-flight tasks.

        Finished tasks weigh 1 each; declared sub-units add the fraction of
        **one** further task on top. Deliberately one and not "every task still
        pending": the declared units belong to whatever is running right now,
        and scaling them across all remaining tasks made a single finished
        task with a full unit pool read as 100% when it was 25% (caught by the
        unit test). Understating is the safe direction for a progress bar.
        """
        if not self.total:
            return 100
        progress = float(self.done)
        if self._units_total:
            partial = min(1.0, self._units_done / self._units_total)
            progress += partial * min(1, max(0, self.total - self.done))
        return max(0, min(100, int(progress * 100 / self.total)))

    def declare_units(self, n: int) -> None:
        """A task announces how many sub-units of work it is about to do."""
        if not self.enabled or n <= 0:
            return
        self._units_total += n
        self._render()

    def note_unit(self, n: int = 1) -> None:
        """*n* declared sub-units finished."""
        if not self.enabled:
            return
        self._units_done += n
        if self._units_total and self._units_done >= self._units_total:
            # Pool drained: clear it so the finished task leaves no residue
            # that would be re-counted on top of the done/total it is about to
            # bump. Whatever is still in flight re-declares as it goes.
            self._units_total = 0
            self._units_done = 0
        self._render()

    def _bar(self, pct: int) -> str:
        filled = round(_BAR_WIDTH * pct / 100)
        return '[' + '#' * filled + '-' * (_BAR_WIDTH - filled) + ']'

    def _compose(self, width: int) -> str:
        """Build the line, dropping parts by priority when width is tight.

        Every counter carries a label, because the two fractions mean very
        different things and are indistinguishable without one: 'runs' counts
        (engine, dork) tasks scheduled this invocation, 'urls' counts unique
        URLs found so far. The counters are the point of the feature, so they
        are the last thing dropped.
        """
        pct = self._pct()
        new = self.urls - self.baseline
        bar = self._bar(pct)
        runs = f'runs {self.done}/{self.total}'
        urls = f'urls {self.urls} (+{new} new)'
        work = f'req {self.requests} | hosts {len(self._hosts)}'

        base = f'[*] {bar} {pct:3d}% | {runs} | {work} | {urls}'
        if self.current:
            candidate = f'{base} | now {self.current}'
            if len(candidate) <= width:
                return candidate
            room = width - len(base) - 8   # 7 for ' | now ' plus 1 for the '…'
            if room >= 10:
                return f'{base} | now …{self.current[-room:]}'

        for line in (
            base,                                              # drop the query
            f'[*] {bar} {pct:3d}% | {runs} | {urls}',          # drop req/hosts
            f'[*] {pct:3d}% | {runs} | {urls}',                # drop the bar
            f'[*] {pct:3d}% | {self.done}/{self.total} | {self.urls} (+{new})',
        ):
            if len(line) <= width:
                return line
        return f'{self.done}/{self.total} {self.urls}u'[:width]

    def _render(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and (now - self._last_render) < _MIN_INTERVAL:
            return
        self._last_render = now
        width = max(20, shutil.get_terminal_size(fallback=(80, 24)).columns - 1)
        line = self._compose(width)
        if colors.enabled():
            line = colors.format_msg(line)
        try:
            self._stream.write('\r' + line + '\x1b[K')
            self._stream.flush()
        except Exception:
            self.enabled = False
            return
        self._drawn = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Erase the line if one is drawn, so other output can print cleanly.

        Called by Engine.log()/vlog() before every write: those go to stdout,
        which is usually the same terminal, and would otherwise be spliced
        into the middle of the progress line.
        """
        if not self.enabled or not self._drawn:
            return
        try:
            self._stream.write(_ERASE_LINE)
            self._stream.flush()
        except Exception:
            self.enabled = False
        self._drawn = False

    def note_request(self, url: str = '') -> None:
        """One HTTP request (or browser navigation) is going out.

        This is what keeps the line alive *inside* a long fetch(): done/total
        cannot move until a whole task ends, so a run with a single task -
        searxbrowser walking dozens of instances with a proof-of-work each -
        would otherwise sit frozen for minutes. Re-rendering here is safe
        because _render() still honours the _MIN_INTERVAL throttle, so many
        concurrent requests do not become many writes.
        """
        if not self.enabled:
            return
        self.requests += 1
        if url:
            try:
                host = urlparse(url).hostname
            except Exception:
                host = None
            if host:
                self._hosts.add(host)
        self._render()

    def start(self, query: str) -> None:
        """A task began; show its dork so the line moves even on slow engines."""
        if not self.enabled:
            return
        self.current = _display_query(query)
        self._render()

    def advance(self, urls: int) -> None:
        """A task finished. *urls* is the running total collected so far."""
        if not self.enabled:
            return
        self.done += 1
        self.urls = urls
        self._render(force=self.done >= self.total)

    def finish(self) -> None:
        """Clear the line for good, right before the run's summary prints."""
        self.clear()


class NullProgress(Progress):
    """Always-off Progress, so callers can stay branch-free."""

    def __init__(self) -> None:
        super().__init__(total=0, baseline=0, enabled=False)
