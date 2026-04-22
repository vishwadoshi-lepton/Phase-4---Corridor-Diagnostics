"""Parse the profile-query result text (list of {road_id, profile: 'bkt:tt,...'}) and
save as {road_id: {minute_of_day: tt}} dict."""
import json, sys, os

def parse_result(text_json):
    rows = json.loads(text_json)
    out = {}
    for r in rows:
        prof = {}
        for tok in r['profile'].split(','):
            b, tt = tok.split(':')
            prof[int(b) * 2] = int(tt)  # minute of day
        out[r['road_id']] = prof
    return out

if __name__ == '__main__':
    in_file, out_file = sys.argv[1], sys.argv[2]
    raw = json.loads(open(in_file).read())
    # Format: [{"type":"text","text":"<json>"}]
    if isinstance(raw, list) and raw and 'text' in raw[0]:
        data = parse_result(raw[0]['text'])
    else:
        data = parse_result(json.dumps(raw))
    # merge with existing if present
    if os.path.exists(out_file):
        existing = json.load(open(out_file))
        existing.update(data)
        data = existing
    json.dump(data, open(out_file, 'w'))
    print(f'Saved {len(data)} profiles to {out_file}')
