#!/usr/bin/env python3
"""Goal hashes of all held-out material (as build_sft_data.py: whitespace-normalized SHA-256 over
goal_type/goal_state/goal_pretty of every eval-shard row; plus the `goal` of every beyond_teacher
held-out site). New training edits whose goal hash is in this set are dropped.
Environment: SHARDS_ROOT (released shards; default ./shards), HYBRID_SITES (glob of hybrid
site files; default ./sites/sites_*_base.jsonl). Output: ./data/heldout_goal_hashes.json"""
import os
import glob, gzip, hashlib, json, re
WS = re.compile(r'\s+'); PH = re.compile(r'^(cleanup|dead_code|L2_arity\d+_(lemma|prop))$')
h = lambda s: hashlib.sha256(WS.sub(' ', s).strip().encode()).hexdigest()
RO = os.environ.get('SHARDS_ROOT', 'shards')
H = set()
for sh in ('minif2f', 'putnam_verified', 'putnam2025_per_file'):
    for fn in sorted(glob.glob(f'{RO}/{sh}/training_pairs*.jsonl.gz')):
        for l in gzip.open(fn, 'rt'):
            r = json.loads(l)
            for k in ('goal_type', 'goal_state', 'goal_pretty'):
                g = r.get(k)
                if g and not PH.match(g.strip()): H.add(h(g))
n0 = len(H)
for p in glob.glob(os.environ.get('HYBRID_SITES', 'sites/sites_*_base.jsonl')):
    for l in open(p):
        g = json.loads(l).get('goal')
        if g: H.add(h(g))
json.dump(sorted(H), open('data/heldout_goal_hashes.json', 'w'))
print('eval-shard hashes', n0, 'total with hybrid sites', len(H))
