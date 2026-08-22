import csv
import io
import json
import sys
from datetime import datetime
from typing import Optional

import core.colors as colors
from output.graph import build_network_graph
from output.html_renderer import render_html
from output.report import render_markdown


def save_output(
    results: list[dict],
    fmt: str = 'txt',
    outfile: Optional[str] = None,
    quiet: bool = False,
    network_map: bool = False,
    network_html_file: Optional[str] = None,
) -> None:
    """
    Serialize *results* to the requested format and write to *outfile* or stdout.

    *results* is a list of per-run dicts with keys:
        seed, dorks (list), urls (set), sources (dict),
        url_sources (dict), url_dorks (dict), extras (dict, optional)

    Formats: txt, json, csv, ndjson, html, markdown

    When *network_map* is True (or fmt == 'html'), each JSON record also carries
    a 'network' field with nodes/edges. When *network_html_file* is given, an
    HTML visualization is written there regardless of *fmt*.
    """
    # markdown primary output
    if fmt == 'markdown':
        md = render_markdown(results)
        if outfile:
            try:
                with open(outfile, 'w') as fh:
                    fh.write(md)
                    fh.write('\n')
                if not quiet:
                    print(colors.format_msg(f'\n[+] Markdown report saved to: {outfile}'))
            except OSError as exc:
                print(colors.format_msg(f'[!] Could not write to {outfile}: {exc}'), file=sys.stderr)
        else:
            print('\n' + md)
        if network_html_file:
            _write_html(results, network_html_file, quiet)
        return

    # html primary output: render and short-circuit; the side artifact
    # (network_html_file) still runs at the bottom if also set.
    if fmt == 'html':
        html_out = render_html(results)
        if outfile:
            try:
                with open(outfile, 'w') as fh:
                    fh.write(html_out)
                if not quiet:
                    print(colors.format_msg(f'\n[+] HTML page-link map saved to: {outfile}'))
            except OSError as exc:
                print(colors.format_msg(f'[!] Could not write to {outfile}: {exc}'), file=sys.stderr)
        else:
            print(html_out)
        if network_html_file and network_html_file != outfile:
            _write_html(results, network_html_file, quiet)
        return

    include_network = network_map or bool(network_html_file)
    segments: list[str] = []

    for result in results:
        seed = result['seed']
        dorks: list = result.get('dorks', [])
        urls: set[str] = result.get('urls', set())
        sources: dict = result.get('sources', {})
        url_sources: dict = result.get('url_sources', {})
        url_dorks: dict = result.get('url_dorks', {})
        extras: dict = result.get('extras', {})
        extra_filtered: set[str] = extras.get('urls_filtered', set())
        timestamp = datetime.now().isoformat()

        if fmt == 'json':
            data = {
                'seed': seed,
                'timestamp': timestamp,
                'dorks': dorks,
                'total': len(urls),
                'urls': sorted(urls),
                'url_sources': {u: url_sources[u] for u in sorted(urls) if u in url_sources},
                'url_dorks': {u: url_dorks[u] for u in sorted(urls) if u in url_dorks},
                'sources': sources,
            }
            if extra_filtered:
                data['extras'] = {'urls_filtered': sorted(extra_filtered)}
            if include_network:
                data['network'] = build_network_graph(result)
            segments.append(json.dumps(data, indent=2))

        elif fmt == 'csv':
            buf = io.StringIO()
            writer = csv.DictWriter(
                buf,
                fieldnames=['seed', 'url', 'type', 'source', 'dork'],
            )
            writer.writeheader()
            for url in sorted(urls):
                writer.writerow({
                    'seed': seed,
                    'url': url,
                    'type': 'url',
                    'source': url_sources.get(url, ''),
                    'dork': url_dorks.get(url, ''),
                })
            for url in sorted(extra_filtered):
                writer.writerow({
                    'seed': seed, 'url': url, 'type': 'url_filtered', 'source': '', 'dork': '',
                })
            segments.append(buf.getvalue())

        elif fmt == 'ndjson':
            # One compact JSON line per URL - pipe-friendly
            for url in sorted(urls):
                record: dict = {'seed': seed, 'url': url, 'type': 'url'}
                if url_sources.get(url):
                    record['source'] = url_sources[url]
                if url_dorks.get(url):
                    record['dork'] = url_dorks[url]
                segments.append(json.dumps(record))
            for url in sorted(extra_filtered):
                segments.append(json.dumps({'seed': seed, 'url': url, 'type': 'url_filtered'}))

        else:  # txt (default)
            lines = list(sorted(urls))
            if extra_filtered:
                if not quiet:
                    lines.append('')
                    lines.append('# Filtered-out URLs')
                lines.extend(sorted(extra_filtered))
            segments.append('\n'.join(lines))

    output = '\n'.join(segments)

    if outfile:
        try:
            with open(outfile, 'w') as fh:
                fh.write(output)
                if fmt != 'ndjson':
                    fh.write('\n')
            if not quiet:
                print(colors.format_msg(f'\n[+] Output saved to: {outfile}'))
        except OSError as exc:
            print(colors.format_msg(f'[!] Could not write to {outfile}: {exc}'), file=sys.stderr)
    else:
        if output:
            print('\n' + output)

    if network_html_file:
        _write_html(results, network_html_file, quiet)


def _write_html(results: list[dict], path: str, quiet: bool) -> None:
    try:
        with open(path, 'w') as fh:
            fh.write(render_html(results))
        if not quiet:
            print(colors.format_msg(f'[+] HTML page-link map saved to: {path}'))
    except OSError as exc:
        print(colors.format_msg(f'[!] Could not write to {path}: {exc}'), file=sys.stderr)
