import kuzu
import sys

BUFFER_GB = int(sys.argv[1]) if len(sys.argv) > 1 else 4
DB_PATH = "/Users/trond/code/mediawiki-graph-reasoning/kuzu_db"

print(f"Opening DB with buffer_pool_size={BUFFER_GB}GB ...")
db = kuzu.Database(DB_PATH, buffer_pool_size=BUFFER_GB * 1024 * 1024 * 1024, read_only=True)
conn = kuzu.Connection(db)

print("DB opened. Querying node count ...")
result = conn.execute("MATCH (p:Page) RETURN count(p) AS n")
print("Page count:", result.get_next())

result2 = conn.execute("MATCH ()-[e:INFERRED]->() RETURN count(e) AS n")
print("INFERRED edges:", result2.get_next())

print("Done.")
