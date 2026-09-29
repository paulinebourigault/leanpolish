#!/usr/bin/env python3
"""Greedy valid-and-shorter on the 1,406 original held-out teacher sites for one checkpoint.
valid iff strictly shorter (count_appL) AND (== teacher's kernel-verified reference, OR candidate
key has kernel_verdict pass in archived verification, OR pass in fresh `lake env lean`
verification files given via --verdicts). Unknowns (no verdict anywhere) written for verification.
usage: seeds_eval.py GENS OUT_JSON [--verdicts f1,f2]"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import glob, hashlib, json, sys
from collections import Counter, defaultdict
from retokenize_appendixL import count_appL
# SFT_RESULTS: directory with verify_chunks*/ and screen_results.jsonl of the learning experiment
EXP = _os.environ.get('SFT_RESULTS', str(ROOT / 'results_data' / 'exp1_sft_dpo'))
gens = {json.loads(l)['site_id']: json.loads(l) for l in open(sys.argv[1])}
passk, failk = set(), set()
for p in glob.glob(f'{EXP}/verify_chunks*/*kernel_verified.jsonl'):
    for l in open(p):
        r = json.loads(l); (passk if r.get('kernel_verdict') == 'pass' else failk).add(r['key'])
for l in open(f'{EXP}/screen_results.jsonl'):
    r = json.loads(l)
    if r.get('screen_verdict') in ('fail', 'introduces_sorry'): failk.add(r['key'])
newv = {}
if '--verdicts' in sys.argv:
    for p in sys.argv[sys.argv.index('--verdicts') + 1].split(','):
        for l in open(p):
            r = json.loads(l); newv[(r['site_id'], r['replacement'])] = r['verdict']
res = defaultdict(Counter); unknown = []
for c in ('minif2f', 'putnam_verified', 'putnam2025_per_file'):
    for l in open(f'{EXP}/data/eval_sites_{c}.jsonl'):
        s = json.loads(l)
        g = gens[s['attempt_id']]['greedy']
        fam = {'dead_code_removal': 'deletion', 'tactic_replacement': 'tactic', 'l2_replacement': 'lemma'}.get(s['type'], s['type'])
        k = hashlib.sha256(f"{s['file']}:{s['start_byte']}:{s['end_byte']}:{g}".encode()).hexdigest()
        shorter = count_appL(s['original']) - count_appL(g) > 0
        for key in (c, f'{c}/{fam}'):
            res[key]['sites'] += 1
        if not shorter:
            v = 'not_shorter'
        elif g == s['reference_replacement'] or k in passk or newv.get((s['attempt_id'], g)) == 'pass':
            v = 'vs'
        elif k in failk or (s['attempt_id'], g) in newv:
            v = 'fail'
        else:
            v = 'unknown'; unknown.append({'site_id': s['attempt_id'], 'file': s['file'], 'start_byte': s['start_byte'],
                                          'end_byte': s['end_byte'], 'original': s['original'], 'replacement': g})
        for key in (c, f'{c}/{fam}'):
            res[key][v] += 1
out = {k: dict(d, vs_pct=round(100 * d['vs'] / d['sites'], 2),
               vs_pct_upper=round(100 * (d['vs'] + d['unknown']) / d['sites'], 2)) for k, d in sorted(res.items())}
json.dump(out, open(sys.argv[2], 'w'), indent=1)
with open(sys.argv[2].replace('.json', '_unknown.jsonl'), 'w') as f:
    for u in unknown: f.write(json.dumps(u, ensure_ascii=False) + '\n')
print({k: (v['vs_pct'], v.get('unknown', 0)) for k, v in out.items() if '/' not in k}, len(unknown), 'unknown')
