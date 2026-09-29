#!/usr/bin/env python3
"""Select 1,000 Goedel-Workbook TRAINING files (SFT train split, never val) with the most
tactic lines NOT covered by accepted teacher edits (cheap text heuristic), fixed seed 42.

Train/val split: build_sft_data.py splits by source file (seed 42, 2% val); we recover it
exactly from the released split files (file field of sft_train.jsonl / sft_val.jsonl).
Teacher coverage: accepted goedel rows with byte spans (tactic_replacement,
dead_code_removal, l2_replacement) -> lines covered by [start_byte,end_byte); warning_cleanup
rows (byte span 0:0) -> their reported `line`.
Heuristic tactic line: a non-blank, non-comment line after the first `:= by` of the file.
Environment: CORPUS_ROOT (dir holding shards/goedel/training_pairs.jsonl and the
goedel_workbook/*.lean sources; default ./corpus), DATA_DIR (dir with sft_train.jsonl /
sft_val.jsonl from experiments/sft/build_sft_data.py; default ./data).
Outputs: ../data/selected_files.json (ordered list + per-file stats), ../data/teacher_spans.json
"""
import json, random, re, os
from collections import defaultdict
RO = os.environ.get('CORPUS_ROOT', 'corpus')
EXP = os.environ.get('DATA_DIR', 'data')
OUT = os.path.join(os.path.dirname(__file__), '..', 'data')
N, SEED = 1000, 42

train_files = {json.loads(l)['file'] for l in open(f'{EXP}/sft_train.jsonl')}
val_files = {json.loads(l)['file'] for l in open(f'{EXP}/sft_val.jsonl')}
assert not (train_files & val_files)
spans, warn_lines = defaultdict(list), defaultdict(set)
for l in open(f'{RO}/shards/goedel/training_pairs.jsonl'):
    r = json.loads(l)
    if r.get('outcome') != 'accepted': continue
    if r['type'] == 'warning_cleanup':
        warn_lines[r['file']].add(r['line'])
    else:
        spans[r['file']].append((r['start_byte'], r['end_byte'], r['original'], r['type']))

cands = sorted(f for f in train_files if f.startswith('goedel_workbook/')
               and re.fullmatch(r'goedel_workbook/lean_workbook_(plus_)?\d+\.lean', f))
stats = {}
for f in cands:
    p = f'{RO}/{f}'
    if not os.path.exists(p): continue
    b = open(p, 'rb').read()
    ok_spans = [(s, e) for s, e, o, t in spans[f] if b[s:e].decode('utf-8', 'replace') == o]
    lines = b.split(b'\n'); starts = []; acc = 0
    for ln in lines: starts.append(acc); acc += len(ln) + 1
    covered = set(warn_lines[f])
    for s, e in ok_spans:
        for i, st in enumerate(starts):
            en = st + len(lines[i])
            if st < e and s <= en and not (e == st): covered.add(i + 1)
    txt = b.decode('utf-8', 'replace')
    m = re.search(r':=\s*by\b', txt)
    if not m: continue
    first = txt[:m.end()].count('\n') + 1
    tac = [i + 1 for i in range(first, len(lines))
           if lines[i].strip() and not lines[i].strip().startswith((b'--', b'/-'))]
    unc = [i for i in tac if i not in covered]
    stats[f] = {'tactic_lines': len(tac), 'uncovered_tactic_lines': len(unc),
                'teacher_spans': len(ok_spans), 'teacher_spans_mismatch': len(spans[f]) - len(ok_spans),
                'warning_lines': len(warn_lines[f]), 'bytes': len(b)}
rng = random.Random(SEED)
keys = list(stats); rng.shuffle(keys)                  # seeded tie-break
keys.sort(key=lambda f: -stats[f]['uncovered_tactic_lines'])  # stable sort keeps shuffle order among ties
sel = keys[:N]
os.makedirs(OUT, exist_ok=True)
json.dump({'seed': SEED, 'n_candidates': len(stats), 'n_train_files_all_shards': len(train_files),
           'n_val_files': len(val_files),
           'threshold_uncovered_lines': stats[sel[-1]]['uncovered_tactic_lines'],
           'files': [{'file': f, **stats[f]} for f in sel]},
          open(f'{OUT}/selected_files.json', 'w'), indent=1)
json.dump({f: {'spans': [[s, e] for s, e, o, t in spans[f] if open(f'{RO}/{f}', 'rb').read()[s:e].decode('utf-8','replace') == o],
               'warning_lines': sorted(warn_lines[f])} for f in sel},
          open(f'{OUT}/teacher_spans.json', 'w'))
u = [stats[f]['uncovered_tactic_lines'] for f in sel]
print('candidates', len(stats), 'selected', len(sel), 'uncovered lines: min', min(u), 'max', max(u), 'sum', sum(u))
import statistics; print('all-candidates median uncovered', statistics.median(s['uncovered_tactic_lines'] for s in stats.values()))
print('bytes selected median', statistics.median(stats[f]['bytes'] for f in sel), 'max', max(stats[f]['bytes'] for f in sel))
