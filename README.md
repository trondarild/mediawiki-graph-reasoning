# mediawiki-graph-reasoning

A local graph reasoning layer for a SemanticMediaWiki instance ("Memex", running at `scribb.com/memex`). The wiki is the authoritative human-readable store; the local [Kuzu](https://kuzudb.com/) graph database is a fast, LLM-native reasoning substrate that Claude Code can query, reason over, and write inferences back to.

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
mmx_graph_write.py ──► Kuzu (INFERRED edges)
(optionally) ────────► wiki via mmxpush (new pages)
                        or mmx_wiki_edit.py (append to existing pages)

mmx_graph_export.py ──► JSON (for external consumers)
```

## Setup

### 1. Clone and create environment

```bash
git clone <repo>
cd mediawiki-graph-reasoning
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp config.example.env .env
# Edit .env and fill in:
#   MEMEX_BOT_NAME, MEMEX_BOT_PASS   — wiki bot account
#   MEMEX_HTTP_USER, MEMEX_HTTP_PASS — HTTP Basic Auth (if applicable)
#   MEMEX_API_URL                    — wiki API endpoint
#   MEMEX_DB_PATH                    — absolute path for local Kuzu DB file
#   MEMEX_LOCAL_ARTICLES, MEMEX_LOCAL_ZOTERO, MEMEX_LOCAL_BOOKS — local source dirs
```

### 3. Initialise the database

```bash
python mmx_graph_init.py
```

### 4. Sync from wiki (first time: full sync, ~30–45 min)

```bash
python mmx_graph_sync.py
```

Subsequent syncs use `--incremental` (only pages changed since last sync):

```bash
python mmx_graph_sync.py --incremental
```

After every sync, the DB file size is printed and warned if it looks bloated (>500 MB warning, >1 GB critical). The current clean baseline is ~176 MB for ~11 K pages.

---

## Scripts

### `mmx_graph_sync.py` — Sync wiki → graph

```bash
python mmx_graph_sync.py               # full sync (requires empty DB)
python mmx_graph_sync.py --incremental # sync only changed pages
```

The full sync guard will abort if the DB already has data, preventing edge duplication. To rebuild: see [Rebuilding the database](#rebuilding-the-database).

### `mmx_graph_query.py` — Query the graph

```bash
python mmx_graph_query.py "free energy principle"
```

Returns structured text with semantic properties, wikilinks, and content excerpts — suitable for LLM grounding. Also importable as a Python module:

```python
from mmx_graph_query import query, search_by_title, get_page_properties
results = query("predictive processing")
```

### `mmx_graph_write.py` — Write inferred edges

```bash
# Write a single edge
python mmx_graph_write.py "Source page" "Target page" "claim description" 0.85

# List all inferred edges
python mmx_graph_write.py

# Export inferred edges to JSON (before a rebuild)
python mmx_graph_write.py --export
python mmx_graph_write.py --export /path/to/backup.json

# Re-import after rebuild
python mmx_graph_write.py --import
python mmx_graph_write.py --import /path/to/backup.json
```

### `mmx_graph_export.py` — Export subgraphs for external consumers

Exports data in schema v1.0 JSON (see module docstring for full schema).

```bash
# Export pages reachable from a seed concept (BFS depth 2)
python mmx_graph_export.py --seed "Heart" --depth 2 --output heart.json

# Export all pages in a wiki category
python mmx_graph_export.py --category "Neuroscience" --output neuro.json

# Find multi-level Consists-of chains (complexification candidates)
python mmx_graph_export.py --complexification --output candidates.json

# Include INFERRED edges in any export
python mmx_graph_export.py --seed "Attention" --inferred --output attention.json
```

Also importable:

```python
from mmx_graph_export import export_subgraph, export_by_category, complexification_candidates

data = export_subgraph("Predictive processing", depth=2)
chains = complexification_candidates(min_depth=2)
```

### `mmx_local_index.py` — Index local papers and books

```bash
python mmx_local_index.py --build            # build index from source dirs in .env
python mmx_local_index.py --search "keyword" # search by title
```

The index (`local_sources.json`) is gitignored and must be rebuilt on each machine.

### `mmx_graph_init.py` — Initialise schema

Only needed when creating a fresh database. Run this after deleting the DB file.

### `probe_kuzu.py` — Diagnostic probe

```bash
python probe_kuzu.py          # open DB with 4 GB buffer pool, count nodes
python probe_kuzu.py 6        # try with 6 GB buffer pool
```

Useful for verifying the DB is accessible after a rebuild.

---

## Claude Code skills

The following slash commands are available when working in this directory with Claude Code:

| Command | Description |
|---------|-------------|
| `/memex-reason "query"` | Query graph + local sources, reason over results |
| `/mmxentry "Page name"` | Generate a MediaWiki wiki entry for a concept |
| `/mmxpaper` | Generate a wiki article from a local PDF |
| `/mmxsearch "topic"` | Search OpenAlex for scientific papers |

---

## Rebuilding the database

The Kuzu DB file grows over time due to copy-on-write storage (no VACUUM in Kuzu). When the size warning fires, rebuild:

```bash
# 1. Export INFERRED edges so they survive the rebuild
python mmx_graph_write.py --export

# 2. Drop and reinitialise
rm kuzu_db kuzu_db.wal
python mmx_graph_init.py

# 3. Full sync from wiki (~30–45 min)
python mmx_graph_sync.py

# 4. Restore inferred edges
python mmx_graph_write.py --import
```

---

## Migrating to a new machine

1. Copy `.env` (credentials — never commit this)
2. Clone the repo and run setup steps 1–4 above
3. Copy `inferred_edges.json` if you want to preserve local inferences, then run `python mmx_graph_write.py --import`
4. Rebuild `local_sources.json` on the new machine: `python mmx_local_index.py --build`

The Kuzu DB file does **not** need to be transferred — it is fully reconstructible from the wiki via `mmx_graph_sync.py`.

---

## Graph schema

```
Node: Page       { title, url, wikitext, categories, last_synced }
Node: Concept    { name }
Edge: HAS_PROP   { property, value }     ← SMW semantic links (Has subtype, Consists of, Displays, …)
Edge: LINKS_TO   { }                     ← wiki wikilinks
Edge: INFERRED   { claim, confidence, session, timestamp }  ← LLM-derived
```

Key rule: the wiki is authoritative. Never modify `Page` nodes directly — use `mmx_graph_sync.py` to pull from the wiki. All LLM-derived knowledge goes into `INFERRED` edges only.
