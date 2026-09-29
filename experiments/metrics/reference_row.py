#!/usr/bin/env python3
"""'Reference (pipeline)' row of Table 2 under both token counters.

Paper definition: rate = the reference edit is strictly shorter under the counter (reference edits
are kernel-verified at dataset build). The strict variant additionally requires an exact 'pass'
verdict in $RESULTS_DIR/exp1_sft_dpo/verify_chunks*. Tok. = sum of the counter's savings over all
sites (as recompute_numbers.py 'teacher_savings'). Same PASS set / ckey as recompute_numbers.py.
Input: RESULTS_DIR (see recompute_numbers.py). Output: results/reference_row.json."""
import os
import glob, hashlib, json, sys
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens as cA
from retokenize_appendixL import count_appL as cB
RES = Path(os.environ.get('RESULTS_DIR', ROOT / 'results_data')); EXP = RES
RES = RES / 'exp1_sft_dpo'
V = defaultdict(set)
for p in glob.glob(str(RES / 'verify_chunks*' / '*kernel_verified.jsonl')):
    for l in open(p):
        if l.strip():
            try: r = json.loads(l)
            except json.JSONDecodeError: continue
            V[r['key']].add(r.get('kernel_verdict'))
PASS = {k for k, v in V.items() if v == {'pass'}}
out = {}
for c in ['minif2f', 'putnam_verified', 'putnam2025_per_file']:
    rows = [json.loads(l) for l in open(EXP / 'data' / f'eval_sites_{c}.jsonl') if l.strip()]
    for nm, f in (('A_port', cA), ('B_appL', cB)):
        ok = tac_ok = tac = tok = sh = tac_sh = 0
        for r in rows:
            k = hashlib.sha256(f"{r['file']}:{r['start_byte']}:{r['end_byte']}:{r['reference_replacement']}".encode()).hexdigest()
            s = f(r['original']) - f(r['reference_replacement'])
            tok += s
            good = k in PASS and s > 0
            ok += good; sh += s > 0
            if r['type'] == 'tactic_replacement':
                tac += 1; tac_ok += good; tac_sh += s > 0
        out[f'{c}/{nm}'] = dict(sites=len(rows), paper_def_all_pct=round(100 * sh / len(rows), 1), paper_def_tac_pct=round(100 * tac_sh / tac, 1), strict_pass_all_pct=round(100 * ok / len(rows), 1),
                                strict_pass_tac_pct=round(100 * tac_ok / tac, 1), tok=tok)
json.dump(out, open(HERE / 'results' / 'reference_row.json', 'w'), indent=1)
for k, v in out.items(): print(k, v)
