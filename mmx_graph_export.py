"""
Export subgraphs from the Kuzu graph database for external consumer processes
(e.g. categorical sheaf project, textbook-index project).

Usage:
    python mmx_graph_export.py --seed "Heart" [--depth 2] [--output out.json] [--inferred]
    python mmx_graph_export.py --category "Neuroscience" [--output out.json] [--inferred]
    python mmx_graph_export.py --complexification [--min-depth 2] [--output candidates.json]

--- Schema v1.0 ---
{
  "version": "1.0",
  "generated": "<ISO timestamp>",
  "seed": "<seed string>",
  "nodes": [
    {
      "title": "<page title>",
      "url": "<wiki URL>",
      "categories": ["<cat>", ...],
      "subtypes": ["<title>", ...],    // pages this page HAS_SUBTYPE
      "supertypes": ["<title>", ...],  // pages that have this page as a subtype
      "parts": ["<title>", ...],       // pages this page CONSISTS_OF
      "wholes": ["<title>", ...],      // pages this page is a part of
      "properties": [["<prop>", "<value>"], ...],  // remaining SMW props
      "wikilinks": ["<title>", ...]
    }
  ],
  "inferred_edges": [   // only if --inferred requested
    {"source": "...", "target": "...", "claim": "...", "confidence": 0.9, "session": "..."}
  ]
}

Importable API:
    from mmx_graph_export import export_subgraph, export_by_category, complexification_candidates
"""

import json
import os
import sys
import kuzu
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("MEMEX_DB_PATH")
if not DB_PATH:
    raise RuntimeError("MEMEX_DB_PATH is not set.")

STRUCTURAL_PROPS = {"Has subtype", "Consists of"}


def _open_conn():
    db = kuzu.Database(DB_PATH)
    return kuzu.Connection(db)


def _get_node(conn, title):
    """Fetch a single page's full export record."""
    r = conn.execute(
        "MATCH (p:Page {title: $t}) RETURN p.url, p.categories",
        {"t": title}
    )
    if not r.has_next():
        return None
    url, cats_raw = r.get_next()
    categories = [c for c in (cats_raw or "").split("|") if c]

    subtypes, parts, other_props = [], [], []
    r2 = conn.execute(
        "MATCH (p:Page {title: $t})-[e:HAS_PROP]->(c:Concept) RETURN e.property, c.name",
        {"t": title}
    )
    while r2.has_next():
        prop, val = r2.get_next()
        if prop == "Has subtype":
            subtypes.append(val)
        elif prop == "Consists of":
            parts.append(val)
        else:
            other_props.append([prop, val])

    supertypes = []
    r3 = conn.execute(
        "MATCH (p:Page)-[e:HAS_PROP {property: 'Has subtype'}]->(c:Concept {name: $t}) "
        "RETURN p.title",
        {"t": title}
    )
    while r3.has_next():
        supertypes.append(r3.get_next()[0])

    wholes = []
    r4 = conn.execute(
        "MATCH (p:Page)-[e:HAS_PROP {property: 'Consists of'}]->(c:Concept {name: $t}) "
        "RETURN p.title",
        {"t": title}
    )
    while r4.has_next():
        wholes.append(r4.get_next()[0])

    wikilinks = []
    r5 = conn.execute(
        "MATCH (a:Page {title: $t})-[:LINKS_TO]->(b:Page) RETURN b.title LIMIT 50",
        {"t": title}
    )
    while r5.has_next():
        wikilinks.append(r5.get_next()[0])

    return {
        "title": title,
        "url": url,
        "categories": categories,
        "subtypes": subtypes,
        "supertypes": supertypes,
        "parts": parts,
        "wholes": wholes,
        "properties": other_props,
        "wikilinks": wikilinks,
    }


def _get_inferred(conn):
    edges = []
    r = conn.execute(
        "MATCH (a:Page)-[e:INFERRED]->(b:Page) "
        "RETURN a.title, b.title, e.claim, e.confidence, e.session"
    )
    while r.has_next():
        src, dst, claim, conf, sess = r.get_next()
        edges.append({"source": src, "target": dst, "claim": claim,
                      "confidence": conf, "session": sess})
    return edges


def _bfs_titles(conn, seed_titles, depth):
    """BFS from seed_titles following structural (has_subtype, consists_of) and wikilink edges."""
    visited = set(seed_titles)
    frontier = set(seed_titles)
    for _ in range(depth):
        if not frontier:
            break
        next_frontier = set()
        # Follow Has subtype and Consists of via Concept nodes to Pages
        placeholders = ", ".join(f"$t{i}" for i in range(len(frontier)))
        params = {f"t{i}": t for i, t in enumerate(frontier)}
        for prop in ("Has subtype", "Consists of"):
            r = conn.execute(
                f"MATCH (a:Page)-[e:HAS_PROP {{property: '{prop}'}}]->(c:Concept) "
                f"WHERE a.title IN [{placeholders}] "
                f"MATCH (b:Page {{title: c.name}}) RETURN b.title",
                params
            )
            while r.has_next():
                t = r.get_next()[0]
                if t not in visited:
                    next_frontier.add(t)
                    visited.add(t)
        # Also follow reverse (supertypes and wholes)
        for prop in ("Has subtype", "Consists of"):
            r = conn.execute(
                f"MATCH (a:Page)-[e:HAS_PROP {{property: '{prop}'}}]->(c:Concept) "
                f"WHERE c.name IN [{placeholders}] RETURN a.title",
                params
            )
            while r.has_next():
                t = r.get_next()[0]
                if t not in visited:
                    next_frontier.add(t)
                    visited.add(t)
        frontier = next_frontier
    return visited


def export_subgraph(seed, depth=2, include_inferred=False, conn=None):
    """
    Export all pages reachable from `seed` within `depth` hops via structural relations.
    Returns the export dict (schema v1.0).
    """
    own_conn = conn is None
    if own_conn:
        conn = _open_conn()

    # Find seed pages by title match
    r = conn.execute(
        "MATCH (p:Page) WHERE lower(p.title) CONTAINS lower($kw) RETURN p.title LIMIT 10",
        {"kw": seed}
    )
    seed_titles = []
    while r.has_next():
        seed_titles.append(r.get_next()[0])

    if not seed_titles:
        return {"version": "1.0", "generated": datetime.now(timezone.utc).isoformat(),
                "seed": seed, "nodes": [], "inferred_edges": []}

    all_titles = _bfs_titles(conn, seed_titles, depth)
    nodes = [n for t in all_titles if (n := _get_node(conn, t)) is not None]

    result = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "nodes": nodes,
    }
    if include_inferred:
        result["inferred_edges"] = _get_inferred(conn)

    return result


def export_by_category(category, include_inferred=False, conn=None):
    """
    Export all pages belonging to a wiki category.
    Returns the export dict (schema v1.0).
    """
    own_conn = conn is None
    if own_conn:
        conn = _open_conn()

    r = conn.execute(
        "MATCH (p:Page) WHERE p.categories CONTAINS $cat RETURN p.title",
        {"cat": category}
    )
    titles = []
    while r.has_next():
        titles.append(r.get_next()[0])

    nodes = [n for t in titles if (n := _get_node(conn, t)) is not None]

    result = {
        "version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "seed": f"category:{category}",
        "nodes": nodes,
    }
    if include_inferred:
        result["inferred_edges"] = _get_inferred(conn)

    return result


def complexification_candidates(min_depth=2, conn=None):
    """
    Find multi-level 'Consists of' chains in the graph — candidate complexification
    relations for the categorical sheaf project (e.g. cell → tissue → organ → organism).

    Returns a list of chains: [{"chain": ["A", "B", "C"], "depth": 3}, ...]
    Chains are deduped and sorted by depth descending.
    """
    own_conn = conn is None
    if own_conn:
        conn = _open_conn()

    # 2-hop chains
    r = conn.execute("""
        MATCH (a:Page)-[e1:HAS_PROP {property: 'Consists of'}]->(c1:Concept)
        MATCH (b:Page {title: c1.name})-[e2:HAS_PROP {property: 'Consists of'}]->(c2:Concept)
        RETURN a.title, c1.name, c2.name
    """)
    two_hop = []
    while r.has_next():
        two_hop.append(r.get_next())

    # 3-hop chains
    r = conn.execute("""
        MATCH (a:Page)-[e1:HAS_PROP {property: 'Consists of'}]->(c1:Concept)
        MATCH (b:Page {title: c1.name})-[e2:HAS_PROP {property: 'Consists of'}]->(c2:Concept)
        MATCH (c:Page {title: c2.name})-[e3:HAS_PROP {property: 'Consists of'}]->(c3:Concept)
        RETURN a.title, c1.name, c2.name, c3.name
    """)
    three_hop = []
    while r.has_next():
        three_hop.append(r.get_next())

    chains = []
    seen = set()

    for row in three_hop:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            chains.append({"chain": list(row), "depth": 4})
        # Mark the 2-hop prefix as seen so we don't duplicate
        seen.add(tuple(row[:3]))

    for row in two_hop:
        key = tuple(row)
        if key not in seen and len(row) >= min_depth + 1:
            seen.add(key)
            chains.append({"chain": list(row), "depth": 3})

    chains.sort(key=lambda x: x["depth"], reverse=True)
    return chains


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export Memex subgraphs for external consumers.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--seed", help="Seed concept title (substring match)")
    group.add_argument("--category", help="Wiki category name")
    group.add_argument("--complexification", action="store_true",
                       help="Find multi-level Consists-of chains")
    parser.add_argument("--depth", type=int, default=2,
                        help="BFS depth for --seed (default: 2)")
    parser.add_argument("--min-depth", type=int, default=2,
                        help="Minimum chain length for --complexification (default: 2)")
    parser.add_argument("--inferred", action="store_true",
                        help="Include INFERRED edges in export")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.complexification:
        data = {
            "version": "1.0",
            "generated": datetime.now(timezone.utc).isoformat(),
            "seed": "complexification",
            "chains": complexification_candidates(min_depth=args.min_depth),
        }
    elif args.seed:
        data = export_subgraph(args.seed, depth=args.depth,
                               include_inferred=args.inferred)
    else:
        data = export_by_category(args.category, include_inferred=args.inferred)

    out = json.dumps(data, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(out)
        node_count = len(data.get("nodes") or data.get("chains", []))
        print(f"Exported {node_count} item(s) to {args.output}")
    else:
        print(out)
