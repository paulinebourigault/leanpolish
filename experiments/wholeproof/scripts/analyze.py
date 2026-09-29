#!/usr/bin/env python3
"""Aggregate whole-proof results into metrics.json (both counters, unified file sets).

Counters: A = Lean-aware comment-skipping count_lean_tokens (leanpolish/lean_counter.py,
the port of LeanPolish's countLeanTokens; primary), B = count_appL (secondary).
File sets (experiments/metrics/file_lists): miniF2F-100 = the hybrid-controls seed-0 sample
minus the `_linter` artifact (99 files); PutnamBench-verified = the 19 listed files (24 minus 2
comment-only, 3 baseline-crash); Putnam2025 = 12 solution.lean files.
Reduction = sum_f (tok(original_f) - tok(result_f)) / sum_f tok(original_f) over ALL files of the set;
result_f = the candidate with the fewest tokens (under that counter) among VERIFIED first-k samples,
else the input (original file, or the LeanPolish output for the post-symbolic condition).
Cost: generated tokens of the first k samples; unique compiles among gated first-k candidates;
pass fraction = unique passing / unique compiled; GPU-s = this corpus' generated-token share of its
run's wall time (load + generate; k<n pro-rata of generate time).
"""
import json, sys, collections
from pathlib import Path
import os
_HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
# WORK_DIR holds data/, gens/, verdicts/ (from the dataset's experiments/wholeproof tarball or a rerun)
W = Path(os.environ.get('WORK_DIR', _HERE.parent))
sys.path[:0] = [str(_HERE), str(ROOT / 'leanpolish')]
from retokenize_appendixL import count_appL
from lean_counter import count_lean_tokens

CNT = {'A': count_lean_tokens, 'B': count_appL}
FL = ROOT / 'experiments' / 'metrics' / 'file_lists'
SETS = {
    'minif2f100': ('miniF2F-100', lambda n: not n.endswith('_linter')),
    'putnam_verified': ('PutnamBench-verified', lambda n, S={Path(l.strip()).stem for l in open(FL / 'putnam_verified.txt')}: n in S),
    'putnam2025': ('Putnam2025-AxiomProver', lambda n: True),
}
CONDS = [('frozen_simple', 'frozen_simple_orig', 'orig'), ('frozen_c2prompt', 'frozen_c2_orig', 'orig'),
         ('trained', 'trained_orig', 'orig'), ('leanpolish_then_trained', 'trained_base', 'base')]
GRP = {'minif2f100': ['mfpb'], 'putnam_verified': ['mfpb'], 'putnam2025': ['axiom4']}


def load_items(c, v):
    return {json.loads(l)['name']: json.loads(l)['text'] for l in open(W / f'data/items_{c}_{v}.jsonl')}


def main():
    cache = {}
    for l in open(W / 'verdicts/compile_cache.jsonl'):
        r = json.loads(l)
        if r['verdict'] == 'pass':
            cache[r['sha']] = r['text']
    tokc = {}

    def tok(ctr, text):
        key = (ctr, hash(text))
        if key not in tokc:
            tokc[key] = CNT[ctr](text)
        return tokc[key]
    M = {}
    for c, (cname, keep) in SETS.items():
        orig, base = load_items(c, 'orig'), load_items(c, 'base')
        names = [n for n in orig if keep(n)]
        res = {'n_files': len(names), 'files': names}
        O = {ct: {n: tok(ct, orig[n]) for n in names} for ct in CNT}
        B = {ct: {n: tok(ct, base[n]) for n in names} for ct in CNT}
        den = {ct: sum(O[ct].values()) for ct in CNT}
        res['orig_tokens'] = den
        res['leanpolish_alone'] = {f'red_{ct}_pct': round(100 * (den[ct] - sum(B[ct].values())) / den[ct], 2) for ct in CNT}
        res['leanpolish_alone']['files_improved_A'] = sum(1 for n in names if B['A'][n] < O['A'][n])
        best_by = {}
        for label, gname, var in CONDS:
            for grp in GRP[c]:
                vf = W / f'verdicts/{gname}_{grp}.jsonl'
                if vf.exists():
                    break
            else:
                continue
            cost = json.load(open(W / f'gens/{gname}_{grp}.cost.json'))
            rows = {r['id'].split('/')[-1]: r for r in map(json.loads, open(vf)) if r['id'].startswith(c + '/')}
            allrows_gen = sum(sum(r['gen_tokens']) for r in map(json.loads, open(vf)))
            inp = O if var == 'orig' else B
            out = {'input': var, 'n_generated': sum(1 for n in names if n in rows),
                   'not_generated_too_long': [n for n in names if n not in rows]}
            for k in (4, 16):
                if k > cost['n'] or any(r.get('max_samples', 16) < k for r in rows.values()):
                    continue
                best = {ct: {} for ct in CNT}
                gt, comp, passed, stat = 0, set(), set(), collections.Counter()
                for n in names:
                    r = rows.get(n)
                    texts = []
                    if r:
                        gt += sum(r['gen_tokens'][:k])
                        for s in r['samples'][:k]:
                            stat[s['status'] if s['status'] != 'compile' else 'compiled_' + s['verdict']] += 1
                            if s['status'] == 'compile':
                                comp.add(s['sha'])
                                if s['verdict'] == 'pass':
                                    passed.add(s['sha']); texts.append(cache[s['sha']])
                    for ct in CNT:
                        best[ct][n] = min([inp[ct][n]] + [tok(ct, t) for t in texts])
                for ct in CNT:
                    best_by[(label, k, ct)] = best[ct]
                share = sum(sum(rows[n]['gen_tokens']) for n in names if n in rows) / max(1, allrows_gen)
                kk = min(k, cost['n'])
                nsamp = sum(stat.values())
                x = {f'red_{ct}_pct': round(100 * (den[ct] - sum(best[ct].values())) / den[ct], 2) for ct in CNT}
                x.update({
                    'saved_A': den['A'] - sum(best['A'].values()),
                    'files_improved_vs_original_A': sum(1 for n in names if best['A'][n] < O['A'][n]),
                    'files_improved_vs_input_A': sum(1 for n in names if best['A'][n] < inp['A'][n]),
                    'generated_tokens': gt,
                    'gpu_s': round(share * (cost['load_s'] + cost['generate_s'] * kk / cost['n']), 1),
                    'unique_compiles': len(comp), 'unique_pass': len(passed),
                    'compile_pass_frac': round(len(passed) / len(comp), 3) if comp else None,
                    'samples': nsamp, 'frac_samples_verified': round(stat['compiled_pass'] / nsamp, 3) if nsamp else None,
                    'sample_status': dict(stat)})
                out[f'k{k}'] = x
            res[label] = out
        comp_ = {}
        for k in (4, 16):
            if ('trained', k, 'A') in best_by:
                t = best_by[('trained', k, 'A')]
                comp_[f'k{k}'] = {'trained_beats_LP_files_A': sum(1 for n in names if t[n] < B['A'][n]),
                                  'LP_beats_trained_files_A': sum(1 for n in names if B['A'][n] < t[n]),
                                  'min_trained_LP_red_A_pct': round(100 * (den['A'] - sum(min(t[n], B['A'][n]) for n in names)) / den['A'], 2)}
        res['comparisons'] = comp_
        M[cname] = res
    json.dump(M, open(Path(os.environ.get('OUT_DIR', _HERE.parent / 'results')) / 'metrics.json', 'w'), indent=1)


if __name__ == '__main__':
    main()
