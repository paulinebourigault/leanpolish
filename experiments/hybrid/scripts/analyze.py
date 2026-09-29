#!/usr/bin/env python3
"""Aggregate verified-hybrid results into metrics.json (reads sites/, gens/,
screen/, verify/, compose/ and files/ under $HYBRID_WORKDIR)."""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import json, os, sys, glob, re
from collections import Counter, defaultdict
from pathlib import Path
from retokenize_appendixL import count_appL
from quality_filter import is_quality_upgrade, menu_class
from lean_counter import count_lean_tokens

# HYBRID_WORKDIR: working directory holding sites/, gens/, screen/, verify/, compose/, files/
R = Path(_os.environ.get('HYBRID_WORKDIR', '.'))

def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []

def head(t):
    t = t.strip()
    m = re.match(r"[A-Za-z_][A-Za-z0-9_?!]*", t)
    return m.group(0) if m else (t[:1] or '<DELETE>')

def corpus_metrics(C, V, gens_path=None, screen_paths=None, verify_glob=None):
    sites = {s['site_id']: s for s in jl(R / f'sites/sites_{C}_{V}.jsonl')}
    gens = {g['site_id']: g for g in jl(gens_path or R / f'gens/{C}_{V}.jsonl')}
    scr = defaultdict(dict)
    for r in (x for sp in (screen_paths or [R / f'screen/{C}_{V}.jsonl']) for x in jl(sp)):
        scr[r['site_id']][r['replacement']] = r['screen']
    ver = defaultdict(dict)
    for p in glob.glob(verify_glob or str(R / f'verify/{C}_{V}*.verdicts.jsonl')):
        for r in jl(p):
            ver[r['site_id']][r['replacement']] = r['verdict']
    if not sites or not gens: return None
    m = Counter(); tok = Counter(); ex = []
    heads = Counter(); menu = Counter(); reasons = Counter()
    for sid, s in sites.items():
        g = gens.get(sid)
        if not g: continue
        m['sites_generated'] += 1
        o = s['original']; to = count_appL(o)
        def cand_ok(c, lane):
            if c == o or c.strip() == o.strip() or count_appL(c) >= to: return None
            if lane == 'screen': return scr[sid].get(c) == 'pass'
            return ver[sid].get(c) == 'pass'
        for lane in ('screen', 'verified'):
            gv = cand_ok(g['greedy'], lane)
            if lane == 'screen' and gv is not None: m['greedy_shorter_candidate'] += 1
            if gv:
                m[f'{lane}_greedy_sites'] += 1; tok[f'{lane}_greedy'] += to - count_appL(g['greedy'])
            best = None
            for c in [g['greedy']] + g.get('samples', []):
                if cand_ok(c, lane):
                    sv = to - count_appL(c)
                    if best is None or sv > best[0]: best = (sv, c)
            if best:
                m[f'{lane}_best5_sites'] += 1; tok[f'{lane}_best5'] += best[0]
                qf = best[1].strip() == '' or is_quality_upgrade(o, best[1])
                if qf: m[f'{lane}_best5_sites_filter_ok'] += 1; tok[f'{lane}_best5_filter_ok'] += best[0]
                if lane == 'screen':
                    c = best[1]
                    heads[head(c) if c.strip() else '<DELETE>'] += 1
                    inm, item, why = menu_class(o, c)
                    if c.strip() == '': menu['deletion'] += 1
                    elif inm:
                        menu['in_menu'] += 1
                        if not qf: r_ = 'specificity_filter_would_reject'
                        elif why: r_ = why.split('(')[0]
                        elif s.get('n_goals_before', 1) > 1: r_ = 'multi_goal_node(teacher needs goalsAfter=[])'
                        else: r_ = 'unexplained_statically(first-success order/timeouts/fold budget/non-terminal node)'
                        reasons[r_] += 1
                    else: menu['outside_menu'] += 1
                    ex.append({'site_id': sid, 'goal': s['goal'][:600], 'original': o, 'edit': c, 'savings': best[0],
                               'filter_ok': qf, 'menu': item, 'verified': ver[sid].get(c)})
    screen_rows = sum(len(v) for v in scr.values())
    verified_rows = sum(len(v) for v in ver.values())
    return {'counts': dict(m), 'tokens_saved_local': dict(tok), 'best5_replacement_heads_top15': heads.most_common(15),
            'menu': dict(menu), 'teacher_miss_reasons_in_menu': dict(reasons),
            'screen_candidates': screen_rows, 'verified_candidates': verified_rows,
            'screen_verdicts': dict(Counter(v for d in scr.values() for v in d.values())),
            'verify_verdicts': dict(Counter(v for d in ver.values() for v in d.values()))}, ex

def whole_file(C, comp_root=None):
    comp_root = comp_root or R
    out = {}
    fdir = R / 'files' / C
    orig = {p.name: count_appL(p.read_text()) for p in (fdir / 'orig').glob('*.lean')}
    base = {p.name: count_appL(p.read_text()) for p in (fdir / 'base').glob('*.lean')}
    out['n_files'] = len(orig)
    out['tokens_original'] = sum(orig.values())
    out['tokens_leanpolish'] = sum(base.values())
    out['leancounter_original'] = sum(count_lean_tokens(p.read_text()) for p in (fdir / 'orig').glob('*.lean'))
    out['leancounter_leanpolish'] = sum(count_lean_tokens(p.read_text()) for p in (fdir / 'base').glob('*.lean'))
    for tag in ('hybrid_greedy', 'hybrid_all', 'hybrid_all_qf', 'hybrid_k16', 'neural_greedy', 'neural_all', 'neural_all_qf'):
        rep = jl(comp_root / f'compose/{C}_{"base" if tag.startswith("hybrid") else "orig"}_{tag.split("_",1)[1]}.jsonl')
        if tag.startswith('neural'):
            # neural-alone composes on ORIGINAL files; token base is the original corpus
            pass
        if not rep: continue
        done = {Path(r['file']).name: r for r in rep}
        if len(done) < len(orig):
            out[tag] = {'incomplete_files': len(orig) - len(done)}
            continue
        tot = sum(r['tokens_out'] for r in done.values())
        vdir = comp_root / 'files' / C / tag
        lc = sum(count_lean_tokens(p.read_text()) for p in vdir.glob('*.lean') if not p.name.startswith('.')) if vdir.exists() else None
        out[tag] = {'tokens': tot, 'edits_applied': sum(r['n_applied'] for r in done.values()),
                    'edits_selected': sum(r['n_chosen'] for r in done.values()),
                    'files_needing_bisection': sum(1 for r in done.values() if r['n_applied'] < r['n_chosen']),
                    'base_compile_failures': sum(1 for r in done.values() if not r['base_compiles']),
                    'tokens_leancounter': lc}
    T0 = out['tokens_original']
    for k, v in list(out.items()):
        if isinstance(v, dict) and 'tokens' in v:
            v['reduction_pct_vs_original'] = round(100 * (T0 - v['tokens']) / T0, 3)
            v['saved_vs_original'] = T0 - v['tokens']
            if k.startswith('hybrid'):
                v['extra_saved_vs_leanpolish'] = out['tokens_leanpolish'] - v['tokens']
    out['leanpolish_reduction_pct'] = round(100 * (T0 - out['tokens_leanpolish']) / T0, 3)
    out['leanpolish_saved'] = T0 - out['tokens_leanpolish']
    return out

def k16_curve(C, screen_paths):
    sites = {s['site_id']: s for s in jl(R / f'sites/sites_{C}_base.jsonl')}
    gens = {g['site_id']: g for g in jl(R / f'gens/{C}_base_k16.jsonl')}
    scr = defaultdict(dict)
    for sp in screen_paths:
        for r in jl(sp): scr[r['site_id']][r['replacement']] = r['screen']
    if not gens or not scr: return None
    out = {}
    for label, n in (('greedy', 0), ('greedy+4', 4), ('greedy+16', 16)):
        ns = tok = nq = tq = 0
        for sid, g in gens.items():
            o = sites[sid]['original']; to = count_appL(o); best = None
            for c in [g['greedy']] + g['samples'][:n]:
                if c.strip() == o.strip() or count_appL(c) >= to: continue
                if scr[sid].get(c) == 'pass':
                    sv = to - count_appL(c)
                    if best is None or sv > best[0]: best = (sv, c)
            if best:
                ns += 1; tok += best[0]
                if best[1].strip() == '' or is_quality_upgrade(o, best[1]): nq += 1; tq += best[0]
        out[label] = {'sites': ns, 'tokens_local': tok, 'sites_filter_ok_best': nq, 'tokens_filter_ok_best': tq}
    return out

if __name__ == '__main__':
    metrics = {'site_level': {}, 'whole_file': {}, 'qwen': {'site_level': {}, 'whole_file': {}}, 'k16': {}}
    allex = {}
    for C in ('putnam2025', 'putnam_verified', 'minif2f'):
        for V in ('base', 'orig'):
            r = corpus_metrics(C, V)
            if r: metrics['site_level'][f'{C}_{V}'], allex[f'{C}_{V}'] = r
        if (R / 'files' / C / 'orig').exists():
            metrics['whole_file'][C] = whole_file(C)
        q = corpus_metrics(C, 'base', gens_path=R / f'gens/qwen_{C}_base.jsonl',
                           screen_paths=[R / f'qwen/screen/{C}_base.jsonl'], verify_glob=str(R / f'qwen/verify/qwen_{C}_base.verdicts.jsonl'))
        if q: metrics['qwen']['site_level'][f'{C}_base'] = q[0]
        if (R / 'qwen' / 'compose').exists():
            metrics['qwen']['whole_file'][C] = whole_file(C, comp_root=R / 'qwen')
    for C, sp in (('putnam2025', [R / 'screen/putnam2025_base_k16_p1.jsonl', R / 'screen/putnam2025_base_k16_cpu.jsonl']),
                  ('putnam_verified', [R / 'screen/putnam_verified_base_k16.jsonl'])):
        k = k16_curve(C, sp)
        if k: metrics['k16'][C] = k
    old = R / 'metrics_old_sites.json'
    if old.exists(): metrics['old_sites_reproduction'] = json.load(open(old))
    json.dump(metrics, open(R / 'metrics.json', 'w'), indent=1, ensure_ascii=False)
    json.dump(allex, open(R / 'examples_all.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(metrics, indent=1, ensure_ascii=False)[:3000])
