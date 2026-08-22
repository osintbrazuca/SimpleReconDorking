"""
Dork-result graph builder.

Converts a per-run result dict (as produced by Engine.run()) into a
node/edge structure suitable for graph visualization (vis-network, cytoscape,
gephi, etc.). Models a three-tier star: target -> dork -> URL, plus a direct
target -> filtered edge for URLs excluded by an active --filter-* alongside
the run (those carry no dork attribution - see core/engine.py's extras
handling).

This is "which dork found which URL," not a link graph - dorking has no page
adjacency to track the way a crawler does.

Pure function - no I/O, no global state.
"""
from __future__ import annotations


_TYPE_COLORS = {
    'target':   '#1976d2',  # blue
    'dork':     '#8e24aa',  # purple - the query itself
    'url':      '#9e9e9e',  # gray
    'filtered': '#757575',  # darker gray - excluded by an active --filter-*
}


def build_network_graph(result: dict) -> dict:
    """
    Build a target -> dork -> URL graph from a per-run result dict.

    Returns:
        {
          'nodes': [{'id', 'label', 'type', 'color', ...}, ...],
          'edges': [{'from', 'to', 'relation'}, ...],
          'stats': {'targets', 'dorks', 'urls', 'filtered', 'edges'},
        }
    """
    seed: str = result.get('seed', '') or '(no target)'
    dorks: list = result.get('dorks', []) or []
    urls: set = result.get('urls', set()) or set()
    url_sources: dict = result.get('url_sources', {}) or {}
    url_dorks: dict = result.get('url_dorks', {}) or {}
    extras: dict = result.get('extras', {}) or {}
    filtered_urls: set = extras.get('urls_filtered', set()) or set()

    nodes: list[dict] = []
    edges: list[dict] = []
    seen_ids: set[str] = set()

    def add_node(node_id: str, **attrs) -> None:
        if not node_id or node_id in seen_ids:
            return
        seen_ids.add(node_id)
        attrs['id'] = node_id
        nodes.append(attrs)

    def add_edge(src: str, dst: str, relation: str) -> None:
        if not src or not dst or src == dst:
            return
        edges.append({'from': src, 'to': dst, 'relation': relation})

    # ── Root target node ──────────────────────────────────────────────
    add_node(seed, label=seed, type='target', color=_TYPE_COLORS['target'], group=seed)

    # ── Dork nodes + target -> dork edges ───────────────────────────
    dork_id = {d: f'dork:{d}' for d in dorks}
    for d, did in dork_id.items():
        add_node(did, label=d, type='dork', color=_TYPE_COLORS['dork'], group=seed)
        add_edge(seed, did, 'ran')

    # ── URL nodes + dork -> url edges ───────────────────────────────
    for url in sorted(urls):
        add_node(
            url,
            label=url,
            type='url',
            color=_TYPE_COLORS['url'],
            source=url_sources.get(url, '') or '',
            group=seed,
        )
        parent = dork_id.get(url_dorks.get(url, ''), seed)
        add_edge(parent, url, 'found')

    # ── Filtered-out URL nodes ────────────────────────────────────────
    for url in sorted(filtered_urls):
        add_node(url, label=url, type='filtered', color=_TYPE_COLORS['filtered'])
        add_edge(seed, url, 'found_filtered')

    # ── Stats ────────────────────────────────────────────────────────
    counts: dict = {'targets': 0, 'dorks': 0, 'urls': 0, 'filtered': 0}
    for n in nodes:
        t = n.get('type', '')
        key = {'target': 'targets', 'dork': 'dorks', 'url': 'urls', 'filtered': 'filtered'}.get(t)
        if key:
            counts[key] += 1
    counts['edges'] = len(edges)

    return {'nodes': nodes, 'edges': edges, 'stats': counts}


def merge_graphs(graphs: list[dict]) -> dict:
    """Combine multiple per-run graphs into a single graph (dedup nodes)."""
    nodes_by_id: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edges: set[tuple] = set()

    for g in graphs:
        for n in g.get('nodes', []):
            nid = n.get('id')
            if nid and nid not in nodes_by_id:
                nodes_by_id[nid] = n
        for e in g.get('edges', []):
            key = (e.get('from'), e.get('to'), e.get('relation'))
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append(e)

    merged_nodes = list(nodes_by_id.values())
    counts: dict = {'targets': 0, 'dorks': 0, 'urls': 0, 'filtered': 0}
    for n in merged_nodes:
        t = n.get('type', '')
        key = {'target': 'targets', 'dork': 'dorks', 'url': 'urls', 'filtered': 'filtered'}.get(t)
        if key:
            counts[key] += 1
    counts['edges'] = len(edges)

    return {'nodes': merged_nodes, 'edges': edges, 'stats': counts}
