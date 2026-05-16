"""
Initialize the Kuzu graph database schema.
Run once (or to reset the schema) before syncing.
"""

import os
import kuzu
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("MEMEX_DB_PATH")
if not DB_PATH:
    raise RuntimeError("MEMEX_DB_PATH is not set. Copy config.example.env to .env and fill in values.")

db = kuzu.Database(DB_PATH)
conn = kuzu.Connection(db)

# Node tables
conn.execute("""
    CREATE NODE TABLE IF NOT EXISTS Page (
        title STRING,
        url STRING,
        wikitext STRING,
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

print(f"Schema initialized at: {DB_PATH}")
