"""
Query the Kuzu graph database for pages relevant to a keyword or topic.

Usage:
    python mmx_graph_query.py "your query here"

Output is structured text suitable for feeding to an LLM as grounding context.
"""

import os
import sys
import kuzu
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("MEMEX_DB_PATH")
if not DB_PATH:
    raise RuntimeError("MEMEX_DB_PATH is not set. Copy config.example.env to .env and fill in values.")


def open_connection():
    db = kuzu.Database(DB_PATH)
    return kuzu.Connection(db)


# --- Search functions ---

def search_by_title(conn, keyword, limit=20):
    """Find pages whose title contains the keyword (case-insensitive)."""
    result = conn.execute(
        "MATCH (p:Page) WHERE lower(p.title) CONTAINS lower($kw) "
        "RETURN p.title, p.url LIMIT $limit",
        {"kw": keyword, "limit": limit}
    )
    pages = []
    while result.has_next():
        row = result.get_next()
        pages.append({"title": row[0], "url": row[1]})
    return pages


def search_by_concept(conn, keyword, limit=20):
    """Find pages related to a concept whose name contains the keyword."""
    result = conn.execute(
        "MATCH (p:Page)-[e:HAS_PROP]->(c:Concept) "
        "WHERE lower(c.name) CONTAINS lower($kw) "
        "RETURN p.title, p.url, e.property, c.name LIMIT $limit",
        {"kw": keyword, "limit": limit}
    )
    pages = []
    seen = set()
    while result.has_next():
        row = result.get_next()
        if row[0] not in seen:
            pages.append({"title": row[0], "url": row[1]})
            seen.add(row[0])
    return pages


# --- Relationship traversal ---

def get_page_properties(conn, title):
    """Get all SMW semantic properties for a page."""
    result = conn.execute(
        "MATCH (p:Page {title: $title})-[e:HAS_PROP]->(c:Concept) "
        "RETURN e.property, c.name",
        {"title": title}
    )
    props = []
    while result.has_next():
        row = result.get_next()
        props.append((row[0], row[1]))
    return props


def get_outlinks(conn, title, limit=8):
    """Get pages this page links to."""
    result = conn.execute(
        "MATCH (a:Page {title: $title})-[:LINKS_TO]->(b:Page) "
        "RETURN b.title, b.url LIMIT $limit",
        {"title": title, "limit": limit}
    )
    pages = []
    while result.has_next():
        row = result.get_next()
        pages.append({"title": row[0], "url": row[1]})
    return pages


def get_backlinks(conn, title, limit=8):
    """Get pages that link to this page."""
    result = conn.execute(
        "MATCH (a:Page)-[:LINKS_TO]->(b:Page {title: $title}) "
        "RETURN a.title, a.url LIMIT $limit",
        {"title": title, "limit": limit}
    )
    pages = []
    while result.has_next():
        row = result.get_next()
        pages.append({"title": row[0], "url": row[1]})
    return pages


def get_wikitext(conn, title):
    result = conn.execute(
        "MATCH (p:Page {title: $title}) RETURN p.wikitext",
        {"title": title}
    )
    if result.has_next():
        return result.get_next()[0] or ""
    return ""


# --- Output formatting ---

def wikitext_excerpt(wikitext, keyword, context_chars=300):
    """Return a snippet of wikitext around the first occurrence of keyword."""
    idx = wikitext.lower().find(keyword.lower())
    if idx == -1:
        return wikitext[:context_chars].strip()
    start = max(0, idx - context_chars // 2)
    end = min(len(wikitext), idx + context_chars // 2)
    snippet = wikitext[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(wikitext):
        snippet = snippet + "..."
    return snippet


def format_page(conn, page, keyword):
    """Format a single page as structured LLM-readable context."""
    title = page["title"]
    url = page["url"]
    lines = [f"### {title}", f"Source: {url}"]

    props = get_page_properties(conn, title)
    if props:
        lines.append("Semantic properties:")
        for prop, val in props:
            lines.append(f"  {prop}: {val}")

    outlinks = get_outlinks(conn, title)
    if outlinks:
        lines.append("Links to: " + ", ".join(p["title"] for p in outlinks))

    backlinks = get_backlinks(conn, title)
    if backlinks:
        lines.append("Linked from: " + ", ".join(p["title"] for p in backlinks))

    wikitext = get_wikitext(conn, title)
    if wikitext:
        lines.append("Content excerpt:")
        lines.append(wikitext_excerpt(wikitext, keyword))

    return "\n".join(lines)


# --- Main entry point ---

def query(keyword, limit=5):
    """
    Given a keyword, search the graph and return structured context for LLM grounding.
    Tries title search first, falls back to concept search if no results.
    """
    conn = open_connection()

    pages = search_by_title(conn, keyword, limit=limit)
    if not pages:
        pages = search_by_concept(conn, keyword, limit=limit)
    if not pages:
        return f"No pages found matching '{keyword}'."

    sections = [f"# Memex graph results for: '{keyword}'\n"]
    for page in pages:
        sections.append(format_page(conn, page, keyword))
        sections.append("")

    return "\n".join(sections)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mmx_graph_query.py <keyword>")
        sys.exit(1)
    print(query(" ".join(sys.argv[1:])))
