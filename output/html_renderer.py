"""
HTML renderer for the dork-result graph visualization.

Produces a self-contained HTML file that loads vis-network from a CDN and
renders the per-run graphs (built by output/graph.py) as an interactive
target -> dork -> URL node/edge diagram.
"""
from __future__ import annotations

import html
import json
from datetime import datetime

from output.graph import build_network_graph, merge_graphs


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SimpleReconDorking - Dork Map ({targets})</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #1e1e1e; color: #eaeaea; }}
  #wrap {{ display: flex; height: 100vh; }}
  #side {{ width: 280px; padding: 14px 16px; background: #252526; overflow-y: auto; box-shadow: 2px 0 6px rgba(0,0,0,.4); }}
  #side h1 {{ margin: 0 0 4px; font-size: 16px; color: #4fc3f7; }}
  #side .ts {{ font-size: 11px; color: #888; margin-bottom: 14px; }}
  #side h2 {{ margin: 14px 0 4px; font-size: 12px; text-transform: uppercase; color: #b0bec5; letter-spacing: .05em; }}
  #side ul {{ list-style: none; padding: 0; margin: 0; font-size: 13px; }}
  #side li {{ display: flex; align-items: center; padding: 3px 0; }}
  #side .dot {{ width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; display: inline-block; }}
  #side .count {{ margin-left: auto; color: #b0bec5; font-variant-numeric: tabular-nums; }}
  #side .targets {{ font-size: 12px; color: #cfd8dc; word-break: break-all; }}
  #net {{ flex: 1; background: #121212; }}
  #info {{ position: absolute; right: 14px; top: 14px; background: rgba(37,37,38,.95); padding: 8px 12px; border-radius: 4px; font-size: 12px; max-width: 380px; display: none; box-shadow: 0 2px 6px rgba(0,0,0,.5); }}
  #info pre {{ margin: 4px 0 0; font-size: 11px; white-space: pre-wrap; color: #b0bec5; }}
  .pill {{ display: inline-block; padding: 1px 6px; border-radius: 9px; font-size: 10px; background: #37474f; color: #cfd8dc; margin-left: 4px; }}
</style>
</head>
<body>
<div id="wrap">
  <aside id="side">
    <h1>Dork Map</h1>
    <div class="ts">{ts}</div>

    <h2>Targets</h2>
    <div class="targets">{targets_html}</div>

    <h2>Nodes</h2>
    <ul id="legend-nodes">
      <li><span class="dot" style="background:#1976d2"></span>target<span class="count">{c_targets}</span></li>
      <li><span class="dot" style="background:#8e24aa"></span>dork<span class="count">{c_dorks}</span></li>
      <li><span class="dot" style="background:#9e9e9e"></span>url<span class="count">{c_urls}</span></li>
      <li><span class="dot" style="background:#757575"></span>filtered<span class="count">{c_filtered}</span></li>
    </ul>

    <h2>Edges</h2>
    <ul>
      <li>ran / found<span class="count">{c_edges}</span></li>
    </ul>
  </aside>
  <main id="net"></main>
  <div id="info"></div>
</div>

<script>
const GRAPH = {graph_json};

const nodes = new vis.DataSet(GRAPH.nodes.map(n => ({{
  id: n.id,
  label: n.label || n.id,
  color: {{ background: n.color || '#9e9e9e', border: '#000', highlight: {{ background: n.color || '#9e9e9e', border: '#4fc3f7' }} }},
  shape: ({{ target: 'star', dork: 'diamond', url: 'dot', filtered: 'triangle' }})[n.type] || 'dot',
  size: n.type === 'target' ? 26 : (n.type === 'dork' ? 18 : (n.type === 'url' ? 14 : 10)),
  font: {{ color: '#eaeaea', size: 12, strokeWidth: 0 }},
  _meta: n,
}})));

const edges = new vis.DataSet(GRAPH.edges.map(e => ({{
  from: e.from,
  to: e.to,
  label: e.relation,
  arrows: 'to',
  color: {{ color: '#555', highlight: '#4fc3f7' }},
  font: {{ color: '#888', size: 9, strokeWidth: 0, align: 'middle' }},
  smooth: {{ type: 'continuous' }},
}})));

const network = new vis.Network(document.getElementById('net'),
  {{ nodes, edges }},
  {{
    physics: {{
      stabilization: {{ iterations: 200 }},
      barnesHut: {{ gravitationalConstant: -8000, springLength: 120, springConstant: 0.04, damping: 0.3 }},
    }},
    interaction: {{ hover: true, tooltipDelay: 200, navigationButtons: true, keyboard: true }},
    nodes: {{ borderWidth: 1 }},
  }}
);

const info = document.getElementById('info');
network.on('click', params => {{
  if (!params.nodes.length) {{ info.style.display = 'none'; return; }}
  const n = nodes.get(params.nodes[0]);
  const m = n._meta || {{}};
  const parts = [`<b>${{m.type}}</b> ${{m.id}}`];
  info.innerHTML = parts.join(' ');
  info.style.display = 'block';
}});
network.on('deselectNode', () => {{ info.style.display = 'none'; }});
</script>
</body>
</html>
"""


def render_html(results: list[dict]) -> str:
    """Render a single self-contained HTML page for *results*.

    Builds a per-run graph for each result, merges them into one combined
    view, then embeds the JSON payload into a vis-network template.
    """
    per_run = [build_network_graph(r) for r in results]
    merged = merge_graphs(per_run)
    stats = merged.get('stats', {})

    target_names = [r.get('seed', '') for r in results if r.get('seed')]
    targets_html = '<br>'.join(html.escape(t) for t in target_names) or '-'

    return _TEMPLATE.format(
        targets=html.escape(', '.join(target_names) or 'dork map'),
        targets_html=targets_html,
        ts=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        c_targets=stats.get('targets', 0),
        c_dorks=stats.get('dorks', 0),
        c_urls=stats.get('urls', 0),
        c_filtered=stats.get('filtered', 0),
        c_edges=stats.get('edges', 0),
        graph_json=json.dumps(merged, ensure_ascii=False),
    )
