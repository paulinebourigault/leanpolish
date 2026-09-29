#!/usr/bin/env python3
"""Usage: RUN_ROOT=... EVAL_ROOT=... python3 make_bases.py OUT_DIR

Build base (teacher-shortened) and original file trees for the hybrid experiment.

putnam2025: teacher-shortened = original + all accepted training_pairs spans applied
            (single pass; content_sha256 matches the pristine inputs for this corpus).
            Cross-checked against the three archived *_shortened.lean outputs (A4, A5, B2).
minif2f / putnam_verified: the optimizer's own *_shortened.lean outputs from the
            archived run (eval_sources mirror); files without one were not edited.
Output layout: <out>/<corpus>/orig/<name>.lean and <out>/<corpus>/base/<name>.lean
"""
import json, sys, shutil
from pathlib import Path
import os
# RUN_ROOT: unpacked release (shards/ and Putnam2025_AxiomProver/); EVAL_ROOT: held-out eval sources
# (goedel_eval/ with the optimizer's *_shortened.lean outputs). Both come from the HF dataset.
RO = Path(os.environ.get('RUN_ROOT', 'data'))
EV = Path(os.environ.get('EVAL_ROOT', 'data')) / 'goedel_eval'
out = Path(sys.argv[1])

def apply(src: bytes, spans):
    spans = sorted(spans, key=lambda s: s[0])
    res, cur = b'', 0
    for s, e, rep, orig in spans:
        assert s >= cur, 'overlap'
        assert src[s:e].decode() == orig, 'mismatch'
        res += src[cur:s] + rep.encode(); cur = e
    return res + src[cur:]

manifest = {}
# putnam2025
spans = {}
for l in open(RO / 'shards/putnam2025_per_file/training_pairs.jsonl'):
    r = json.loads(l)
    if r.get('outcome') != 'accepted' or r['type'] in ('warning_cleanup', 'l2_detection'):
        continue
    spans.setdefault(r['file'], []).append((r['start_byte'], r['end_byte'], r['replacement'], r['original']))
d = out / 'putnam2025'; (d / 'orig').mkdir(parents=True, exist_ok=True); (d / 'base').mkdir(exist_ok=True)
for p in sorted((RO / 'Putnam2025_AxiomProver').glob('*/solution.lean')):
    name = p.parent.name
    src = p.read_bytes()
    key = f'Putnam2025_AxiomProver/{name}/solution.lean'
    base = apply(src, spans.get(key, []))
    sh = p.with_name('solution_shortened.lean')
    note = ''
    if sh.exists():
        note = 'matches_archived_shortened' if sh.read_bytes() == base else 'DIFFERS_from_archived_shortened'
    (d / 'orig' / f'{name}.lean').write_bytes(src)
    (d / 'base' / f'{name}.lean').write_bytes(base)
    manifest[f'putnam2025/{name}'] = {'n_teacher_edits': len(spans.get(key, [])), 'note': note}
for corpus, sub in (('minif2f', 'minif2f_verified'), ('putnam_verified', 'putnam_verified')):
    d = out / corpus; (d / 'orig').mkdir(parents=True, exist_ok=True); (d / 'base').mkdir(exist_ok=True)
    for p in sorted((EV / sub).glob('*.lean')):
        if p.name.endswith('_shortened.lean'):
            continue
        sh = p.with_name(p.stem + '_shortened.lean')
        shutil.copy(p, d / 'orig' / p.name)
        shutil.copy(sh if sh.exists() else p, d / 'base' / p.name)
        manifest[f'{corpus}/{p.stem}'] = {'teacher_shortened': sh.exists()}
json.dump(manifest, open(out / 'bases_manifest.json', 'w'), indent=1)
print({k: v for k, v in manifest.items() if k.startswith('putnam2025')})
