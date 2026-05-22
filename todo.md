## Project setup
- [x] create local python environment and activate
- [x] Set up repo: create `config.example.env`, `.gitignore`, and `requirements.txt`
- [x] Install dependencies (`pip install kuzu python-dotenv requests`)
- [x] Define and initialize Kuzu schema (`mmx_graph_init.py`)

## Security and configuration

- [x] Design `.gitignore` to exclude credentials, local config, and environment-specific files (`.env`, `*.local.*`, Kuzu DB files, `__pycache__`, etc.)
- [x] Design local configuration system: all environment-specific values (wiki credentials, local DB path, HTTP auth) sourced from a single config file (`.env`) that is gitignored; repo ships only `config.example.env` with placeholder values and documentation of each key
- [x] implement .env file by copying from ~/code/memex_maintenance/.env
## Sync (`mmx_graph_sync.py`)
- [x] Recursively fetch exclusion list: all pages in category "Personal info" and its subcategories (`action=query&list=categorymembers&cmtype=page|subcat`)
- [x] Fetch all page titles (`action=query&list=allpages&aplimit=500`)
- [x] Fetch single batch of wikitext with 50 items (`action=query&prop=revisions&titles=...`)
- [x] Estimate time for full download based on single batch (11500 pages) — ~5 min for wikitext at 1.3s/batch
- [x] Fetch wikitext in batches of 50 (`action=query&prop=revisions&titles=...`)
- [x] Fetch SMW properties in batches of 500 via `action=ask` with offset pagination (not per-page `smwbrowse`)
- [x] Fetch and store wiki category membership per page (`action=query&prop=categories`) into the `categories` field — used by the reasoning engine to determine each page's object type
- [x] Populate Kuzu nodes (pages, with `categories` field) and edges (semantic properties, wikilinks)
- [x] Incremental sync: skip pages where `last_synced` is newer than wiki `touched` timestamp

## Query (`mmx_graph_query.py`)

- [x] Keyword/title search
- [x] Relationship traversal (e.g. pages linked to a concept)
- [x] Return format suitable for LLM context (structured text + page URLs)

## Write-back (`mmx_graph_write.py`)

- [x] Write inferred edges with metadata (claim, confidence, session, timestamp)
- [ ] Optional: push conclusions to wiki via MediaWiki API

## Claude Code skill (`~/.claude/commands/memex-reason.md`)

- [x] Invoke `mmx_graph_query.py` and feed results as grounding context
- [x] Instruct Claude to cite source pages in conclusions
- [x] Instruct Claude to optionally persist inferences via `mmx_graph_write.py`
- [x] support telling claude-code to do incremental sync between wiki and local graph db
## Categorical reasoning engine (`mmx_graph_reason.py`)

- [ ] Create `property_types.json`: declare each SMW property as a typed mapping `{ "from": "Category", "to": "Category" }` for the known property set (explains, tests, measures, reports, simulates, …)
- [ ] Implement page partitioning: load pages from Kuzu grouped by their `categories` field
- [ ] Implement diagram completion: for each composable property pair (A→B, B→C), query Kuzu for the implied direct edge (A→C) and flag absent ones as candidate `INFERRED` edges
- [ ] Implement fiber product detection: for properties sharing a codomain, find convergent pairs (e.g., Experiment + Simulation both targeting the same Theory)
- [ ] Implement adjunction gap detection: find phenomena explained but not measured, and experiments measuring phenomena with no explaining theory; emit as candidate tasks
- [ ] Write all candidates as `INFERRED` edges with `claim` naming the rule (e.g., `"diagram_completion: tests∘explains"`) and a confidence score
- [ ] Integrate with Claude Code skill: surface categorical candidates as part of `/memex-reason` output for human review before any wiki write-back

## Grounding in local sources

Local papers and books are stored at:
- `~/Articles/` — PDF/papers
- `~/Zotero/storage/` — Zotero-managed references
- `~/books/` — books

**Design decision pending:** should local source awareness be integrated into the existing `/memex-reason` skill, or implemented as a separate skill (e.g. `/memex-reason-deep`)? Integration keeps the workflow unified; separation avoids bloating every query with file-system lookups for cases where the wiki graph is sufficient.

- [x] Explore `~/Articles`, `~/Zotero/storage`, `~/books/` — 656 articles, 406 Zotero entries, ~111 books; all primarily PDF
- [x] Decide: integrate into `memex-reason` (single skill, graph + local sources together)
- [x] Add local source paths to `.env` / `config.example.env` (`MEMEX_LOCAL_ARTICLES`, `MEMEX_LOCAL_ZOTERO`, `MEMEX_LOCAL_BOOKS`)
- [x] Build a lightweight local index (`mmx_local_index.py --build` → `local_sources.json`, gitignored); 2414 entries indexed
- [x] At query time: surface title matches from local index alongside graph results; ask user whether to read the matched files
- [x] If user confirms reading: use Claude Code Read tool on matched files; offer to write graph inferences and push wiki entries via `mmxentrypush`
- [x] After reading local files: ask user whether to push new concepts to the wiki via `mmxentrypush` (usage: `echo "concept name" | mmxentrypush` in terminal)
- [x] Add support for local tool chain: `echo "<path>" | mmxpaper | mmxpush pagename="<Author Year - Title> (article)"`
## Email agent inbox (`agent@host.com` via IMAP)

Goal: Claude can read and act on emails sent to a dedicated address on the online server.

**Server setup (manual, one-time):**
- [ ] Create `agent@yourhost.com` in the server mail control panel
- [ ] Confirm IMAP access is enabled and note the IMAP hostname (port 993)
- [ ] Add credentials to `.env`: `AGENT_EMAIL`, `AGENT_EMAIL_PASS`, `AGENT_IMAP_HOST`
- [ ] Add placeholders to `config.example.env`

**Local implementation:**
- [ ] Write `mmx_mail.py`: connects via IMAP, fetches unread messages, parses sender/subject/body/attachments, marks as read, returns structured list
- [ ] Save PDF attachments to `~/Articles/` automatically
- [ ] Create `/mmxmail` Claude Code skill: runs `mmx_mail.py`, presents unread messages, and routes each one:
  - PDF attachment → offer to run `/mmxpaper <path>`
  - Body mentions a concept → offer to run `/mmxentry <concept>`
  - Otherwise → show message and offer to reply via SMTP
- [ ] Reply support: `mmx_mail.py --reply <message-id> <body>` sends via SMTP using same credentials
- [ ] Add `mmx_mail.py` Bash permission to `~/.claude/settings.json`

## Wiki entries: Move (rhetoric) subtypes

- [x] `/mmxentry "Assertion (move rhetoric)"`
- [x] `/mmxentry "Concession (move rhetoric)"`
- [x] `/mmxentry "Amplification (move rhetoric)"`
- [x] `/mmxentry "Authority appeal (move rhetoric)"`
- [x] `/mmxentry "Question raising (move rhetoric)"`
- [x] `/mmxentry "Register shift (move rhetoric)"`

## Wiki entries: Move subtypes

- [x] `/mmxentry "Move (rhetoric)"`
- [x] `/mmxentry "Move (dance)"`
- [x] `/mmxentry "Move (politics)"`

## Wiki entries: Move (philosophy) subtypes

- [x] `/mmxentry "Framing (move philosophy)"`
- [x] `/mmxentry "Conceding (move philosophy)"`
- [x] `/mmxentry "Distinguishing (move philosophy)"`
- [x] `/mmxentry "Motivating (move philosophy)"`
- [x] `/mmxentry "Blocking (move philosophy)"`

## Kuzu DB memory problem

The kuzu_db file has grown to 7.9GB. As of 2026-04-27, opening the database fails with:
`RuntimeError: Buffer manager exception: Unable to allocate memory! The buffer pool is full and no memory could be freed!`
Even with `buffer_pool_size=2GB` set. All graph queries and syncs are broken.

- [x] Clarify root cause: DB was massively bloated — 7.9GB; actual data fits in 176MB. Kuzu 0.11.3 (latest) has no VACUUM and could not open the DB even with 6GB buffer pool.
- [x] Rebuild: dropped kuzu_db, ran mmx_graph_init.py, full mmx_graph_sync.py — 11,287 pages, 19,416 HAS_PROP edges, 86,503 LINKS_TO edges; DB now 176MB (2026-05-07)
- [x] Restored graph query step in mmxentry skill
- [x] Add DB size monitoring: `report_db_size()` runs after every sync, warns at 500MB, critical at 1GB
- [x] Add INFERRED edge export/import (`mmx_graph_write.py --export / --import`) so rebuilds are lossless
- [x] Guard full sync against running on existing DB (would silently duplicate all edges)
- [ ] Move wikitext out of Kuzu into a SQLite sidecar (`mmx_wikitext.db`) — SQLite does in-place row updates with no copy-on-write dead space; Kuzu then holds only graph structure (nodes + edges), staying small indefinitely. Update `mmx_graph_sync.py` (write/read wikitext via SQLite), `mmx_graph_query.py` (excerpt from SQLite), and `mmx_graph_init.py` (create SQLite schema). Drop `wikitext` field from Kuzu `Page` node.

## Compositional interface for external consumers

Context: a textbook-index DB project and a categorical sheaf project (zoom across type, composition, and complexification axes) need graph data from this project as scaffolding and seeding. High-effort sheaf tasks include curating complexification relations (e.g. organ systems complexify into a unit organism — emergent whole from composed parts). This project can surface candidates and expose its graph to those consumers.

- [x] Design export schema v1.0: nodes with title, url, categories, subtypes, supertypes, parts, wholes, other SMW props, wikilinks; optional inferred_edges
- [x] Implement `mmx_graph_export.py`: `--seed` (BFS from concept), `--category` (all pages in wiki category), `--complexification` (multi-hop Consists-of chains); importable API
- [x] Graph query already importable as module (`mmx_graph_query.py` exposes `query()`, `search_by_title()`, `get_page_properties()`, etc.)
- [x] Complexification candidates: 5,632 chains found (max depth 4); accessible via `mmx_graph_export.py --complexification`
- [x] Interface contract documented in `mmx_graph_export.py` module docstring (schema v1.0, CLI flags, importable functions)

## Inference write-back to wiki (==Inferred connections== section)

Goal: instead of storing INFERRED edges locally in Kuzu, push them to the wiki as an `==Inferred connections==` section on each page — sentences containing SMW semantic links. The graph DB then picks them up on normal sync, making inferences first-class wiki content that survives rebuilds.

Push (create new page) is already working via `mmxpush`. What is missing is the ability to **edit existing pages**.

- [ ] Explore MediaWiki API edit endpoint: `action=edit` with `appendtext` or full `text` replacement — determine which is safer for appending a section without overwriting existing content
- [ ] Check if bot account has edit permissions (may need different token type: `action=query&meta=tokens&type=csrf`)
- [ ] Implement `mmx_wiki_edit.py`: fetch current wikitext, append or update `==Inferred connections==` section, POST edit back — idempotent (re-running replaces the section, does not duplicate it)
- [ ] Define wikitext format for inferred connection sentences (e.g. `'''[[SourcePage]]''' [[has subject::TargetPage]] — ''claim text''.`)
- [ ] Integrate with Claude Code skill: after reasoning session, offer to push inferred connections to wiki pages rather than writing local INFERRED edges

## Integration and documentation

- [ ] Test end-to-end: query → reasoning → citation → write-back
- [x] README with setup, usage, rebuild, and migration instructions
