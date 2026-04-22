"""
Find Delhi road_segments that underlie a given encoded polyline, in direction.

Approach:
  1. Decode Google-style polyline -> list[(lat,lng)].
  2. Build a PostGIS LineString (SRID 4326) from those points (lng,lat order).
  3. Spatial filter: pick candidate segments in Delhi whose geometry lies within
     a small buffer of the polyline. Use geography buffer (meters).
  4. Direction filter: for each candidate, require that the segment is
     "co-directional" with the polyline. We test this by projecting the
     segment's start and end onto the polyline (ST_LineLocatePoint) and
     requiring end_fraction > start_fraction by a meaningful margin.
  5. Coverage filter: require the segment to overlap the buffer for most of
     its length (>= 70%) -- keeps out perpendicular crossings that happen to
     poke into the buffer.
  6. Order by start_fraction ascending -> this is the physical upstream->
     downstream ordering along the polyline.

Validation: the user gave 4 seed road_ids that must be in the result.
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor


POLYLINE = "k{kmDq~fvMrCRnADz@AdBL|KvAbAR`DdA`AVzLpBfBNNAPGxG@f@DnBBjBF`F`@|Jr@bI|@bEf@zD`@RC\\GrB\\vGhCvB~@nCnAdEpAbBh@rBr@zFtAfC^jEfA|@R~BbAnB`A|FnCx@ZzDzAjPvG"

SEED_IDS = [
    "6f5ffb4b-d62c-4559-9519-7fd29b1549e7",
    "f31cc188-93ca-4bee-b057-3437c21d34f8",
    "22a8101c-1ee9-4d03-959d-3ff1f8c46b4a",
    "5c5b5237-ccd0-4660-81b5-e7398d8aa1ae",
]

BUFFER_METERS = 8           # small buffer thickness
MIN_OVERLAP_FRACTION = 0.80 # segment must lie mostly inside buffer
MIN_FRACTION_DELTA = 0.0002 # start->end forward progress along polyline (direction filter)
TAG_FALLBACK = ["Delhi"]    # used if seeds aren't in road_segment on this host


def decode_polyline(encoded: str):
    """Google polyline decoder -> list[(lat, lng)]."""
    coords, idx, lat, lng = [], 0, 0, 0
    while idx < len(encoded):
        for key in ("lat", "lng"):
            result, shift = 0, 0
            while True:
                b = ord(encoded[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if key == "lat":
                lat += delta
            else:
                lng += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def polyline_to_wkt(points):
    # WKT wants "lng lat"
    return "LINESTRING(" + ",".join(f"{lng} {lat}" for lat, lng in points) + ")"


def main():
    points = decode_polyline(POLYLINE)
    print(f"Decoded polyline: {len(points)} vertices")
    print(f"  First: {points[0]}")
    print(f"  Last:  {points[-1]}")
    wkt = polyline_to_wkt(points)

    conn = psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Sanity-check the 4 seed IDs: do they exist? What tag(s) do they have?
    cur.execute("""
        SELECT road_id, road_name, tag, organization_id, road_length_meters
        FROM public.road_segment
        WHERE road_id = ANY(%s)
    """, (SEED_IDS,))
    seeds = cur.fetchall()
    print("\nSeed segments found:")
    for s in seeds:
        print(f"  {s['road_id']}  tag={s['tag']}  org={s['organization_id']}  "
              f"len={s['road_length_meters']}m  name={s['road_name']}")

    # What tag should we filter on? Use the tag(s) observed on the seeds.
    delhi_tags = sorted({s["tag"] for s in seeds if s["tag"]})
    print(f"Delhi-indicating tags (from seeds): {delhi_tags}")
    if not delhi_tags:
        # Fallback: show distinct tags so we know what's there.
        cur.execute("SELECT DISTINCT tag FROM public.road_segment ORDER BY tag")
        all_tags = [r["tag"] for r in cur.fetchall()]
        print(f"All tags in road_segment: {all_tags}")
        raise SystemExit("Could not infer Delhi tag from seeds")

    # Main corridor-extraction query.
    sql = """
        WITH pl AS (
            SELECT ST_SetSRID(ST_GeomFromText(%(wkt)s), 4326) AS geom
        ),
        pl_buf AS (
            SELECT ST_Buffer(geom::geography, %(buf)s)::geometry AS buf,
                   geom
            FROM pl
        ),
        candidates AS (
            SELECT rs.road_id,
                   rs.road_name,
                   rs.tag,
                   rs.road_length_meters,
                   rs.geometry AS seg_geom
            FROM public.road_segment rs, pl_buf
            WHERE rs.tag = ANY(%(tags)s)
              AND rs.geometry IS NOT NULL
              AND rs.geometry && pl_buf.buf
              AND ST_Intersects(rs.geometry, pl_buf.buf)
        ),
        scored AS (
            SELECT c.road_id,
                   c.road_name,
                   c.tag,
                   c.road_length_meters,
                   -- how much of the segment lies inside the buffer (0..1)
                   ST_Length(ST_Intersection(c.seg_geom, pb.buf)::geography)
                     / NULLIF(ST_Length(c.seg_geom::geography), 0) AS overlap_frac,
                   -- where along the polyline the segment's start and end project to
                   ST_LineLocatePoint(pb.geom, ST_StartPoint(c.seg_geom)) AS start_frac,
                   ST_LineLocatePoint(pb.geom, ST_EndPoint(c.seg_geom))   AS end_frac
            FROM candidates c, pl_buf pb
        )
        SELECT road_id, road_name, tag, road_length_meters,
               overlap_frac, start_frac, end_frac,
               (end_frac - start_frac) AS frac_delta
        FROM scored
        WHERE overlap_frac >= %(min_overlap)s
          AND (end_frac - start_frac) >= %(min_delta)s
        ORDER BY start_frac ASC
    """

    cur.execute(sql, {
        "wkt": wkt,
        "buf": BUFFER_METERS,
        "tags": delhi_tags,
        "min_overlap": MIN_OVERLAP_FRACTION,
        "min_delta": MIN_FRACTION_DELTA,
    })
    rows = cur.fetchall()

    print(f"\nMatched {len(rows)} Delhi segments in direction of polyline "
          f"(buffer={BUFFER_METERS}m, min_overlap={MIN_OVERLAP_FRACTION}, "
          f"min_frac_delta={MIN_FRACTION_DELTA}):\n")
    print(f"{'#':>3}  {'road_id':36}  {'ovl':>5}  {'sfrac':>6}  {'efrac':>6}  {'len_m':>6}  name")
    for i, r in enumerate(rows, 1):
        print(f"{i:>3}  {r['road_id']}  "
              f"{r['overlap_frac']:.2f}  "
              f"{r['start_frac']:.4f}  {r['end_frac']:.4f}  "
              f"{r['road_length_meters']:>6}  {r['road_name']}")

    # ---- Build a clean non-overlapping chain ----
    # Drop any segment whose [start_frac, end_frac] interval is fully
    # subsumed by another matched segment's interval. That removes the
    # "roads/ChIJ..." duplicate IDs and any side-street segments that
    # happen to co-align for a short stretch. Ties broken by larger
    # frac_delta (longer coverage) first.
    intervals = sorted(
        rows,
        key=lambda r: (r["start_frac"], -(r["end_frac"] - r["start_frac"]))
    )
    clean = []
    for r in intervals:
        s, e = r["start_frac"], r["end_frac"]
        subsumed = False
        for k in clean:
            if k["start_frac"] <= s and k["end_frac"] >= e and not (
                k["start_frac"] == s and k["end_frac"] == e
            ):
                subsumed = True
                break
        if subsumed:
            continue
        # also drop later duplicates with identical interval
        if any(k["start_frac"] == s and k["end_frac"] == e for k in clean):
            continue
        clean.append(r)
    clean.sort(key=lambda r: r["start_frac"])

    # Per user: skip everything up to and including the #22 `roads/ChIJ...`
    # reverse-overlap segment -- corridor starts fresh from #23 (20914a08...).
    TRIM_START_ROAD_ID = "20914a08-a262-4e79-9196-7954e451ddeb"
    trim_idx = next(
        (i for i, r in enumerate(clean) if r["road_id"] == TRIM_START_ROAD_ID),
        None,
    )
    if trim_idx is not None:
        dropped = len(clean) - (len(clean) - trim_idx)
        clean = clean[trim_idx:]
        print(f"\nTrimmed corridor to start at {TRIM_START_ROAD_ID} "
              f"(dropped {trim_idx} preceding segments). "
              f"New chain length: {len(clean)}")

    print(f"\nClean chain (subsumed-interval dedup): {len(clean)} segments")
    print(f"{'#':>3}  {'road_id':36}  {'sfrac':>6}  {'efrac':>6}  {'gap':>6}  {'len_m':>6}  name")
    prev_e = None
    for i, r in enumerate(clean, 1):
        gap = "" if prev_e is None else f"{(r['start_frac'] - prev_e):+.4f}"
        print(f"{i:>3}  {r['road_id']}  "
              f"{r['start_frac']:.4f}  {r['end_frac']:.4f}  {gap:>6}  "
              f"{r['road_length_meters']:>6}  {r['road_name']}")
        prev_e = r["end_frac"]

    result_ids = [r["road_id"] for r in rows]
    missing = [s for s in SEED_IDS if s not in result_ids]
    extra_present = [s for s in SEED_IDS if s in result_ids]
    print(f"\nSeed check:")
    print(f"  seeds present in result : {len(extra_present)}/{len(SEED_IDS)}")
    for s in extra_present:
        print(f"    ✓ {s}")
    for s in missing:
        print(f"    ✗ MISSING {s}")

    # Write both lists out.
    out_all = os.path.join(os.path.dirname(__file__), "delhi_corridor_all_matches.txt")
    with open(out_all, "w") as f:
        f.write("# Delhi corridor - all matches (ordered upstream -> downstream)\n")
        f.write(f"# buffer={BUFFER_METERS}m  min_overlap={MIN_OVERLAP_FRACTION}  min_frac_delta={MIN_FRACTION_DELTA}\n")
        f.write(f"# total: {len(rows)} segments\n")
        for i, r in enumerate(rows, 1):
            f.write(f'("{r["road_id"]}", "{r["road_name"]}"),  # #{i} sfrac={r["start_frac"]:.4f}\n')

    out_chain = os.path.join(os.path.dirname(__file__), "delhi_corridor_chain.py")
    with open(out_chain, "w") as f:
        f.write('"""Delhi corridor (Sri Aurobindo Marg) — auto-generated.\n')
        f.write(f'Polyline buffer={BUFFER_METERS}m, direction-filtered, dedup non-subsumed.\n')
        f.write(f'{len(clean)} segments, ordered upstream -> downstream.\n"""\n\n')
        f.write('DELHI_AUROBINDO = {\n')
        f.write('    "id": "DEL_AUROBINDO",\n')
        f.write('    "name": "Sri Aurobindo Marg (Delhi) — polyline-derived",\n')
        f.write('    "chain": [\n')
        for r in clean:
            f.write(f'        ("{r["road_id"]}", "{r["road_name"]}"),\n')
        f.write('    ],\n}\n')

    print(f"\nWrote all 70 matches to:  {out_all}")
    print(f"Wrote clean chain (.py) to: {out_chain}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
