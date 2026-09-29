#!/usr/bin/env python3
"""Aggregate hybrid-control results into metrics.json.

Whole-file token reduction uses the paper convention: denominator = appL tokens of ALL original
files of the corpus set; any file without a verified output (compose missing / failed) counts as
its original (0 reduction). Every output file counted here is either (a) a compose.py output,
which is written only after a fresh `lake env lean` of the joint file succeeded (or is the unchanged
input), or (b) a leanpolish.py `_shortened.lean` (fresh post-verified) or its unchanged input.
We also report a comment-stripped variant (comments removed from both sides before counting), since
whole-proof LLM rewrites can shorten proofs just by dropping comments.

Usage: analyze_controls.py --root CONTROLS_WORKDIR [--bt HYBRID_WORKDIR] --out metrics.json
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, glob, json, os, re, sys
from collections import Counter, defaultdict
from pathlib import Path
from retokenize_appendixL import count_appL  # noqa: E402
from lean_counter import count_lean_tokens  # noqa: E402  (port of LeanPolish countLeanTokens, comment-skipping)

CORPORA = {'putnam_verified': ('files', 'putnam_verified'), 'putnam2025': ('files', 'putnam2025'),
           'minif2f100': ('files100', 'minif2f'), 'putnam_verified19': ('files', 'putnam_verified')}
# paper's 19 PB-verified files = the 24 minus 2 files without a proof and 3 that do not compile under Lean/Mathlib v4.21
PV_EXCLUDE19 = {'putnam_2008_a6.lean', 'sum_squares_of_nonneg.lean', 'putnam_1978_a5.lean', 'putnam_2010_a4.lean', 'putnam_2018_b3.lean'}


def strip_comments(t):
    t = re.sub(r'/-.*?-/', '', t, flags=re.S)
    return re.sub(r'--[^\n]*', '', t)


def jl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def tok(p, strip=False):
    t = Path(p).read_text()
    if strip == 'lean': return count_lean_tokens(t)
    return count_appL(strip_comments(t) if strip else t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=_os.environ.get('CONTROLS_WORKDIR', '.'))
    ap.add_argument('--bt', default=None, help='hybrid working directory with hybrid outputs (files/<C>/hybrid_*)')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    R = Path(args.root)
    stages = [x for p in sorted(glob.glob(str(R / 'costs/stages*.jsonl'))) for x in jl(p)]
    out = {'whole_file': {}, 'cost': {}, 'c2_candidates': {}}
    for C, (fr, CC) in CORPORA.items():
        odir = R / fr / CC / 'orig'
        names = sorted(p.name for p in odir.glob('*.lean'))
        if C == 'putnam_verified19': names = [n for n in names if n not in PV_EXCLUDE19]
        res = {}
        for strip in ('lean', False, True):
            key = {'lean': 'lean', False: 'raw', True: 'stripped'}[strip]
            T0 = {n: tok(odir / n, strip) for n in names}
            base = {n: tok(R / fr / CC / 'base' / n, strip) for n in names}
            conds = {'original': T0, 'leanpolish': base}
            # composed conditions: any dir under files/<CC>/ other than orig/base
            for d in sorted((R / fr / CC).iterdir()):
                if not d.is_dir() or d.name in ('orig', 'base') or d.name.endswith('_post'): continue
                conds[d.name] = {n: (tok(d / n, strip) if (d / n).exists() else T0[n]) for n in names}
            for d in sorted((R / fr / CC).glob('*_post')):
                # post-pass: LeanPolish on LLM-changed files; unchanged files -> LeanPolish(original) = base
                pre = d.name.replace('_post', '_orig')
                def post_tok(n, d=d, pre=pre):
                    if (d / n).exists(): return tok(d / n, strip)
                    llm = R / fr / CC / pre / n
                    if llm.exists() and llm.read_bytes() != (odir / n).read_bytes():
                        return tok(llm, strip)   # LeanPolish post-pass pending: count the verified LLM output
                    return base[n]               # LLM left the file unchanged: post-pass == LeanPolish(original)
                conds[d.name] = {n: post_tok(n) for n in names}
            if args.bt:
                for d in sorted(Path(args.bt, 'files', CC).glob('hybrid_*')):
                    got = {n: tok(d / n, strip) for n in names if (d / n).exists()}
                    conds['MAIN_' + d.name] = {n: got.get(n, T0[n]) for n in names}
                    conds['MAIN_' + d.name + '__coverage'] = len(got)
            tot0 = sum(T0.values())
            tab = {}
            for k, v in conds.items():
                if k.endswith('__coverage'):
                    tab[k] = v; continue
                t = sum(v.values())
                tab[k] = {'tokens': t, 'saved': tot0 - t, 'reduction_pct': round(100 * (tot0 - t) / tot0, 3),
                          'files_changed': sum(1 for n in names if v[n] != T0[n])}
            res[key] = tab
        res['n_files'] = len(names)
        out['whole_file'][C] = res
    # C2 candidate statistics (parse + screen + compose), per model / corpus / variant / k
    for raw in glob.glob(str(R / 'gens/*_raw.jsonl')):
        M = Path(raw).name[:-len('_raw.jsonl')]
        rows = {r['site_id']: r for r in jl(raw)}
        for C in [c for c in CORPORA if c != 'putnam_verified19']:
            for V in ('orig', 'base', 'lp_rerun'):
                units = jl(R / f'sites/c2_units_{C}_{V}.jsonl')
                if not units or not (R / f'screen/{M}_{C}_{V}.jsonl').exists(): continue
                scr = defaultdict(dict)
                for r in jl(R / f'screen/{M}_{C}_{V}.jsonl'):
                    scr[r['site_id']][r['replacement']] = r['screen']
                for K, n in (('k4', 4), ('k16', 16)):
                    st = Counter(); gen_tokens = 0
                    for u in units:
                        r = rows.get(u['site_id'])
                        if not r: st['unit_not_generated'] += 1; continue
                        gen_tokens += sum(r['gen_tokens'][:n])
                        st['samples'] += len(r['why'][:n])
                        for w in r['why'][:n]:
                            st['parse_' + w.split(':')[0]] += 1
                    st['gen_tokens'] = gen_tokens
                    # screen outcome over distinct shorter candidates (k16 screen covers k4 set)
                    g = {x['site_id']: x for x in jl(R / f'gens/{M}_{K}.jsonl')}
                    for u in units:
                        x = g.get(u['site_id'])
                        if not x: continue
                        cands = {c for c in [x['greedy']] + x.get('samples', []) if c.strip() != u['original'].strip()}
                        shorter = {c for c in cands if count_appL(c) < count_appL(u['original'])}
                        st['distinct_changed_cands'] += len(cands)
                        st['distinct_shorter_cands'] += len(shorter)
                        for c in shorter:
                            st['screen_' + str(scr[u['site_id']].get(c, 'missing'))] += 1
                        st['units_with_passing_shorter'] += any(scr[u['site_id']].get(c) == 'pass' for c in shorter)
                    srows = jl(R / f'screen/{M}_{C}_{V}.jsonl')
                    st['screen_decl_elabs'] = sum(1 for r in srows if r.get('how') == 'decl' and r.get('sample_index', 0) < n)
                    st['screen_file_boots'] = len({x['file'] for x in units})
                    st['screen_exhaustive'] = all(r.get('exhaustive', True) for r in srows if r.get('how') == 'decl')
                    comp = jl(R / f'compose/{M}_{C}_{V}_{K}.jsonl')
                    st['compose_files'] = len(comp)
                    st['compose_fresh_compiles'] = sum(r['compiles'] for r in comp)
                    st['compose_edits_selected'] = sum(r['n_chosen'] for r in comp)
                    st['compose_edits_applied'] = sum(r['n_applied'] for r in comp)
                    st['units'] = len(units)
                    out['c2_candidates'][f'{M}|{C}|{V}|{K}'] = dict(st)
    # REPL / Lean call counts per screen file
    for p in glob.glob(str(R / 'screen/*.jsonl')):
        T = Path(p).stem
        rows = jl(p)
        c = Counter(r.get('how', '-') for r in rows)
        out['cost'][T] = {'screen_rows': len(rows), 'repl_tactic_replays': c.get('tactic', 0),
                          'repl_decl_elabs': c.get('decl', 0),
                          'screen_verdicts': dict(Counter(r['screen'] for r in rows))}
    for p in glob.glob(str(R / 'post/*.jsonl')) + glob.glob(str(R / 'lprerun/*.jsonl')) + glob.glob(str(R / 'c3/lp_*.jsonl')):
        rows = jl(p)
        out['cost'][Path(p).parent.name + '_' + Path(p).stem] = {'files': len(rows), 'lp_wall_s_sum': round(sum(r['wall_s'] for r in rows)),
                                               'lp_candidate_checks': sum(r['lp_candidate_checks'] for r in rows),
                                               'lp_fresh_postverify': sum(1 for r in rows if r['shortened']),
                                               'tokens_in': sum(r['tokens_in'] for r in rows),
                                               'tokens_out': sum(r['tokens_out'] for r in rows)}
    for p in glob.glob(str(R / 'gens/*.cost.json')):
        out['cost']['gen_' + Path(p).name[:-len('.cost.json')]] = json.load(open(p))
    for key, st in out['c2_candidates'].items():
        M = key.split('|')[0]
        cj = out['cost'].get('gen_' + M)
        if cj and cj.get('gen_tokens'):
            st['gpu_s_share'] = round(cj['gpu_s'] * st['gen_tokens'] / cj['gen_tokens'], 1)
        st['lean_calls'] = st.get('screen_decl_elabs', 0) + st.get('screen_file_boots', 0) + st.get('compose_fresh_compiles', 0)
    out['stages'] = stages
    json.dump(out, open(args.out, 'w'), indent=1)
    print(json.dumps(out['whole_file'], indent=1)[:5000])


if __name__ == '__main__':
    main()
