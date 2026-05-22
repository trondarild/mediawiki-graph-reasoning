"""
Initialize the Kuzu graph database schema and the SQLite wikitext sidecar.
Run once (or to reset the schema) before syncing.
"""

import os
import sqlite3
import kuzu
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("MEMEX_DB_PATH")
if not DB_PATH:
    raise RuntimeError("MEMEX_DB_PATH is not set. Copy config.example.env to .env and fill in values.")

_db_dir = os.path.dirname(os.path.abspath(DB_PATH))
WIKITEXT_DB_PATH = os.path.join(_db_dir, "mmx_wikitext.db")

db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

# Node tables — wikitext is stored in the SQLite sidecar (mmx_wikitext.db), not here
conn.execute("""
    CREATE NODE TABLE IF NOT EXISTS Page (
        title STRING,
        url STRING,
        categories STRING,
        last_synced STRING,
        PRIMARY KEY (title)
    )
""")

conn.execute("""
    CREATE NODE TABLE IF NOT EXISTS Concept (
        name STRING,
        PRIMARY KEY (name)
    )
""")

# Edge tables
conn.execute("""
    CREATE REL TABLE IF NOT EXISTS HAS_PROP (
        FROM Page TO Concept,
        property STRING,
        value STRING
    )
""")

conn.execute("""
    CREATE REL TABLE IF NOT EXISTS LINKS_TO (
        FROM Page TO Page
    )
""")

conn.execute("""
    CREATE REL TABLE IF NOT EXISTS INFERRED (
        FROM Page TO Page,
        claim STRING,
        confidence FLOAT,
        session STRING,
        timestamp STRING
    )
""")

# SQLite sidecar: stores wikitext with proper in-place UPDATE semantics
sql = sqlite3.connect(WIKITEXT_DB_PATH)
sql.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        title TEXT PRIMARY KEY,
        wikitext TEXT,
        last_updated TEXT
    )
""")
sql.commit()
sql.close()

print(f"Schema initialized at: {DB_PATH}")
print(f"Wikitext sidecar: {WIKITEXT_DB_PATH}")
