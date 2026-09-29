#!/usr/bin/env python3
"""Screen results -> exact-verification queue. A candidate goes to exact `lake env lean` verification
iff its REPL screen is 'pass' or the screen could not judge it (no_chunk, chunk_baseline_fail,
file_boot_fail, error*). Screen fail / fail_goals_differ / fail_delete_closing / timeout = rejected.
Rows already verified in --done files (same site_id+replacement) are skipped.
Usage: prep_verify.py --sites S.jsonl [..] --screen X.jsonl [..] --out Q.jsonl [--done V.jsonl ..]"""
import argparse, json, hashlib, os
ap = argparse.ArgumentParser()
ap.add_argument('--sites', nargs='+', required=True); ap.add_argument('--screen', nargs='+', required=True)
ap.add_argument('--out', required=True); ap.add_argument('--done', nargs='*', default=[])
a = ap.parse_args()
sites = {}
for p in a.sites:
    for l in open(p):
        s = json.loads(l); sites[s['site_id']] = s
done = set()
for p in a.done:
    if os.path.exists(p):
        for l in open(p):
            v = json.loads(l); done.add((v['site_id'], v['replacement']))
UNJUDGED = ('no_chunk', 'chunk_baseline_fail', 'file_boot_fail', 'error')
seen, n = set(), 0
with open(a.out, 'w') as fo:
    for p in a.screen:
        for l in open(p):
            r = json.loads(l)
            if not (r['screen'] == 'pass' or r['screen'].startswith(UNJUDGED)): continue
            k = (r['site_id'], r['replacement'])
            if k in seen or k in done: continue
            seen.add(k); s = sites[r['site_id']]
            fo.write(json.dumps({'site_id': s['site_id'], 'file': s['file'], 'start_byte': s['start_byte'],
                                 'end_byte': s['end_byte'], 'original': s['original'],
                                 'replacement': r['replacement'], 'screen': r['screen']}, ensure_ascii=False) + '\n')
            n += 1
print('queued', n)
