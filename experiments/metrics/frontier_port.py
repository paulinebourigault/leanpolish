#!/usr/bin/env python3
"""Frontier-prover files (FRONTIER_DATA: the frontier-hybrid run directory from HF experiments/frontier_hybrid,
with files/<src>/{orig,lp}/ and run_*/final/<lane>/<src>/), both counters.
orig = pristine release file; lp = LeanPolish (teacher) output <name>_shortened.lean (falls back to
orig if the teacher produced no output); lanes = run_b*/final/<lane>/<src>/<name>.lean (falls back
to the lp text when a lane did not emit a file). Output: frontier_port.json."""
import json, os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1])); sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens as cA
from retokenize_appendixL import count_appL as cB
P = Path(os.environ.get('FRONTIER_DATA', 'frontier_hybrid'))
LANES = ['g4_raw', 'g4_filt', 'g16_raw', 'g16_filt']
out = {}
for src in ('seed', 'aristotle'):
    for o in sorted((P / 'files' / src / 'orig').glob('*.lean')):
        n = o.stem; to = o.read_text()
        lp = P / 'files' / src / 'lp' / f'{n}_shortened.lean'
        tl = lp.read_text() if lp.exists() else None
        rec = {'has_lp_output': tl is not None, 'A_orig': cA(to), 'B_orig': cB(to)}
        tl = tl if tl is not None else to
        rec.update(A_lp=cA(tl), B_lp=cB(tl))
        for lane in LANES:
            fs = sorted(P.glob(f'run_*/final/{lane}/{src}/{n}.lean'))
            t = fs[-1].read_text() if fs else tl
            rec[f'A_{lane}'] = cA(t); rec[f'B_{lane}'] = cB(t); rec[f'{lane}_file'] = bool(fs)
        out[f'{src}/{n}'] = rec
json.dump(out, open(HERE / 'results' / 'frontier_port.json', 'w'), indent=1)
for k, r in out.items():
    print(k, {x: y for x, y in r.items() if not x.endswith('_file')})
