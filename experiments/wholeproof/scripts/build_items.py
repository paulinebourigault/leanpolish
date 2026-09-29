#!/usr/bin/env python3
"""Eval items: miniF2F-100 (minif2f_subsample100.txt, seed 0 of 354), PutnamBench-verified
(24 files), Putnam2025 AxiomProver (12 files); variants orig (original file) and base
(LeanPolish-shortened file, <HYBRID_FILES>/<corpus>/base). The controls C2 unit is attached (for
the C2-prompt frozen control) when the file has exactly one unit.

Env: HYBRID_FILES  files/ tree of the hybrid experiment (dataset tarball experiments/beyond_teacher)
     CONTROLS_DIR  controls data dir with sites/c2_units_*.jsonl (dataset tarball experiments/hybrid_controls)
     SUBSAMPLE     miniF2F-100 list (default: CONTROLS_DIR/minif2f_subsample100.txt)
Output: data/items_<corpus>_<orig|base>.jsonl in the current directory."""
import json, collections, os
from pathlib import Path
BT = Path(os.environ.get('HYBRID_FILES', 'data/beyond_teacher/files'))
HC = Path(os.environ.get('CONTROLS_DIR', 'data/hybrid_controls'))
mf = [l.strip() for l in open(os.environ.get('SUBSAMPLE', HC / 'minif2f_subsample100.txt')) if l.strip()]
out = Path('data'); out.mkdir(exist_ok=True)
for corpus, names, ucorp in (('minif2f100', mf, 'minif2f100'),
                             ('putnam_verified', None, 'putnam_verified'),
                             ('putnam2025', None, 'putnam2025')):
    bc = 'minif2f' if corpus == 'minif2f100' else corpus
    if names is None:
        names = sorted(p.stem for p in (BT / bc / 'orig').glob('*.lean'))
    for var in ('orig', 'base'):
        units = collections.defaultdict(list)
        for l in open(HC / f'sites/c2_units_{ucorp}_{var}.jsonl'):
            u = json.loads(l); units[Path(u['file']).stem].append(u)
        with open(out / f'items_{corpus}_{var}.jsonl', 'w') as fo:
            for n in names:
                t = (BT / bc / var / f'{n}.lean').read_text()
                us = units.get(n, [])
                if us: assert t.encode()[us[0]['start_byte']:us[0]['end_byte']].decode() == us[0]['original']
                fo.write(json.dumps({'id': f'{corpus}/{var}/{n}', 'corpus': corpus, 'variant': var, 'name': n,
                                     'text': t, 'unit': us[0] if len(us) == 1 else None,
                                     'n_units': len(us)}, ensure_ascii=False) + '\n')
        print(corpus, var, len(names), 'with single unit:', sum(1 for n in names if len(units.get(n, [])) == 1))
