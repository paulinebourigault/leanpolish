#!/usr/bin/env python3
"""Aggregate teacher + hybrid results into metrics.json (+ examples jsonl).

Both counters are computed on the actual texts (original input, LeanPolish output = hybrid
base, hybrid final file of each lane):
  A = count_lean_tokens (Python port of LeanPolish.lean countLeanTokens; equals LeanPolish's
      own tokens_original/tokens_shortened on all our files)  -- primary
  B = retokenize_appendixL.count_appL                            -- secondary
usage: aggregate.py OUT_DIR FH_ROOT editor:tag:RUN[,RUN...] ...
  e.g. aggregate.py out work deepseek:main:run_b1,run_b2 deepseek:ext:run_b1,run_b2 qwen:main:run_q1
  (ext uses combine_ext.json / final_ext; main uses combine.json / final)
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path
import os
_HERE = Path(__file__).resolve().parent
_ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
# local variants first, then shared hybrid scripts, then the shared token counters
sys.path[:0] = [str(_HERE), str(_ROOT / 'experiments' / 'hybrid' / 'scripts'), str(_ROOT / 'leanpolish')]
LEAN_PROJECT = os.environ.get('LEAN_PROJECT', str(_ROOT / 'leanpolish'))
WORK_DIR = os.environ.get('WORK_DIR', 'work')
REPL_BIN = os.environ.get('REPL_BIN', 'repl')
from retokenize_appendixL import count_appL as cB
from lean_counter import count_lean_tokens as cA
from quality_filter import is_quality_upgrade

out_dir, FH = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
te = json.load(open(FH / 'teacher_edits.json'))
LANES = ['g4_raw', 'g4_filt', 'g16_raw', 'g16_filt']
F = FH / 'files'


def both(t):
    return {'A': cA(t), 'B': cB(t)}


teacher = {}
for key, t in te.items():
    corpus, name = key.split('/')
    o = (F / corpus / 'orig' / f'{name}.lean').read_text()
    b = (F / corpus / 'base' / f'{name}.lean').read_text()
    co, cb = both(o), both(b)
    teacher[key] = {'orig': co, 'teacher': cb,
                    'teacher_saved': {k: co[k] - cb[k] for k in 'AB'},
                    'teacher_output': t['teacher_output'], 'teacher_report': t['teacher_report']}

res = {'teacher': teacher, 'editors': {}}
examples = []
for spec in sys.argv[3:]:
    editor, tag, runs = spec.split(':')
    cname, fdir = ('combine_ext.json', 'final_ext') if tag == 'ext' else ('combine.json', 'final')
    per_file = {}
    for rn in runs.split(','):
        run = FH / rn
        if not (run / cname).exists():
            continue
        comb = json.load(open(run / cname))
        sites = {json.loads(l)['site_id']: json.loads(l) for l in open(run / 'sites.jsonl')}
        fstat = defaultdict(Counter)
        for l in open(run / 'gens.jsonl'):
            g = json.loads(l); s = sites[g['site_id']]
            key = s['file'].replace('/base/', '/')[:-5]; o = s['original']
            cs = [g['greedy']] + g.get('samples', [])
            sh = {c for c in cs if c.strip() != o.strip() and cB(c) < cB(o)}
            fstat[key]['sites'] += 1
            fstat[key]['unique_shorter_cands'] += len(sh)
            fstat[key]['sites_with_shorter_cand'] += bool(sh)
        for l in open(run / 'screen.jsonl'):
            r = json.loads(l); key = sites[r['site_id']]['file'].replace('/base/', '/')[:-5]
            fstat[key]['screen_' + r['screen'].split(':')[0]] += 1
        vfiles = ['verdicts.jsonl'] + (['verdicts_gd.jsonl'] if tag == 'ext' else [])
        for vf in vfiles:
            if not (run / vf).exists():
                continue
            for l in open(run / vf):
                r = json.loads(l); s = sites[r['site_id']]
                key = s['file'].replace('/base/', '/')[:-5]
                fstat[key][f'verify_{r["verdict"]}'] += 1
                if r.get('verdict') == 'timeout':
                    fstat[key]['verify_timeouts'] += 1
        for key, lanes in comb['results'].items():
            T = teacher[key]
            rec = {'pipeline': dict(fstat[key])}
            for lane in LANES:
                L = lanes[lane]
                fin = both((run / fdir / lane / f'{key}.lean').read_text())
                rec[lane] = {'final': fin, 'final_verified': L['final_verified'],
                             'neural_increment': {k: T['teacher'][k] - fin[k] for k in 'AB'},
                             'hybrid_saved': {k: T['orig'][k] - fin[k] for k in 'AB'},
                             'hybrid_pct': {k: round(100 * (T['orig'][k] - fin[k]) / T['orig'][k], 3) for k in 'AB'},
                             'n_individually_verified_edits': L['n_individually_verified_edits'],
                             'n_sites_with_verified_edit': L['n_sites_with_verified_edit'],
                             'n_kept_joint': L['n_kept_joint'],
                             'n_kept_quality_ok': sum(e['quality_ok'] for e in L['kept'])}
            per_file[key] = rec
            if tag == 'main':
                for e in lanes['g16_raw']['kept']:
                    examples.append({'editor': editor, 'file': key, **{k: e[k] for k in (
                        'site_id', 'goal', 'original', 'replacement', 'savings', 'budget', 'quality_ok', 'deletion')},
                        'savings_A': cA(e['original']) - cA(e['replacement'])})
    tot = {}
    for lane in LANES:
        ks = sorted(per_file)
        tot[lane] = {
            'files': ks,
            'orig': {k: sum(teacher[f]['orig'][k] for f in ks) for k in 'AB'},
            'teacher_saved': {k: sum(teacher[f]['teacher_saved'][k] for f in ks) for k in 'AB'},
            'neural_increment': {k: sum(per_file[f][lane]['neural_increment'][k] for f in ks) for k in 'AB'},
            'hybrid_saved': {k: sum(per_file[f][lane]['hybrid_saved'][k] for f in ks) for k in 'AB'},
            'n_kept_joint': sum(per_file[f][lane]['n_kept_joint'] for f in ks),
            'all_final_verified': all(per_file[f][lane]['final_verified'] for f in ks)}
        t = tot[lane]
        t['teacher_pct'] = {k: round(100 * t['teacher_saved'][k] / t['orig'][k], 3) for k in 'AB'} if ks else None
        t['hybrid_pct'] = {k: round(100 * t['hybrid_saved'][k] / t['orig'][k], 3) for k in 'AB'} if ks else None
    res['editors'][f'{editor}:{tag}'] = {'per_file': per_file, 'total': tot}
json.dump(res, open(out_dir / 'metrics.json', 'w'), indent=1, ensure_ascii=False)
with open(out_dir / 'examples_kept_g16_raw.jsonl', 'w') as f:
    for e in sorted(examples, key=lambda e: -e['savings']):
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
for ed, v in res['editors'].items():
    for lane in LANES:
        t = v['total'][lane]
        print(ed, lane, 'files', len(t['files']), 'orig', t['orig'], 'teacher', t['teacher_saved'],
              'neural+', t['neural_increment'], 'hybrid', t['hybrid_pct'], 'verified', t['all_final_verified'])
