#!/usr/bin/env python3
"""Evaluation metrics for round-1 vs round-2 variants (pre-registered rules, see README).
A candidate succeeds iff != original, strictly shorter under count_appL and exact verdict 'pass'
(verify_*.jsonl; anything never queued = screen-rejected = fail).
Teacher sites: vs@1 (greedy) and vs@5 (greedy or any of 4 samples), per corpus x family.
Hybrid (beyond-teacher) sites: per-site best verified count_appL saving (@1 greedy-only, @5), summed.
CIs: file-level bootstrap 2000x seed 42; paired differences vs --ref model.
Usage: eval_metrics.py --sites a.jsonl b.jsonl --verify v1.jsonl .. --model r1=gens_r1.jsonl --model r2n=... --ref r1 --out m.json"""
import argparse, json, os, random, sys
from collections import defaultdict
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get('LEANPOLISH_ROOT', os.path.abspath(os.path.join(_HERE, '..', '..', '..')))
for _p in (_HERE, os.path.join(_ROOT, 'experiments', 'hybrid', 'scripts'), os.path.join(_ROOT, 'leanpolish')):
    sys.path.insert(0, _p)
from retokenize_appendixL import count_appL
from quality_filter import is_quality_upgrade
ap = argparse.ArgumentParser()
ap.add_argument('--sites', nargs='+', required=True); ap.add_argument('--verify', nargs='+', required=True)
ap.add_argument('--model', action='append', required=True); ap.add_argument('--ref', default=None)
ap.add_argument('--out', required=True); ap.add_argument('--B', type=int, default=2000)
a = ap.parse_args()
sites = {}
for p in a.sites:
    for l in open(p):
        s = json.loads(l)
        s.setdefault('family', 'nonteacher'); s['_set'] = 'teacher' if 'reference_replacement' in s else 'beyond_teacher'
        sites[s['site_id']] = s
ok = set()
for p in a.verify:
    if not os.path.exists(p): continue
    for l in open(p):
        v = json.loads(l)
        if v['verdict'] == 'pass': ok.add((v['site_id'], v['replacement']))
def sav(s, c):
    if c == s['original'] or c.strip() == s['original'].strip(): return 0
    d = count_appL(s['original']) - count_appL(c)
    return d if d > 0 and (s['site_id'], c) in ok else 0
per = {}  # model -> site -> (s1, s5, sav1, sav5)
for m in a.model:
    name, path = m.split('=', 1); per[name] = {}
    for l in open(path):
        g = json.loads(l); s = sites.get(g['site_id'])
        if s is None: continue
        v1 = sav(s, g['greedy']); v5 = max([v1] + [sav(s, c) for c in g.get('samples', [])])
        per[name][g['site_id']] = (v1 > 0, v5 > 0, v1, v5)
groups = defaultdict(list)
for sid, s in sites.items():
    c = s.get('corpus'); f = s['family']
    for key in (f"{s['_set']}|ALL|{f}", f"{s['_set']}|{c}|{f}", f"{s['_set']}|ALL|ALL", f"{s['_set']}|{c}|ALL"):
        groups[key].append(sid)
rng = random.Random(42)
def stat(name, sids, idx, rate):
    vals = [per[name].get(x, (0, 0, 0, 0))[idx] for x in sids]
    return (100 * sum(vals) / len(vals)) if rate else sum(vals)
def boot(fn, sids):
    byf = defaultdict(list)
    for x in sids: byf[sites[x]['file']].append(x)
    fs = sorted(byf); out = []
    r = random.Random(42)
    for _ in range(a.B):
        samp = [x for f in (r.choice(fs) for _ in fs) for x in byf[f]]
        out.append(fn(samp))
    out.sort(); return [round(out[int(0.025 * a.B)], 2), round(out[int(0.975 * a.B) - 1], 2)]
res = {'n_verified_pass_keys': len(ok), 'groups': {}}
names = list(per)
for key, sids in sorted(groups.items()):
    sids = [x for x in sids if all(x in per[n] for n in names)]
    if not sids: continue
    G = {'n_sites': len(sids), 'n_files': len({sites[x]['file'] for x in sids})}
    teacher = key.startswith('teacher')
    for n in names:
        for idx, lab in ((0, 'vs@1'), (1, 'vs@5')) if teacher else ((2, 'saving@1'), (3, 'saving@5')):
            G[f'{n}:{lab}'] = round(stat(n, sids, idx, teacher), 2)
            G[f'{n}:{lab}_ci'] = boot(lambda ss, n=n, idx=idx: stat(n, ss, idx, teacher), sids)
            if a.ref and n != a.ref:
                d = lambda ss, n=n, idx=idx: stat(n, ss, idx, teacher) - stat(a.ref, ss, idx, teacher)
                G[f'{n}-{a.ref}:{lab}'] = round(d(sids), 2); G[f'{n}-{a.ref}:{lab}_ci'] = boot(d, sids)
        if not teacher:
            G[f'{n}:sites_with_verified@5'] = sum(per[n][x][1] for x in sids)
    res['groups'][key] = G
# POST-HOC metric (added after observing training-data composition; NOT pre-registered):
# specificity-filter compliance of verified successful outputs, and swap-type counts.
from collections import Counter
def head(t):
    t = t.strip(); return t.split()[0] if t else '<DEL>'
res['posthoc_compliance'] = {}
for n in names:
    for setname in ('teacher', 'beyond_teacher'):
        for dec in ('greedy', 'all5'):
            succ = []
            for l in open(dict(m.split('=', 1) for m in a.model)[n]):
                g = json.loads(l); s = sites.get(g['site_id'])
                if s is None or s['_set'] != setname: continue
                if setname == 'teacher' and s['family'] != 'tactic': continue
                cs = [g['greedy']] + (g.get('samples', []) if dec == 'all5' else [])
                for c in dict.fromkeys(cs):
                    if sav(s, c) > 0: succ.append((s['original'], c))
            if not succ: continue
            comp = [is_quality_upgrade(o, c) for o, c in succ]
            res['posthoc_compliance'][f'{n}|{setname}|{dec}'] = {
                'n_successful_unique': len(succ), 'n_compliant': sum(comp),
                'compliance_rate': round(100 * sum(comp) / len(succ), 1),
                'n_deletion': sum(c.strip() == '' for o, c in succ),
                'noncompliant_swaps': Counter(f'{head(o)}->{head(c)}' for (o, c), ok_ in zip(succ, comp) if not ok_).most_common(12)}
json.dump(res, open(a.out, 'w'), indent=1)
for k, v in res['posthoc_compliance'].items(): print('POSTHOC', k, {kk: vv for kk, vv in v.items() if kk != 'noncompliant_swaps'})
for k, G in res['groups'].items():
    print(k, {kk: vv for kk, vv in G.items() if not kk.endswith('_ci')})
