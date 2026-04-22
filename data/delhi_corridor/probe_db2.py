"""Dig deeper: rejected_event, route_monitoring, and try postgres DB."""
import os, psycopg2
from psycopg2.extras import RealDictCursor

SEED_IDS = [
    "6f5ffb4b-d62c-4559-9519-7fd29b1549e7",
    "f31cc188-93ca-4bee-b057-3437c21d34f8",
    "22a8101c-1ee9-4d03-959d-3ff1f8c46b4a",
    "5c5b5237-ccd0-4660-81b5-e7398d8aa1ae",
]

def run(dbname):
    print(f"\n########## DB = {dbname} ##########")
    try:
        conn = psycopg2.connect(host=os.environ["POSTGRES_HOST"], port=os.environ["POSTGRES_PORT"],
                                dbname=dbname, user=os.environ["POSTGRES_USER"],
                                password=os.environ["POSTGRES_PASSWORD"])
    except Exception as e:
        print(" connect failed:", e); return
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # rejected_event structure and content for the seed
    try:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='rejected_event'
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        if cols:
            print("rejected_event columns:", [c["column_name"] for c in cols])
            cur.execute("""SELECT * FROM public.rejected_event
                            WHERE road_id = ANY(%s) LIMIT 3""", (SEED_IDS,))
            for r in cur.fetchall(): print(" sample rejected row:", dict(r))
    except Exception as e:
        conn.rollback(); print(" rejected_event check failed:", e)

    # route_monitoring table
    try:
        cur.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema='route_monitoring' AND table_name='monitored_route_segment'
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        if cols:
            print("route_monitoring.monitored_route_segment columns:", [c["column_name"] for c in cols])
            cur.execute("SELECT COUNT(*) AS c FROM route_monitoring.monitored_route_segment")
            print(" total rows:", cur.fetchone()["c"])
            cur.execute("SELECT segment_id FROM route_monitoring.monitored_route_segment WHERE segment_id = ANY(%s)", (SEED_IDS,))
            hits = [r["segment_id"] for r in cur.fetchall()]
            print(" seed hits:", hits)
    except Exception as e:
        conn.rollback(); print(" route_monitoring check failed:", e)

    # All schemas with geometry columns and a segment-like column -- search for seed
    try:
        cur.execute("""
            SELECT f_table_schema, f_table_name, f_geometry_column
            FROM geometry_columns
            ORDER BY f_table_schema, f_table_name
        """)
        print("\n geometry_columns:")
        geom_tables = cur.fetchall()
        for g in geom_tables:
            print(f"   {g['f_table_schema']}.{g['f_table_name']} (geom col: {g['f_geometry_column']})")
    except Exception as e:
        conn.rollback(); print(" geometry_columns failed:", e)

    # Look for any uuid column in any table that contains a seed
    try:
        cur.execute("""
            SELECT table_schema, table_name, column_name
            FROM information_schema.columns
            WHERE data_type IN ('uuid','character varying','text','varchar')
              AND (column_name ILIKE '%id%' OR column_name ILIKE '%uuid%')
              AND table_schema NOT IN ('information_schema','pg_catalog')
            ORDER BY table_schema, table_name
        """)
        cand = cur.fetchall()
        print(f"\n Scanning {len(cand)} id-like columns for seed presence...")
        for r in cand:
            full = f'"{r["table_schema"]}"."{r["table_name"]}"'
            col = r["column_name"]
            try:
                cur.execute(f'SELECT 1 FROM {full} WHERE {col}::text = ANY(%s) LIMIT 1', (SEED_IDS,))
                if cur.fetchone():
                    print(f"   HIT {full}.{col}")
            except Exception:
                conn.rollback()
    except Exception as e:
        conn.rollback(); print(" scan failed:", e)

    cur.close(); conn.close()

run("traffic")
run("postgres")
