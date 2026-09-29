#!/usr/bin/env python3
"""Held-out teacher sites (1,406) -> site rows usable by screen_sites/verify_full.
site_id = attempt_id; file relative to files-root (goedel_eval/..., Putnam2025_AxiomProver/...).
family: 'deletion' (reference replacement empty) vs 'tactic' (type tactic_replacement) vs 'other'.
no_goal: prompt goal is '(no local goal)' (the paper's no-model deletion rule applies).
Environment: DATA_DIR (dir with eval_sites_<corpus>.jsonl; default ./data). Output: ./sites/eval_teacher.jsonl"""
import os
import json
EXP = os.environ.get('DATA_DIR', 'data')
out = open('sites/eval_teacher.jsonl', 'w'); n = 0
for c in ('minif2f', 'putnam_verified', 'putnam2025_per_file'):
    for l in open(f'{EXP}/eval_sites_{c}.jsonl'):
        r = json.loads(l)
        fam = 'deletion' if r['reference_replacement'] == '' else ('tactic' if r['type'] == 'tactic_replacement' else 'other')
        out.write(json.dumps({'site_id': r['attempt_id'], 'corpus': c, 'file': r['file'],
            'start_byte': r['start_byte'], 'end_byte': r['end_byte'], 'original': r['original'],
            'reference_replacement': r['reference_replacement'], 'type': r['type'], 'kind': r.get('kind'),
            'family': fam, 'no_goal': '[GOAL]\n(no local goal)\n' in r['prompt'], 'prompt': r['prompt']},
            ensure_ascii=False) + '\n'); n += 1
print(n)
