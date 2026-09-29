#!/usr/bin/env python3
"""Sanity/baseline: compile every eval item file (orig and LeanPolish base) with a fresh
`lake env lean`, same criteria as parse_verify.compile_file.
usage: verify_refs.py OUT.jsonl ITEMS.jsonl [ITEMS.jsonl ...]"""
import json, sys, concurrent.futures as cf
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_verify import compile_file
import os
from parse_verify import TMP
os.makedirs(TMP, exist_ok=True)
items = [json.loads(l) for p in sys.argv[2:] for l in open(p)]
with cf.ThreadPoolExecutor(12) as ex, open(sys.argv[1], 'w') as fo:
    futs = {ex.submit(compile_file, it['text'], 1800): it['id'] for it in items}
    for fu in cf.as_completed(futs):
        v, dt, msg = fu.result()
        fo.write(json.dumps({'id': futs[fu], 'verdict': v, 'secs': dt, 'msg': msg}) + '\n'); fo.flush()
print('done')
