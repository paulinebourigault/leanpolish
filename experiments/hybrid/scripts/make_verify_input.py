#!/usr/bin/env python3
"""Build verify_full.py input rows from screen passes. usage: sites.jsonl screen.jsonl out.jsonl"""
import json, sys
sites = {}
for l in open(sys.argv[1]):
    s = json.loads(l); sites[s['site_id']] = s
n = 0
with open(sys.argv[3], 'w') as f:
    for p in sys.argv[2].split(','):
        for l in open(p):
            r = json.loads(l)
            if r['screen'] != 'pass' or r['site_id'] not in sites: continue
            s = sites[r['site_id']]
            f.write(json.dumps({'site_id': r['site_id'], 'file': s['file'], 'start_byte': s['start_byte'],
                                'end_byte': s['end_byte'], 'original': s['original'],
                                'replacement': r['replacement']}, ensure_ascii=False) + '\n'); n += 1
print(n, 'rows')
