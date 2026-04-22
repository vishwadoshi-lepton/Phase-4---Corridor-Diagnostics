"""Probe where the Delhi seed road_ids actually live."""
import os, psycopg2
from psycopg2.extras import RealDictCursor

SEED_IDS = [
    "6f5ffb4b-d62c-4559-9519-7fd29b1549e7",
    "f31cc188-93ca-4bee-b057-3437c21d34f8",
    "22a8101c-1ee9-4d03-959d-3ff1f8c46b4a",
    "5c5b5237-ccd0-4660-81b5-e7398d8aa1ae",
]

conn = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
                        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
                        password=os.environ["POSTGRES_PASSWORD"])
cur = conn.cursor(cursor_factory=RealDictCursor)

print("=== databases ===")
cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname")
for r in cur.fetchall(): print(" ", r["datname"])

print("\n=== tables with a 'road_id' or 'segment_id' column ===")
cur.execute("""
    SELECT table_schema, table_name, column_name
    FROM information_schema.columns
    WHERE column_name IN ('road_id', 'segment_id')
    ORDER BY table_schema, table_name
""")
tables = cur.fetchall()
for r in tables: print(f"  {r['table_schema']}.{r['table_name']}.{r['column_name']}")

print("\n=== search each for the seeds ===")
seen = set()
for r in tables:
    key = (r["table_schema"], r["table_name"], r["column_name"])
    if key in seen: continue
    seen.add(key)
    full = f'"{r["table_schema"]}"."{r["table_name"]}"'
    col = r["column_name"]
    try:
        cur.execute(f'SELECT {col} FROM {full} WHERE {col} = ANY(%s) LIMIT 10', (SEED_IDS,))
        hits = cur.fetchall()
        if hits:
            print(f"  HIT {full}.{col}: {len(hits)} / {len(SEED_IDS)} -> {[h[col] for h in hits]}")
    except Exception as e:
        conn.rollback()
        # print(f"  skipped {full}.{col}: {e}")

print("\n=== distinct tag values in backup / other road tables ===")
cur.execute("""
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_name ILIKE '%road_segment%' OR table_name ILIKE '%road%segment%'
    ORDER BY table_schema, table_name
""")
for r in cur.fetchall():
    full = f'"{r["table_schema"]}"."{r["table_name"]}"'
    try:
        cur.execute(f'SELECT DISTINCT tag FROM {full} WHERE tag ILIKE %s', ('%delhi%',))
        delhi = [x["tag"] for x in cur.fetchall()]
        cur.execute(f'SELECT count(*) AS c FROM {full}')
        c = cur.fetchone()["c"]
        print(f"  {full}: rows={c}, delhi-like tags: {delhi}")
    except Exception as e:
        conn.rollback()

cur.close(); conn.close()
