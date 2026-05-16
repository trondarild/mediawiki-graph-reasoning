# Memex Graph DB Integration — Project Plan

## Overview

Augment the SemanticMediaWiki ("Memex") with a local graph database that an LLM (Claude Code) can query and update during inference and reasoning sessions. The wiki remains the authoritative human-readable store; the graph DB serves as a fast, LLM-native reasoning substrate.

## Context

- The wiki runs on shared hosting (`scribb.com`) — no persistent server processes possible there
- SemanticMediaWiki already stores semantic triples, but its query interface is not suited for LLM-native access
- The graph DB runs entirely locally
- Credentials and wiki API access follow the same pattern as the existing `memex-maintenance` repo (`.env` with `MEMEX_BOT_NAME`, `MEMEX_BOT_PASS`, `MEMEX_HTTP_USER`, `MEMEX_HTTP_PASS`)
- Wiki API endpoint: `https://scribb.com/memex/api.php`

## Technology Choice: Kuzu

Kuzu is an embedded graph database (like SQLite for graphs):
- No server process required — `pip install kuzu` is the entire setup
- Python-native bindings
- Cypher-compatible query language
- Fast, works offline
- Viable on any machine without infrastructure

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Claude Code session                                     │
│                                                          │
│  /memex-reason "query"                                   │
│       │                                                  │
│       ▼                                                  │
│  mmx_graph_query.py ──► Kuzu (local graph DB)           │
│       │                      ▲                          │
│       │                      │ sync                     │
│       │               mmx_graph_sync.py                 │
│       │                      │                          │
│       │               MediaWiki API (remote)            │
│       │                                                  │
│  Returns: relevant nodes + edges + source page refs      │
│       │                                                  │
│  Claude reasons, may write inferences back               │
│       │                                                  │
│       ▼                                                  │
│  mmx_graph_write.py ──► Kuzu (new "inferred" edges)     │
│  (optionally) ────────► wiki via create_mmx_page.py     │
└─────────────────────────────────────────────────────────┘
```

## Graph Schema

```
Node: Page       { title, url, wikitext, categories, last_synced }
Node: Concept    { name }
Edge: HAS_PROP   { property, value }   ← SMW semantic links
Edge: LINKS_TO   { }                   ← wiki wikilinks
Edge: INFERRED   { claim, confidence, session, timestamp }  ← LLM-derived
```

`categories` stores the wiki categories a page belongs to as a comma-separated string. This is a plain sync/labelling field. It is used by the categorical reasoning engine to determine each page's *object type* — wiki category membership (e.g., `Theory`, `Experiment`) serves as the proxy for typed object domains in the category-theoretic sense. The categorical structure itself (functors, diagrams, adjunctions) is not stored here; it is inferred at reasoning time by `mmx_graph_reason.py`.

The `INFERRED` edge type is the key distinction: Claude can write reasoning results back as a separate layer tagged with session and confidence, without touching authoritative wiki data.

## Components to Build

### 1. `mmx_graph_sync.py`
Pulls pages and SMW semantic properties from the wiki API into Kuzu.
- Designed to be run periodically (manually or via cron)
- Safe request rate: 1 req/sec to avoid hammering shared hosting

**Category exclusion**
Pages in the "Personal info" category (and all its subcategories) are excluded from sync. The exclusion list is built first via a recursive `action=query&list=categorymembers&cmtype=page|subcat` walk before any page fetching begins.

**Page title fetch**
`action=query&list=allpages` with `aplimit=500` — ~24 requests for 12k pages. Negligible time.

**Wikitext fetch**
`action=query&prop=revisions&titles=...` supports 50 titles per batch → ~240 requests at 1 req/sec ≈ 4 minutes for a full sync.

**SMW semantic property fetch**
Use batched `action=ask` with `|limit=500` and offset pagination — do NOT use per-page `action=smwbrowse` (that would require ~12,000 requests and take 3+ hours). Batched approach needs ~24 requests.

**Estimated full sync time: 10–15 minutes** for 12k pages. Incremental syncs (pages modified since `last_synced`) will be much faster.

**Incremental sync**
Track `last_synced` timestamp per page. On subsequent runs, use `action=query&list=recentchanges` or compare `last_synced` against the page's `touched` timestamp to skip unchanged pages.

### 2. `mmx_graph_query.py`
Given a keyword or natural-language query, retrieves relevant nodes and relationships from Kuzu and returns structured text for Claude to reason over, including source page references.

### 3. `~/.claude/commands/memex-reason.md`
A global Claude Code skill (available across all projects) that:
- Invokes `mmx_graph_query.py` with the user's query
- Feeds results to Claude as grounding context
- Prompts Claude to cite source pages in its conclusion
- Optionally prompts Claude to write inferences back via `mmx_graph_write.py`

### 4. `mmx_graph_write.py`
Writes LLM-derived inferences back to the Kuzu graph as `INFERRED` edges. Optionally creates wiki pages for significant conclusions via the MediaWiki API.

### 5. `mmx_graph_reason.py` — Categorical reasoning engine

Implements a category-theoretic interpretation of the knowledge graph. The key conceptual move: SMW semantic properties are not merely labelled edges — they are treated as *functors* between typed object domains. Wiki category membership (e.g., `Theory`, `Experiment`, `Phenomenon`) serves as the proxy for defining those domains; pages in the same wiki category are objects of the same categorical type. The category-theoretic structure (functors, commuting diagrams, fiber products, adjunctions) is not stored in the graph — it is inferred at reasoning time over the typed graph data.

**Property type signatures**
Each SMW property is declared as a typed functor signature: a mapping from one object domain (identified by wiki category name) to another. These signatures are stored in a committed config file `property_types.json` (not gitignored — no secrets, just schema). Example:

```json
{
  "explains":   { "from": "Theory",     "to": "Phenomenon" },
  "tests":      { "from": "Experiment", "to": "Theory"     },
  "measures":   { "from": "Experiment", "to": "Phenomenon" },
  "reports":    { "from": "Paper",      "to": "Dataset"    },
  "simulates":  { "from": "Simulation", "to": "Theory"     }
}
```

This file is maintained by the user and extended as new typed properties are identified.

**Reasoning operations**

*Diagram completion (missing edge detection)*
Compose two compatible property mappings and check whether the implied direct edge exists. Example:
- `Experiment --tests--> Theory --explains--> Phenomenon`
- If `Experiment --measures--> Phenomenon` is absent, flag it as a candidate `INFERRED` edge.

*Fiber products (convergence detection)*
For two properties sharing the same codomain (e.g., `tests` and `simulates` both mapping to `Theory`), find pairs `(Experiment, Simulation)` that target the same Theory — representing empirical validation structures.

*Adjunction gap detection*
Find asymmetric coverage across the theory–phenomenon–experiment triad:
- Phenomena explained by theories but not measured by any experiment → candidate "experiment needed" tasks
- Experiments measuring phenomena not explained by any theory → candidate "theory needed" tasks

**Output**
All proposed relations are written as `INFERRED` edges with `claim` describing the categorical rule that generated them (e.g., `"diagram_completion: tests∘explains"`), a `confidence` score, and the current session timestamp. They are never written directly to the wiki without human review.

## Security and Local Configuration

This is a public repository. Credentials and machine-specific paths must never be committed.

### `.gitignore` design

The following must be gitignored:

```
# Credentials and local config
.env
config.local.toml

# Kuzu database files (contain wiki content, local path-specific)
kuzu_db/
*.kuzu

# Python artifacts
__pycache__/
*.py[cod]
*.egg-info/
.venv/
dist/

# OS and editor noise
.DS_Store
*.swp
```

### Local configuration system

All environment-specific values are sourced from a single gitignored file. Scripts load config via `python-dotenv` from `.env` (or a `config.local.toml` if structured config is preferred later).

**Committed to repo:** `config.example.env` — documents every required key with placeholder values:

```ini
# MediaWiki bot credentials
MEMEX_BOT_NAME=YourBotName
MEMEX_BOT_PASS=your-bot-password

# HTTP Basic Auth (if wiki is behind HTTP auth)
MEMEX_HTTP_USER=your-http-user
MEMEX_HTTP_PASS=your-http-password

# Wiki API endpoint
MEMEX_API_URL=https://scribb.com/memex/api.php

# Local path to the Kuzu database directory
MEMEX_DB_PATH=/absolute/path/to/kuzu_db
```

**Not committed:** `.env` — copy of `config.example.env` with real values filled in.

Setup for a new machine: `cp config.example.env .env` then fill in real values.

All Python scripts load config at startup:

```python
from dotenv import load_dotenv
import os

load_dotenv()
BOT_NAME = os.environ["MEMEX_BOT_NAME"]
DB_PATH  = os.environ["MEMEX_DB_PATH"]
# etc.
```

Scripts should fail fast with a clear message if a required env var is missing, rather than silently using a wrong default.

## What This Enables

- Claude can answer questions grounded in wiki content with explicit page citations
- Inferences from one session persist and are available in future sessions
- The graph accumulates a layer of LLM-derived knowledge on top of the human-authored wiki
- The two stores stay in sync: wiki is the authoritative editable record; graph is the fast reasoning substrate
