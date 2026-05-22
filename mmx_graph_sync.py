"""
Sync SemanticMediaWiki pages into the local Kuzu graph database.

Usage:
    python mmx_graph_sync.py              # full sync (re-fetches everything)
    python mmx_graph_sync.py --incremental  # only sync pages changed since last sync

Reads config from .env (copy config.example.env and fill in values).
"""

import os
import re
import sqlite3
import time
import kuzu
import requests
from requests.exceptions import ReadTimeout, ConnectionError as RequestsConnectionError
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

def _require(key):
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"{key} is not set. Copy config.example.env to .env and fill in values.")
    return val

API_URL   = _require("MEMEX_API_URL")
DB_PATH   = _require("MEMEX_DB_PATH")
BOT_NAME  = _require("MEMEX_BOT_NAME")
BOT_PASS  = _require("MEMEX_BOT_PASS")
HTTP_USER = os.environ.get("MEMEX_HTTP_USER")
HTTP_PASS = os.environ.get("MEMEX_HTTP_PASS")

_db_dir = os.path.dirname(os.path.abspath(DB_PATH))
WIKITEXT_DB_PATH = os.path.join(_db_dir, "mmx_wikitext.db")

RATE_LIMIT = 1.0  # seconds between requests

session = requests.Session()
if HTTP_USER and HTTP_PASS:
    session.auth = (HTTP_USER, HTTP_PASS)

_last_request = 0.0


def api_get(params, retries=4):
    """Rate-limited GET to the MediaWiki API, with exponential backoff on 5xx errors."""
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed)
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")

    for attempt in range(retries):
        response = session.get(API_URL, params=params, timeout=30)
        _last_request = time.time()
        if response.status_code < 500:
            break
        wait = 10 * (2 ** attempt)
        print(f"  {response.status_code} error, retrying in {wait}s (attempt {attempt+1}/{retries})")
        time.sleep(wait)
    else:
        response.raise_for_status()

    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise RuntimeError(f"API error: {data['error']}")
    return data


def api_post(params, retries=4):
    """Rate-limited POST to the MediaWiki API, with exponential backoff on 5xx and timeout errors."""
    global _last_request
    elapsed = time.time() - _last_request
    if elapsed < RATE_LIMIT:
        time.sleep(RATE_LIMIT - elapsed)
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")

    response = None
    for attempt in range(retries):
        try:
            response = session.post(API_URL, data=params, timeout=60)
            _last_request = time.time()
            if response.status_code < 500:
                break
            wait = 10 * (2 ** attempt)
            print(f"  {response.status_code} error, retrying in {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
        except (ReadTimeout, RequestsConnectionError) as e:
            wait = 10 * (2 ** attempt)
            print(f"  Connection error ({e.__class__.__name__}), retrying in {wait}s (attempt {attempt+1}/{retries})")
            time.sleep(wait)
    else:
        if response is not None:
            response.raise_for_status()
        raise RuntimeError("Max retries exceeded with no response")

    response.raise_for_status()
    return response.json()


def login():
    """Log in as the bot account to obtain read/write access."""
    # Step 1: fetch login token
    data = api_get({"action": "query", "meta": "tokens", "type": "login"})
    token = data["query"]["tokens"]["logintoken"]

    # Step 2: log in
    result = api_post({
        "action": "login",
        "lgname": BOT_NAME,
        "lgpassword": BOT_PASS,
        "lgtoken": token,
    })
    if result.get("login", {}).get("result") != "Success":
        raise RuntimeError(f"Login failed: {result}")
    print(f"Logged in as {result['login']['lgusername']}")


def fetch_excluded_titles(root_category="Personal info"):
    """
    Recursively walk root_category and all subcategories.
    Returns a set of page titles that must be excluded from sync.
    """
    excluded = set()
    cats_to_visit = [root_category]
    visited_cats = set()

    while cats_to_visit:
        cat = cats_to_visit.pop()
        if cat in visited_cats:
            continue
        visited_cats.add(cat)

        cmcontinue = None
        while True:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": f"Category:{cat}",
                "cmtype": "page|subcat",
                "cmlimit": "500",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue

            data = api_get(params)
            members = data.get("query", {}).get("categorymembers", [])

            for member in members:
                if member["ns"] == 14:  # NS 14 = Category
                    subcat_name = member["title"].removeprefix("Category:")
                    cats_to_visit.append(subcat_name)
                else:
                    excluded.add(member["title"])

            cmcontinue = data.get("continue", {}).get("cmcontinue")
            if not cmcontinue:
                break

    print(f"Exclusion list: {len(excluded)} pages in '{root_category}' and subcategories")
    return excluded


def fetch_all_titles(excluded):
    """
    Fetch all page titles in the main namespace, minus excluded titles.
    Returns a list of title strings.
    """
    titles = []
    apcontinue = None

    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": "0",
            "aplimit": "500",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue

        data = api_get(params)
        pages = data.get("query", {}).get("allpages", [])

        for page in pages:
            if page["title"] not in excluded:
                titles.append(page["title"])

        apcontinue = data.get("continue", {}).get("apcontinue")
        if not apcontinue:
            break

    print(f"Fetched {len(titles)} page titles (after exclusions)")
    return titles


def fetch_wikitext_batch(titles):
    """
    Fetch wikitext for up to 50 titles in a single API call.
    Uses POST to avoid URL length limits with long page titles.
    Returns a dict of {title: wikitext}.
    """
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": "|".join(titles),
    }
    data = api_post(params)
    pages = data.get("query", {}).get("pages", [])
    result = {}
    for page in pages:
        title = page["title"]
        slots = page.get("revisions", [{}])[0].get("slots", {})
        wikitext = slots.get("main", {}).get("content", "")
        result[title] = wikitext
    return result


def fetch_smw_properties(titles_set):
    """
    Fetch all SMW semantic properties for pages in titles_set.
    Strategy: enumerate all properties from namespace 102, then for each property
    paginate through all pages having it via action=ask with limit=500.
    Returns a dict of {page_title: [(property, value), ...]}.
    """
    # Step 1: enumerate all SMW property names
    properties = []
    apcontinue = None
    while True:
        params = {
            "action": "query",
            "list": "allpages",
            "apnamespace": "102",
            "aplimit": "500",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        data = api_get(params)
        for page in data.get("query", {}).get("allpages", []):
            properties.append(page["title"].removeprefix("Property:"))
        apcontinue = data.get("continue", {}).get("apcontinue")
        if not apcontinue:
            break
    print(f"Found {len(properties)} SMW properties")

    # Step 2: for each property, fetch all (page, value) pairs in batches of 500
    result = {}
    for prop in properties:
        offset = 0
        batch_count = 0
        while True:
            query = f"[[{prop}::+]]|?{prop}|limit=500|offset={offset}"
            data = api_get({"action": "ask", "query": query})
            results = data.get("query", {}).get("results", {})
            if not results:
                break
            for page_title, page_data in results.items():
                if page_title not in titles_set:
                    continue
                for val in page_data.get("printouts", {}).get(prop, []):
                    value_str = val.get("fulltext", str(val)) if isinstance(val, dict) else str(val)
                    result.setdefault(page_title, []).append((prop, value_str))
            batch_count += 1
            next_offset = data.get("query-continue-offset")
            if next_offset is None or len(results) < 500:
                break
            offset = next_offset
        print(f"  '{prop}': {batch_count} batch(es)")

    print(f"Fetched SMW properties for {len(result)} pages")
    return result


def fetch_categories_batch(titles):
    """
    Fetch wiki category membership for up to 50 titles in a single API call.
    Uses POST to avoid URL length limits.
    Returns a dict of {title: [category_name, ...]}.
    """
    params = {
        "action": "query",
        "prop": "categories",
        "cllimit": "500",
        "titles": "|".join(titles),
    }
    data = api_post(params)
    pages = data.get("query", {}).get("pages", [])
    result = {}
    for page in pages:
        title = page["title"]
        cats = [c["title"].removeprefix("Category:") for c in page.get("categories", [])]
        result[title] = cats
    return result


def fetch_all_categories(titles):
    """
    Fetch wiki category membership for all titles in batches of 50.
    Returns a dict of {title: [category_name, ...]}.
    """
    BATCH = 50
    result = {}
    total_batches = -(-len(titles) // BATCH)

    for i in range(0, len(titles), BATCH):
        batch = titles[i:i + BATCH]
        batch_num = i // BATCH + 1
        result.update(fetch_categories_batch(batch))
        print(f"  Categories batch {batch_num}/{total_batches} ({len(result)} pages so far)")

    print(f"Fetched categories for {len(result)} pages")
    return result


def fetch_all_wikitext(titles):
    """
    Fetch wikitext for all titles in batches of 50.
    Returns a dict of {title: wikitext}.
    """
    BATCH = 50
    result = {}
    total_batches = -(-len(titles) // BATCH)

    for i in range(0, len(titles), BATCH):
        batch = titles[i:i + BATCH]
        batch_num = i // BATCH + 1
        result.update(fetch_wikitext_batch(batch))
        print(f"  Wikitext batch {batch_num}/{total_batches} ({len(result)} pages so far)")

    print(f"Fetched wikitext for {len(result)} pages")
    return result


WIKILINK_RE = re.compile(r'\[\[([^|\]#]+)(?:\|[^\]]*)?\]\]')


def parse_wikilinks(wikitext, titles_set):
    """Extract internal page links from wikitext, returning only links to known pages."""
    links = set()
    for m in WIKILINK_RE.finditer(wikitext):
        target = m.group(1).strip().replace("_", " ")
        if ":" in target:
            continue  # skip File:, Category:, Template:, etc.
        if target and target[0].islower():
            target = target[0].upper() + target[1:]
        if target in titles_set:
            links.add(target)
    return links


CHECKPOINT_INTERVAL = 500


def populate_kuzu(titles, wikitext_map, smw_props, categories_map):
    """Write all fetched data into the Kuzu graph database and wikitext sidecar."""
    db = kuzu.Database(DB_PATH, buffer_pool_size=2 * 1024 * 1024 * 1024)
    conn = kuzu.Connection(db)
    titles_set = set(titles)
    now = datetime.now(timezone.utc).isoformat()

    # --- Page nodes (no wikitext in Kuzu — stored in SQLite sidecar) ---
    print("Inserting Page nodes...")
    for i, title in enumerate(titles):
        url = f"https://scribb.com/memex/index.php?title={title.replace(' ', '_')}"
        cats = "|".join(categories_map.get(title, []))
        conn.execute(
            "MERGE (p:Page {title: $title}) "
            "SET p.url = $url, p.categories = $cats, p.last_synced = $ts",
            {"title": title, "url": url, "cats": cats, "ts": now}
        )
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            conn.execute("CHECKPOINT")
            print(f"  {i + 1}/{len(titles)} pages (checkpoint)")
        elif (i + 1) % 1000 == 0:
            print(f"  {i + 1}/{len(titles)} pages")
    conn.execute("CHECKPOINT")
    print(f"Inserted {len(titles)} Page nodes")

    # --- Wikitext sidecar (SQLite) ---
    sql = sqlite3.connect(WIKITEXT_DB_PATH)
    sql.execute("CREATE TABLE IF NOT EXISTS pages (title TEXT PRIMARY KEY, wikitext TEXT, last_updated TEXT)")
    sql.executemany(
        "INSERT OR REPLACE INTO pages (title, wikitext, last_updated) VALUES (?, ?, ?)",
        [(t, wikitext_map.get(t, ""), now) for t in titles]
    )
    sql.commit()
    sql.close()

    # --- Concept nodes and HAS_PROP edges ---
    print("Inserting Concept nodes and HAS_PROP edges...")
    concepts_created = set()
    prop_edge_count = 0
    for page_title, props in smw_props.items():
        for prop, value in props:
            if value not in concepts_created:
                conn.execute("MERGE (c:Concept {name: $name})", {"name": value})
                concepts_created.add(value)
            conn.execute(
                "MATCH (p:Page {title: $page}), (c:Concept {name: $value}) "
                "CREATE (p)-[:HAS_PROP {property: $prop, value: $value}]->(c)",
                {"page": page_title, "value": value, "prop": prop}
            )
            prop_edge_count += 1
            if prop_edge_count % CHECKPOINT_INTERVAL == 0:
                conn.execute("CHECKPOINT")
    conn.execute("CHECKPOINT")
    print(f"Inserted {prop_edge_count} HAS_PROP edges ({len(concepts_created)} concepts)")

    # --- LINKS_TO edges ---
    print("Inserting LINKS_TO edges...")
    link_count = 0
    for i, (title, wikitext) in enumerate(wikitext_map.items()):
        for target in parse_wikilinks(wikitext, titles_set):
            if target != title:
                conn.execute(
                    "MATCH (a:Page {title: $src}), (b:Page {title: $dst}) "
                    "CREATE (a)-[:LINKS_TO]->(b)",
                    {"src": title, "dst": target}
                )
                link_count += 1
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            conn.execute("CHECKPOINT")
            print(f"  Wikilinks: {i + 1}/{len(wikitext_map)} pages processed ({link_count} edges so far)")
        elif (i + 1) % 1000 == 0:
            print(f"  Wikilinks: {i + 1}/{len(wikitext_map)} pages processed ({link_count} edges so far)")
    conn.execute("CHECKPOINT")
    print(f"Inserted {link_count} LINKS_TO edges")
    print("Kuzu population complete.")


def fetch_touched_timestamps(titles):
    """
    Fetch the `touched` timestamp for each title in batches of 50 via action=query&prop=info.
    Returns a dict of {title: touched_iso_string}.
    """
    BATCH = 50
    result = {}
    for i in range(0, len(titles), BATCH):
        batch = titles[i:i + BATCH]
        data = api_post({
            "action": "query",
            "prop": "info",
            "titles": "|".join(batch),
        })
        for page in data.get("query", {}).get("pages", []):
            if "touched" in page:
                result[page["title"]] = page["touched"]
    print(f"Fetched touched timestamps for {len(result)} pages")
    return result


def get_kuzu_last_synced():
    """
    Read last_synced timestamps for all Page nodes currently in Kuzu.
    Returns a dict of {title: last_synced_iso_string}.
    """
    db = kuzu.Database(DB_PATH, buffer_pool_size=2 * 1024 * 1024 * 1024)
    conn = kuzu.Connection(db)
    r = conn.execute("MATCH (p:Page) RETURN p.title, p.last_synced")
    result = {}
    while r.has_next():
        row = r.get_next()
        result[row[0]] = row[1]
    return result


def update_page_in_kuzu(conn, sql_conn, title, wikitext, cats, titles_set, now):
    """Update a single page node and rebuild its edges. Wikitext goes to SQLite sidecar."""
    url = f"https://scribb.com/memex/index.php?title={title.replace(' ', '_')}"

    # Update Kuzu node (no wikitext field)
    conn.execute(
        "MERGE (p:Page {title: $title}) "
        "SET p.url = $url, p.categories = $cats, p.last_synced = $ts",
        {"title": title, "url": url, "cats": cats, "ts": now}
    )

    # Update wikitext in SQLite sidecar
    sql_conn.execute(
        "INSERT OR REPLACE INTO pages (title, wikitext, last_updated) VALUES (?, ?, ?)",
        (title, wikitext, now)
    )

    # Rebuild LINKS_TO edges: delete existing, re-insert from new wikitext
    conn.execute(
        "MATCH (a:Page {title: $title})-[r:LINKS_TO]->() DELETE r",
        {"title": title}
    )
    for target in parse_wikilinks(wikitext, titles_set):
        if target != title:
            conn.execute(
                "MATCH (a:Page {title: $src}), (b:Page {title: $dst}) "
                "CREATE (a)-[:LINKS_TO]->(b)",
                {"src": title, "dst": target}
            )

    # Rebuild HAS_PROP edges: delete existing, re-insert
    conn.execute(
        "MATCH (a:Page {title: $title})-[r:HAS_PROP]->() DELETE r",
        {"title": title}
    )


def sync_incremental():
    """
    Incremental sync: fetch only pages changed on the wiki since their last_synced timestamp.
    New pages (not yet in Kuzu) are fetched and added. Deleted pages are left in place.
    """
    login()
    excluded = fetch_excluded_titles()
    titles = fetch_all_titles(excluded)
    titles_set = set(titles)

    # Determine which pages need updating
    touched = fetch_touched_timestamps(titles)
    last_synced = get_kuzu_last_synced()

    new_titles = [t for t in titles if t not in last_synced]
    changed_titles = [
        t for t in titles
        if t in last_synced and t in touched and touched[t] > last_synced[t]
    ]
    to_update = new_titles + changed_titles

    print(f"New pages: {len(new_titles)}, Changed pages: {len(changed_titles)}, Unchanged: {len(titles) - len(to_update)}")

    if not to_update:
        print("Graph is up to date.")
        return

    # Fetch data only for pages that need updating
    wikitext_map = fetch_all_wikitext(to_update)
    categories_map = fetch_all_categories(to_update)
    # SMW: re-fetch all properties but filter to changed pages
    smw_props_all = fetch_smw_properties(titles_set)
    smw_props = {t: v for t, v in smw_props_all.items() if t in set(to_update)}

    now = datetime.now(timezone.utc).isoformat()
    db = kuzu.Database(DB_PATH, buffer_pool_size=2 * 1024 * 1024 * 1024)
    conn = kuzu.Connection(db)
    sql_conn = sqlite3.connect(WIKITEXT_DB_PATH)
    sql_conn.execute("CREATE TABLE IF NOT EXISTS pages (title TEXT PRIMARY KEY, wikitext TEXT, last_updated TEXT)")

    print(f"Updating {len(to_update)} pages in Kuzu...")
    for i, title in enumerate(to_update):
        wikitext = wikitext_map.get(title, "")
        cats = "|".join(categories_map.get(title, []))
        update_page_in_kuzu(conn, sql_conn, title, wikitext, cats, titles_set, now)

        # Re-insert HAS_PROP edges for this page
        for prop, value in smw_props.get(title, []):
            conn.execute("MERGE (c:Concept {name: $name})", {"name": value})
            conn.execute(
                "MATCH (p:Page {title: $page}), (c:Concept {name: $value}) "
                "CREATE (p)-[:HAS_PROP {property: $prop, value: $value}]->(c)",
                {"page": title, "value": value, "prop": prop}
            )
        if (i + 1) % CHECKPOINT_INTERVAL == 0:
            conn.execute("CHECKPOINT")
            sql_conn.commit()
            print(f"  {i + 1}/{len(to_update)} pages updated (checkpoint)")
        elif (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(to_update)} pages updated")
    conn.execute("CHECKPOINT")
    sql_conn.commit()
    sql_conn.close()

    print(f"Incremental sync complete. Updated {len(to_update)} pages.")


def report_db_size():
    """Print Kuzu and SQLite sidecar sizes; warn if Kuzu looks bloated."""
    kuzu_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    sqlite_mb = os.path.getsize(WIKITEXT_DB_PATH) / (1024 * 1024) if os.path.exists(WIKITEXT_DB_PATH) else 0

    if kuzu_mb >= 1024:
        level = "CRITICAL"
    elif kuzu_mb >= 500:
        level = "WARNING"
    else:
        level = "OK"

    print(f"DB size: Kuzu {kuzu_mb:.1f} MB [{level}], SQLite wikitext {sqlite_mb:.1f} MB")
    if level == "WARNING":
        print("  Kuzu is growing large. Consider a full rebuild soon (drop kuzu_db, re-run without --incremental).")
    if level == "CRITICAL":
        print("  Kuzu is likely bloated. Rebuild required: delete kuzu_db, run mmx_graph_init.py, then full sync.")


if __name__ == "__main__":
    import sys
    if "--incremental" in sys.argv:
        sync_incremental()
    else:
        # Guard against running full sync on a populated DB — edges use CREATE, not MERGE,
        # so re-running on existing data silently multiplies edges and bloats the file.
        db = kuzu.Database(DB_PATH, buffer_pool_size=512 * 1024 * 1024)
        conn = kuzu.Connection(db)
        existing = conn.execute("MATCH (p:Page) RETURN count(p)").get_next()[0]
        del conn, db
        if existing > 0:
            print(f"ERROR: DB already contains {existing} pages.")
            print("Full sync uses CREATE (not MERGE) for edges and will duplicate data.")
            print("To rebuild: delete kuzu_db, run mmx_graph_init.py, then re-run this script.")
            sys.exit(1)
        login()
        excluded = fetch_excluded_titles()
        titles = fetch_all_titles(excluded)
        wikitext_map = fetch_all_wikitext(titles)
        smw_props = fetch_smw_properties(set(titles))
        categories_map = fetch_all_categories(titles)
        populate_kuzu(titles, wikitext_map, smw_props, categories_map)
    report_db_size()
