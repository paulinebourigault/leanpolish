#!/usr/bin/env python3
"""Hybrid / neural-alone lanes on the unified metric basis (experiments/metrics): same file lists,
counter A (countLeanTokens port) primary, B (count_appL) secondary. Reads the unified-metric outputs (experiments/metrics),
does not modify them. Writes unified_hybrid.json."""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import json, sys
from pathlib import Path
# HYBRID_WORKDIR: hybrid working directory (files/, qwen/files/; HF experiments/beyond_teacher tarball)
# METRICS_DIR: unified-metric folder (file_lists/ and metrics.json, see experiments/metrics)
BT = Path(_os.environ.get('HYBRID_WORKDIR', '.'))
MU = Path(_os.environ.get('METRICS_DIR', ROOT / 'experiments' / 'metrics'))
from lean_counter import count_lean_tokens as cA
from retokenize_appendixL import count_appL as cB
MUM = json.load(open(next(q for q in (MU / 'metrics.json', MU / 'results' / 'metrics.json') if q.exists())))
def local_name(C, entry):
    return Path(entry).parent.name + '.lean' if C == 'putnam2025' else Path(entry).name
LANES = [('orig', BT, 'orig'), ('leanpolish', BT, 'base')] + \
        [(f'deepseek_{t}', BT, t) for t in ('hybrid_greedy', 'hybrid_all', 'hybrid_all_qf', 'hybrid_k16', 'neural_greedy', 'neural_all', 'neural_all_qf')] + \
        [(f'qwen_{t}', BT / 'qwen', t) for t in ('hybrid_greedy', 'hybrid_all', 'hybrid_all_qf')]
out = {}
for C in ('putnam2025', 'putnam_verified', 'minif2f'):
    names = [local_name(C, l.strip()) for l in open(MU / 'file_lists' / f'{C}.txt') if l.strip()]
    res = {'n_files': len(names)}
    for lane, root, sub in LANES:
        d = root / 'files' / C / sub
        if not d.exists(): continue
        miss = [n for n in names if not (d / n).exists()]
        if miss: res[lane] = {'missing_files': len(miss)}; continue
        txt = [(d / n).read_text() for n in names]
        res[lane] = {'A': sum(map(cA, txt)), 'B': sum(map(cB, txt))}
    A0, B0 = res['orig']['A'], res['orig']['B']
    for lane, v in res.items():
        if isinstance(v, dict) and 'A' in v:
            v['A_saved'] = A0 - v['A']; v['B_saved'] = B0 - v['B']
            v['A_pct'] = round(100 * v['A_saved'] / A0, 2); v['B_pct'] = round(100 * v['B_saved'] / B0, 2)
    t = MUM[C]['totals']
    res['check_vs_unified_metric'] = {'A_orig_match': t['A_orig'] == A0, 'B_orig_match': t['B_orig'] == B0,
                                      'A_saved_teacher_match': t['A_saved'] == res['leanpolish']['A_saved'],
                                      'B_saved_teacher_match': t['B_saved'] == res['leanpolish']['B_saved']}
    out[C] = res
json.dump(out, open(BT / 'unified_hybrid.json', 'w'), indent=1)
for C, r in out.items():
    print(C, r['n_files'], r['check_vs_unified_metric'])
    for lane, v in r.items():
        if isinstance(v, dict) and 'A' in v: print(f"  {lane:28s} A {v['A']:>7} (-{v['A_saved']}, {v['A_pct']}%)  B {v['B']:>7} (-{v['B_saved']}, {v['B_pct']}%)")
        elif isinstance(v, dict) and 'missing_files' in v: print('  ', lane, v)
