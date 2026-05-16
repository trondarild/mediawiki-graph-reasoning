# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Augment a SemanticMediaWiki instance ("Memex", running at `scribb.com`) with a local embedded graph database (Kuzu) that Claude Code can query and update during reasoning sessions. The wiki is the authoritative human-readable store; the graph DB is a fast, LLM-native reasoning substrate.

## Setup

```bash
pip install kuzu python-dotenv requests
```

Credentials use the same `.env` pattern as the `memex-maintenance` repo:

```
MEMEX_BOT_NAME=...
MEMEX_BOT_PASS=...
MEMEX_HTTP_USER=...
MEMEX_HTTP_PASS=...
```

Wiki API endpoint: `https://scribb.com/memex/api.php`

## Architecture

```
/memex-reason "query"
      │
      ▼
mmx_graph_query.py ──► Kuzu (local graph DB)
      │                      ▲
      │                      │ sync
      │               mmx_graph_sync.py
      │                      │
      │               MediaWiki API (remote)
      │
Claude reasons, may write inferences back
      │
      ▼
mmx_graph_write.py ──► Kuzu (new "inferred" edges)
(optionally) ────────► wiki via create_mmx_page.py
```

## Graph Schema

```
Node: Page       { title, url, wikitext, last_synced }
Node: Concept    { name }
Edge: HAS_PROP   { property, value }                           ← SMW semantic links
Edge: LINKS_TO   { }                                           ← wiki wikilinks
Edge: INFERRED   { claim, confidence, session, timestamp }     ← LLM-derived
```

`INFERRED` edges are the key distinction: Claude writes reasoning results as a separate layer tagged with session and confidence, without touching authoritative wiki data.

## Components

- **`mmx_graph_sync.py`** — Pulls pages and SMW semantic properties from the wiki API into Kuzu. Run manually or via cron. Uses `action=query&list=allpages` to enumerate pages and `action=ask` for semantic properties.
- **`mmx_graph_query.py`** — Given a query, retrieves relevant nodes and relationships from Kuzu; returns structured text with source page references for Claude to reason over.
- **`mmx_graph_write.py`** — Writes `INFERRED` edges to Kuzu with metadata; optionally creates wiki pages for conclusions via the MediaWiki API.
- **`~/.claude/commands/memex-reason.md`** — Global Claude Code skill that invokes `mmx_graph_query.py`, feeds results as grounding context, and instructs Claude to cite sources and optionally persist inferences.

## Constraints

- The wiki runs on shared hosting — no persistent server processes on the remote side.
- Kuzu is embedded (no server needed locally); the DB file lives in this repo or a configured path.
- Incremental sync should track `last_synced` to avoid re-fetching unchanged pages.

## For agent use

All commands must run from `/Users/trond/code/mediawiki-graph-reasoning/` (the `.venv` and `kuzu_db/` paths are relative to this directory).

**Query the graph:**
```bash
cd /Users/trond/code/mediawiki-graph-reasoning && .venv/bin/python mmx_graph_query.py "<query string>"
```

**Write an inferred edge:**
```bash
cd /Users/trond/code/mediawiki-graph-reasoning && .venv/bin/python mmx_graph_write.py "<source_title>" "<target_title>" "<claim>" <0.0-1.0> "<session_id>"
```

**Sync from wiki:**
```bash
cd /Users/trond/code/mediawiki-graph-reasoning && .venv/bin/python mmx_graph_sync.py --incremental
```

**Raw Kuzu (Python):**
```python
import kuzu
db = kuzu.Database("/Users/trond/code/mediawiki-graph-reasoning/kuzu_db")
conn = kuzu.Connection(db)
result = conn.execute("MATCH (p:Page) WHERE p.title CONTAINS 'foo' RETURN p.title, p.url")
```

**Key rule:** The wiki at `scribb.com/memex` is authoritative. Never modify `Page` nodes directly — use `mmx_graph_sync.py` to pull from the wiki. All agent-derived knowledge goes into `INFERRED` edges only.
