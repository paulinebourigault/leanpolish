#!/usr/bin/env python3
"""Ranker inside a verified search with a budget of Lean checks, on ALL held-out complete pools.

Replay of the recorded complete-menu runs: every candidate that was not skipped for length was
executed by Lean, and its outcome is stored in the pool. A policy orders a state's candidates using
only information available before verification, spends at most b Lean checks in that order, and keeps
the first acceptable edit (valid, shorter, passes the specificity filter). Every other executed
candidate is a failed check. Candidates skipped for length cost nothing. `simp?` candidates are tried
last by every policy, because their recorded text is the suggestion produced by running them.
Savings are tokens of the edited span (primary counter).

Policies: menu order, shortest string, per-tactic prior (rate of being the best candidate in the
Goedel training pools), frozen log-probabilities, the trained ranker without and with the goal.

Also reported: paired difference ranker - menu order (bootstrap over source files), and whether the
maximum candidate score tells states with an acceptable edit from states without one (AUROC, and the
savings kept when the lowest-scored states are skipped).

Usage: DATA_DIR=<unpacked complete_pools_ranker> python3 budgeted_search.py   (CPU, about a minute)
"""
import argparse, json, os, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
sys.path.insert(0, str(HERE))
from lean_counter import count_lean_tokens  # noqa: E402
from poolcommon import ACCEPTABLE, annotate, load_sites  # noqa: E402

HELD_OUT = ['cm_minif2f', 'cm_putnam_verified', 'cm_axiom']
BUDGETS = [1, 2, 4, 8, None]            # None = try every candidate
SCORES = {                              # policy -> (score file, field)
    'frozen_qwen7b': ('cm_lp_qwen7b', 'lp_qwen7b_sum'),
    'frozen_deepseek7b': ('cm_lp_dsp7b', 'lp_dsp7b_sum'),
    'ranker_no_goal': ('heldout_rk_nogoal', 'rk_nogoal_best'),
    'ranker': ('heldout_rk_full', 'rk_full_best'),
}
POLICIES = ['menu', 'shortest_string', 'tactic_prior', 'frozen_qwen7b', 'frozen_deepseek7b', 'ranker_no_goal', 'ranker']


def key(state, cand):
    return f"{state['corpus']}|{state['file']}|{state['start_byte']}|{state['end_byte']}|{cand['menu_idx']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=os.environ.get('DATA_DIR'))
    ap.add_argument('--out', type=Path, default=HERE / 'results' / 'budgeted_search.json')
    a = ap.parse_args()
    if not a.data:
        sys.exit('set DATA_DIR or pass --data (unpacked experiments/complete_pools_ranker.tar.gz)')
    pools, scores_dir = Path(a.data) / 'pools', Path(a.data) / 'scores'

    states = [s for src in HELD_OUT for s in load_sites(pools / f'{src}.jsonl.gz')]
    score = {}
    for pol, (fname, field) in SCORES.items():
        score[pol] = {}
        for line in open(scores_dir / f'{fname}.jsonl'):
            x = json.loads(line)
            score[pol][x['key']] = x[field]
    # per-tactic prior: how often each menu tactic is the best candidate in the training pools
    best, seen = defaultdict(float), defaultdict(int)
    for s in load_sites(pools / 'goedel_train.jsonl.gz'):
        for c in annotate(s)['_cands']:
            seen[c['menu_name']] += 1
            best[c['menu_name']] += c['is_best']
    prior = {k: best[k] / seen[k] for k in seen}

    def order(state, cands, pol):
        def rank(c):
            if pol == 'menu':
                v = 0
            elif pol == 'shortest_string':
                v = len(c['final_tac'])
            elif pol == 'tactic_prior':
                v = -prior.get(c['menu_name'], 0.0)
            else:
                v = -score[pol].get(key(state, c), -1e9)
            return (c['menu_name'] == 'simp?', v, c['menu_idx'])
        return sorted(cands, key=rank)

    executed, saving = [], []
    for s in states:
        cands = [c for c in s['candidates'] if not c['skipped']]
        o = count_lean_tokens(s['original'])
        executed.append(cands)
        saving.append({c['menu_idx']: o - count_lean_tokens(c['final_tac']) if c['outcome'] in ACCEPTABLE else None for c in cands})
    exhaustive = sum(max([v for v in sv.values() if v is not None] + [0]) for sv in saving)
    with_edit = sum(any(v is not None for v in sv.values()) for sv in saving)

    out = {'n_states': len(states), 'states_with_acceptable_edit': with_edit, 'exhaustive_tokens_saved': exhaustive,
           'policies': {}}
    per_state = {}
    for pol in POLICIES:
        orders = [order(s, c, pol) for s, c in zip(states, executed)]
        out['policies'][pol] = {}
        for b in BUDGETS:
            tokens = checks = failed = found = 0
            v = []
            for od, sv in zip(orders, saving):
                got = 0
                for c in (od if b is None else od[:b]):
                    checks += 1
                    if sv[c['menu_idx']] is None:
                        failed += 1
                        continue
                    got = sv[c['menu_idx']]
                    found += 1
                    break
                tokens += got
                v.append(got)
            name = 'all' if b is None else str(b)
            out['policies'][pol][name] = {'tokens_saved': tokens, 'pct_of_exhaustive': 100 * tokens / exhaustive,
                                          'lean_checks': checks, 'failed_checks': failed,
                                          'states_with_edit_pct': 100 * found / len(states)}
            per_state[(pol, name)] = np.array(v, float)

    # paired difference, ranker - menu order, bootstrap clustered over source files
    files = sorted({f"{s['corpus']}|{s['file']}" for s in states})
    index = {f: i for i, f in enumerate(files)}
    g = np.array([index[f"{s['corpus']}|{s['file']}"] for s in states])
    n_per_file = np.bincount(g, None, len(files))
    out['ranker_minus_menu'] = {}
    for b in ('1', '4'):
        r, m = per_state[('ranker', b)], per_state[('menu', b)]
        R, M = np.bincount(g, r, len(files)), np.bincount(g, m, len(files))
        idx = np.random.default_rng(0).integers(0, len(files), (20000, len(files)))
        d = (R[idx].sum(1) - M[idx].sum(1)) / n_per_file[idx].sum(1)
        out['ranker_minus_menu'][b] = {'tokens_per_state': float((r.sum() - m.sum()) / len(r)),
                                       'ci95': [float(x) for x in np.percentile(d, [2.5, 97.5])], 'n_files': len(files)}

    # does the maximum candidate score tell states with an acceptable edit from the others?
    def auroc(y, s):
        y, s = np.array(y), np.array(s)
        o = np.argsort(s)
        r = np.empty(len(s))
        r[o] = np.arange(1, len(s) + 1)
        n1 = y.sum()
        return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * (len(y) - n1)))
    live = [(s, c, sv) for s, c, sv in zip(states, executed, saving) if c]
    y = [int(any(v is not None for v in sv.values())) for _, _, sv in live]
    out['state_level'] = {'n_states_with_executed_candidates': len(live)}
    for pol in ('ranker', 'frozen_deepseek7b'):
        top = []
        for s, cands, _ in live:
            cs = [score[pol].get(key(s, c), -1e9) for c in cands if c['menu_name'] != 'simp?']
            top.append(max(cs) if cs else -1e9)
        top = np.array(top)
        first = np.array([sv[order(s, c, pol)[0]['menu_idx']] or 0 for s, c, sv in live], float)
        curve = []
        for q in (0, 0.25, 0.5, 0.6, 0.7, 0.8):
            keep = top >= np.quantile(top, q)
            curve.append({'skip_fraction': q, 'lean_checks': int(keep.sum()), 'tokens_saved': int(first[keep].sum()),
                          'pct_of_exhaustive': 100 * float(first[keep].sum()) / exhaustive})
        out['state_level'][pol] = {'auroc_has_acceptable_edit': auroc(y, top), 'one_check_skip_curve': curve}

    a.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    print(f"{len(states)} states, {with_edit} with an acceptable edit, exhaustive savings {exhaustive} tokens")
    print(f"{'policy':20s} {'b=1':>7s} {'b=2':>7s} {'b=4':>7s} {'b=8':>7s}  checks to try all")
    for pol in POLICIES:
        p = out['policies'][pol]
        print(f"{pol:20s} " + ' '.join(f"{p[b]['pct_of_exhaustive']:6.1f}%" for b in ('1', '2', '4', '8')) + f"  {p['all']['lean_checks']}")
    print('wrote', a.out)


if __name__ == '__main__':
    main()
