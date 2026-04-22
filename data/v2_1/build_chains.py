"""
Build joint segment chains from PostGIS adjacency data.
Usage: python3 build_chains.py <segs.json> <adj.json> <validated.txt> <n_corridors> <min_len> <max_len> <seed> <output.json>
"""
import json, random, sys
from collections import defaultdict

segs_file, adj_file, validated_file, n_cor, min_len, max_len, seed, out_file = sys.argv[1:]
n_cor = int(n_cor); min_len = int(min_len); max_len = int(max_len); seed = int(seed)
random.seed(seed)

segs_raw = json.loads(json.load(open(segs_file))[0]['text'])
adj_raw = json.loads(json.load(open(adj_file))[0]['text'])
validated = set()
if validated_file != "NONE":
    validated = set(open(validated_file).read().split())

seg_by_id = {s['road_id']: s for s in segs_raw}
downstream = defaultdict(set)
upstream = defaultdict(set)
for r in adj_raw:
    downstream[r['from_id']].add(r['to_id'])
    upstream[r['to_id']].add(r['from_id'])

def name_core(n):
    # strip common prefix/suffix, lowercase, strip
    n = n.lower().replace('pune/','').strip()
    return n

def walk_downstream(start, visited):
    """Greedily walk downstream, preserving straight-line direction."""
    path = [start]
    visited = set(visited) | {start}
    names_used = {name_core(seg_by_id[start]['road_name'])}
    # also reject if name reversed (A to B vs B to A)
    def reversed_name(n):
        # "X To Y" -> "Y To X"
        nc = name_core(n)
        if ' to ' in nc:
            p = nc.split(' to ',1)
            return p[1].strip() + ' to ' + p[0].strip()
        return None
    names_reversed = {reversed_name(seg_by_id[start]['road_name'])}
    cur = start
    while True:
        candidates = []
        cur_seg = seg_by_id[cur]
        # direction vector of current segment (end - start)
        cvx = cur_seg['ex'] - cur_seg['sx']
        cvy = cur_seg['ey'] - cur_seg['sy']
        for n in downstream[cur]:
            if n in visited or n not in seg_by_id:
                continue
            nseg = seg_by_id[n]
            nc = name_core(nseg['road_name'])
            if nc in names_used:
                continue
            if nc in names_reversed:
                continue
            # direction vector of candidate
            nvx = nseg['ex'] - nseg['sx']
            nvy = nseg['ey'] - nseg['sy']
            # dot product — positive means same general direction
            dot = cvx*nvx + cvy*nvy
            if dot <= 0:
                continue  # reject U-turn / opposing direction
            candidates.append((dot, n))
        if not candidates:
            break
        # prefer strongest direction continuation
        candidates.sort(reverse=True)
        nxt = candidates[0][1]
        path.append(nxt)
        visited.add(nxt)
        names_used.add(name_core(seg_by_id[nxt]['road_name']))
        rn = reversed_name(seg_by_id[nxt]['road_name'])
        if rn: names_reversed.add(rn)
        cur = nxt
    return path

def walk_upstream(start, visited):
    path = [start]
    visited = set(visited) | {start}
    cur = start
    while True:
        prevs = [p for p in upstream[cur] if p not in visited and p in seg_by_id]
        if not prevs:
            break
        prevs.sort(key=lambda x: (len(upstream[x]), seg_by_id[x]['road_length_meters']))
        prev = prevs[0]
        path.insert(0, prev)
        visited.add(prev)
        cur = prev
    return path

import math
def hav_m(a, b):
    # haversine in meters
    R = 6371000.0
    lon1, lat1 = math.radians(a[0]), math.radians(a[1])
    lon2, lat2 = math.radians(b[0]), math.radians(b[1])
    dlon = lon2 - lon1; dlat = lat2 - lat1
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(h))

def chain_is_straight(chain):
    # straightness = direct distance between chain start and chain end
    # divided by sum of segment lengths. If < 0.5, it's loopy.
    first = seg_by_id[chain[0]]
    last = seg_by_id[chain[-1]]
    direct = hav_m((first['sx'], first['sy']), (last['ex'], last['ey']))
    total = sum(seg_by_id[r]['road_length_meters'] for r in chain)
    return (direct / total) if total > 0 else 0

def build_chain_from_seed(seed_id):
    # downstream only — more predictable
    down = walk_downstream(seed_id, set())
    return down

# try many seeds, pick the best diverse set
candidates = [s for s in seg_by_id if s not in validated and len(downstream[s]) >= 1 and len(upstream[s]) >= 1]
random.shuffle(candidates)

built = []
used = set()
tries = 0
for seed_id in candidates:
    if seed_id in used:
        continue
    chain = build_chain_from_seed(seed_id)
    if not (min_len <= len(chain) <= max_len):
        continue
    if any(rid in used for rid in chain):
        continue
    # ensure enough total length
    total_m = sum(seg_by_id[r]['road_length_meters'] for r in chain)
    if total_m < 2500:
        continue
    # reject loops
    straight = chain_is_straight(chain)
    if straight < 0.55:
        continue
    built.append({
        'seed': seed_id,
        'chain': [{
            'road_id': r,
            'road_name': seg_by_id[r]['road_name'],
            'length_m': seg_by_id[r]['road_length_meters'],
            'road_class': seg_by_id[r]['road_class'],
        } for r in chain],
        'total_length_m': total_m,
    })
    for r in chain: used.add(r)
    tries += 1
    if len(built) >= n_cor:
        break

json.dump(built, open(out_file, 'w'), indent=2)
print(f'Built {len(built)} corridors')
for c in built:
    print(f'  {len(c["chain"])} segs, {c["total_length_m"]}m  starting "{c["chain"][0]["road_name"][:60]}"  ending "{c["chain"][-1]["road_name"][:60]}"')
