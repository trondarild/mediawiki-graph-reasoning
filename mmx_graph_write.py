"""
Write LLM-derived inferences back to the Kuzu graph as INFERRED edges.

Usage:
    python mmx_graph_write.py <source_title> <target_title> <claim> <confidence> [session]
    python mmx_graph_write.py --export [file]   # dump INFERRED edges to JSON (default: inferred_edges.json)
    python mmx_graph_write.py --import [file]   # reload INFERRED edges from JSON after a rebuild

Arguments:
    source_title  Title of the source Page node
    target_title  Title of the target Page node
    claim         Description of the inferred relationship (e.g. "diagram_completion: tests∘explains")
    confidence    Float between 0 and 1
    session       Optional session identifier (defaults to current timestamp)

Or import and call write_inference() directly from another script.
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
    raise RuntimeError("MEMEX_DB_PATH is not set. Copy config.example.env to .env and fill in values.")


def write_inference(source_title, target_title, claim, confidence, session=None):
    """
    Write an INFERRED edge from source_title to target_title.
    Both pages must already exist as Page nodes in the graph.
    Returns True if the edge was written, False if either page was not found.
    """
    if session is None:
        session = datetime.now(timezone.utc).isoformat()
    timestamp = datetime.now(timezone.utc).isoformat()
    confidence = float(confidence)

    db = kuzu.Database(DB_PATH)
    conn = kuzu.Connection(db)

    # Verify both pages exist
    for title in (source_title, target_title):
        r = conn.execute("MATCH (p:Page {title: $t}) RETURN count(p)", {"t": title})
        if r.get_next()[0] == 0:
            print(f"Page not found in graph: '{title}'")
            return False

    conn.execute(
        "MATCH (a:Page {title: $src}), (b:Page {title: $dst}) "
        "CREATE (a)-[:INFERRED {claim: $claim, confidence: $conf, session: $session, timestamp: $ts}]->(b)",
        {
            "src": source_title,
            "dst": target_title,
            "claim": claim,
            "conf": confidence,
            "session": session,
            "ts": timestamp,
        }
    )
    print(f"Inferred: '{source_title}' -> '{target_title}'")
    print(f"  Claim:      {claim}")
    print(f"  Confidence: {confidence}")
    print(f"  Session:    {session}")
    return True


def list_inferences(limit=20):
    """Print all INFERRED edges currently in the graph."""
    db = kuzu.Database(DB_PATH)
    conn = kuzu.Connection(db)
    r = conn.execute(
        "MATCH (a:Page)-[e:INFERRED]->(b:Page) "
        "RETURN a.title, b.title, e.claim, e.confidence, e.session "
        "ORDER BY e.timestamp DESC LIMIT $limit",
        {"limit": limit}
    )
    count = 0
    while r.has_next():
        src, dst, claim, conf, sess = r.get_next()
        print(f"{src} -> {dst}")
        print(f"  {claim} (confidence: {conf}, session: {sess})")
        count += 1
    if count == 0:
        print("No inferred edges found.")


DEFAULT_EXPORT_PATH = os.path.join(os.path.dirname(__file__), "inferred_edges.json")


def export_inferences(path=None):
    """Dump all INFERRED edges to a JSON file so they survive a DB rebuild."""
    path = path or DEFAULT_EXPORT_PATH
    db = kuzu.Database(DB_PATH)
    conn = kuzu.Connection(db)
    r = conn.execute(
        "MATCH (a:Page)-[e:INFERRED]->(b:Page) "
        "RETURN a.title, b.title, e.claim, e.confidence, e.session, e.timestamp"
    )
    edges = []
    while r.has_next():
        src, dst, claim, conf, session, ts = r.get_next()
        edges.append({"source": src, "target": dst, "claim": claim,
                      "confidence": conf, "session": session, "timestamp": ts})
    with open(path, "w") as f:
        json.dump(edges, f, indent=2)
    print(f"Exported {len(edges)} INFERRED edge(s) to {path}")


def import_inferences(path=None):
    """Reload INFERRED edges from a JSON export after a DB rebuild."""
    path = path or DEFAULT_EXPORT_PATH
    if not os.path.exists(path):
        print(f"No export file found at {path} — nothing to import.")
        return
    with open(path) as f:
        edges = json.load(f)
    ok = skipped = 0
    for e in edges:
        result = write_inference(e["source"], e["target"], e["claim"],
                                 e["confidence"], e["session"])
        if result:
            ok += 1
        else:
            skipped += 1
    print(f"Imported {ok} edge(s); {skipped} skipped (page not found in graph).")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        list_inferences()
        sys.exit(0)
    if sys.argv[1] == "--export":
        export_inferences(sys.argv[2] if len(sys.argv) > 2 else None)
        sys.exit(0)
    if sys.argv[1] == "--import":
        import_inferences(sys.argv[2] if len(sys.argv) > 2 else None)
        sys.exit(0)
    if len(sys.argv) < 5:
        print("Usage: python mmx_graph_write.py <source> <target> <claim> <confidence> [session]")
        sys.exit(1)
    source = sys.argv[1]
    target = sys.argv[2]
    claim  = sys.argv[3]
    conf   = sys.argv[4]
    sess   = sys.argv[5] if len(sys.argv) > 5 else None
    ok = write_inference(source, target, claim, float(conf), sess)
    sys.exit(0 if ok else 1)
