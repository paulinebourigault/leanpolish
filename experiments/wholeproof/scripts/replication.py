#!/usr/bin/env python3
"""Replication of the whole-proof rewriter: training seeds, decoding seeds, more problems,
a second base model, and sample budgets.

Reads only saved verdicts (no GPU, no Lean): for every run, the 16 samples per proof with their
fresh-process verdict. A sample counts if its verdict is `pass` and it is shorter than the input;
otherwise the input is kept. Metric: whole-corpus token reduction (ratio of sums, primary counter).

Runs (file names in `<data>/wholeproof/verdicts/`, d = decoding seed):
  frozen__c2__d{42,43,44}            frozen DeepSeek-Prover-V2-7B, theorem-level prompt
  s{42,1,2,3,4}__simple__d{42,43,44} trained DeepSeek rewriters (training seed), training prompt
  mfrest_*                           the same models on the 252 further miniF2F proofs (d42)
  qwenfrozen__c2__d{42,43}           frozen Qwen2.5-Coder-7B, theorem-level prompt
  qwenfrozensimple__simple__d42      frozen Qwen2.5-Coder-7B, training prompt (prompt control)
  qwens{42,1}__simple__d{42,43}      trained Qwen rewriters

Output (`--out`, default results/replication.json):
  seeds            trained vs frozen at 16 samples, per cohort (per-seed values, paired file bootstrap,
                   per-file sign test)
  further_minif2f  the 252 further miniF2F proofs and all 351
  second_model     Qwen2.5-Coder-7B, with the prompt control
  sample_budget    expected result with k of the 16 samples (k = 1, 2, 4, 8, 16), share of proofs
                   shortened, and an equal-budget mix of frozen and trained samples
  behaviour        per-sample behaviour (unchanged / verified shorter / median cut)
  file_checks      distinct candidates compiled per run

Usage: REPLICATION_DATA=<unpacked replication tarball> python3 replication.py
"""
import argparse, collections, json, math, os, re, sys
from math import comb
from pathlib import Path
import numpy as np

ROOT = Path(os.environ.get('LEANPOLISH_ROOT', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens  # noqa: E402

N = 16                     # samples per proof in every run
BUDGETS = [1, 2, 4, 8, 16]
B = 100_000                # bootstrap resamples
DEEPSEEK_SEEDS = ['42', '1', '2', '3', '4']
QWEN_SEEDS = ['42', '1']


def load(data):
    wp = data / 'wholeproof'
    items = {}
    for p in sorted((wp / 'items').glob('items_*_orig.jsonl')):
        for line in open(p):
            r = json.loads(line)
            items[r['id']] = r
    passing = {}
    for line in open(wp / 'verdicts' / 'compile_cache.jsonl'):
        r = json.loads(line)
        if r.get('verdict') == 'pass':
            passing[r['sha']] = count_lean_tokens(r['text'])
    orig = {i: count_lean_tokens(r['text']) for i, r in items.items()}
    runs, status = {}, {}
    for p in sorted((wp / 'verdicts').glob('*__d*.jsonl')):
        toks, stat = {}, {}
        for line in open(p):
            r = json.loads(line)
            if r['id'] not in items or r['id'] in toks:
                continue
            o = orig[r['id']]
            v = [min(o, passing[s['sha']]) if s.get('verdict') == 'pass' and s.get('sha') in passing else o
                 for s in r['samples'][:N]]
            toks[r['id']] = v + [o] * (N - len(v))
            stat[r['id']] = [(s.get('status'), s.get('sha')) for s in r['samples'][:N]]
        runs[p.stem], status[p.stem] = toks, stat
    return items, orig, runs, status


def cohorts(items, pb19):
    def ids(pred):
        return sorted(i for i, r in items.items() if pred(r['corpus'], r['name']))
    c = {'miniF2F-99': ids(lambda c, n: c == 'minif2f100' and not n.endswith('_linter')),
         'miniF2F-rest': ids(lambda c, n: c == 'minif2f_rest' and not n.endswith('_linter')),
         'PutnamBench-19': ids(lambda c, n: c == 'putnam_verified' and n in pb19),
         'PB-add': ids(lambda c, n: c == 'putnam_add')}
    c['miniF2F-all'] = sorted(c['miniF2F-99'] + c['miniF2F-rest'])
    c['PutnamBench-34'] = sorted(c['PutnamBench-19'] + c['PB-add'])
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=os.environ.get('REPLICATION_DATA'))
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'results' / 'replication.json')
    a = ap.parse_args()
    if not a.data:
        sys.exit('set REPLICATION_DATA or pass --data (unpacked experiments/replication.tar.gz)')
    data = Path(a.data)
    pb19 = {Path(l.strip()).stem for l in open(ROOT / 'experiments/metrics/file_lists/putnam_verified.txt') if l.strip()}
    items, orig, runs, status = load(data)
    coh = cohorts(items, pb19)
    # full miniF2F: join the miniF2F-99 and miniF2F-rest runs of the same model and decoding seed
    for n in list(runs):
        if n.startswith('mfrest_') and n[len('mfrest_'):] in runs:
            runs['mfall_' + n[len('mfrest_'):]] = {**runs[n[len('mfrest_'):]], **runs[n]}

    def tokens(ids):
        return np.array([orig[i] for i in ids], float)

    def red(v, ov):
        return float(100 * (ov.sum() - np.asarray(v).sum()) / ov.sum())

    def best16(run, ids):
        return np.array([min(runs[run][i]) for i in ids], float)

    def boot(frozen, trained, ov):
        """Paired file bootstrap of the reduction difference (trained - frozen), ratio of sums."""
        idx = np.random.default_rng(0).integers(0, len(ov), (B, len(ov)))
        g = 100 * (frozen[idx].sum(1) - trained[idx].sum(1)) / ov[idx].sum(1)
        return {'gain_pp': float(100 * (frozen.sum() - trained.sum()) / ov.sum()),
                'ci95': [float(x) for x in np.percentile(g, [2.5, 97.5])],
                'files_trained_better': int((trained < frozen).sum()), 'files_frozen_better': int((frozen < trained).sum())}

    def per_file(frozen, trained, ov):
        """Per-file view: sign test on files that differ, bootstrap of the mean per-file gain."""
        d = (frozen - trained) / ov * 100
        w, l = int((d > 1e-9).sum()), int((d < -1e-9).sum())
        n = w + l
        p = sum(math.comb(n, k) for k in range(max(w, l), n + 1)) / 2 ** n * 2 if n else 1.0
        bs = np.random.default_rng(0).choice(d, (B, len(d))).mean(1)
        return {'trained_better': w, 'frozen_better': l, 'sign_test_p_two_sided': min(1.0, p),
                'mean_per_file_gain_pp': float(d.mean()), 'ci95': [float(x) for x in np.percentile(bs, [2.5, 97.5])]}

    def compare(frozen_runs, trained_runs_by_seed, ids):
        ov = tokens(ids)
        fr = [best16(r, ids) for r in frozen_runs]
        F = np.mean(fr, axis=0)
        S = {s: np.mean([best16(r, ids) for r in rs], axis=0) for s, rs in trained_runs_by_seed.items()}
        T = np.mean(list(S.values()), axis=0)
        seeds = {s: red(v, ov) for s, v in S.items()}
        row = {'n_files': len(ids), 'frozen': red(F, ov), 'frozen_decodings': [red(x, ov) for x in fr],
               'frozen_decoding_sd': float(np.std([red(x, ov) for x in fr], ddof=1)) if len(fr) > 1 else None,
               'trained_per_seed': seeds, 'trained_mean': float(np.mean(list(seeds.values()))),
               'trained_sd': float(np.std(list(seeds.values()), ddof=1)) if len(seeds) > 1 else None,
               'seeds_above_frozen': int(sum(v > red(F, ov) for v in seeds.values())), 'n_seeds': len(seeds)}
        row.update(boot(F, T, ov))
        row['per_file'] = per_file(F, T, ov)
        return row

    out = {}
    # ---- training seeds x decoding seeds (16 samples)
    ds_frozen = [f'frozen__c2__d{d}' for d in (42, 43, 44)]
    ds_trained = {s: [f's{s}__simple__d{d}' for d in (42, 43, 44)] for s in DEEPSEEK_SEEDS}
    out['seeds'] = {c: compare(ds_frozen, ds_trained, coh[c])
                    for c in ('miniF2F-99', 'PutnamBench-19', 'PB-add', 'PutnamBench-34')}
    # ---- further miniF2F problems (decoding seed 42)
    out['further_minif2f'] = {
        'miniF2F-rest': compare(['mfrest_frozen__c2__d42'], {s: [f'mfrest_s{s}__simple__d42'] for s in DEEPSEEK_SEEDS}, coh['miniF2F-rest']),
        'miniF2F-all': compare(['mfall_frozen__c2__d42'], {s: [f'mfall_s{s}__simple__d42'] for s in DEEPSEEK_SEEDS}, coh['miniF2F-all'])}
    # ---- second base model, with the prompt control
    qw_frozen = [f'qwenfrozen__c2__d{d}' for d in (42, 43)]
    qw_trained = {s: [f'qwens{s}__simple__d{d}' for d in (42, 43)] for s in QWEN_SEEDS}
    out['second_model'] = {}
    for c in ('miniF2F-99', 'PutnamBench-19', 'PB-add', 'PutnamBench-34'):
        row = compare(qw_frozen, qw_trained, coh[c])
        row['frozen_training_prompt'] = red(best16('qwenfrozensimple__simple__d42', coh[c]), tokens(coh[c]))
        out['second_model'][c] = row

    # ---- sample budget: expectation over the choice of k of the 16 samples (exact)
    W = {k: np.array([comb(N - j, k - 1) / comb(N, k) for j in range(1, N + 1)]) for k in BUDGETS}

    def emin(v, k):                      # expected minimum of a random k-subset
        return float(np.dot(np.sort(np.array(v, float)), W[k]))

    def pshort(v, o, k):                 # P(at least one verified shorter sample among k)
        m = sum(x < o for x in v)
        return 1 - comb(N - m, k) / comb(N, k)

    def emix(vf, vt, h):                 # expected minimum of h frozen and h trained samples
        x, y = np.sort(np.array(vf, float)), np.sort(np.array(vt, float))
        return float((np.minimum.outer(x, y) * np.outer(W[h], W[h])).sum())

    groups = {'DeepSeek': (r'(mfrest_|mfall_)?frozen__c2__d(4[234])', r'(mfrest_|mfall_)?s(\d+)__simple__d(4[234])', 2),
              'Qwen': (r'qwenfrozen__c2__d(4[23])', r'qwens(\d+)__simple__d(4[23])', 1)}
    order = ['miniF2F-99', 'miniF2F-rest', 'PutnamBench-19', 'PB-add', 'miniF2F-all', 'PutnamBench-34']
    rng = np.random.default_rng(0)
    out['sample_budget'] = {}
    for g, (fp, tp, sg) in groups.items():
        fr = [n for n in runs if re.fullmatch(fp, n)]
        tr = collections.defaultdict(list)
        for n in runs:
            m = re.fullmatch(tp, n)
            if m:
                tr[m.group(sg)].append(n)
        for c in order:
            ids = coh[c]
            use = (lambda n: n.startswith('mfall_')) if c == 'miniF2F-all' else (lambda n: not n.startswith('mfall_'))
            frc = sorted(n for n in fr if use(n) and all(i in runs[n] for i in ids))
            trc = {s: sorted(n for n in ns if use(n) and all(i in runs[n] for i in ids)) for s, ns in tr.items()}
            trc = {s: ns for s, ns in trc.items() if ns}
            if not frc or not trc:
                continue
            ov = tokens(ids)
            idx = rng.integers(0, len(ids), (B, len(ids)))

            def ci(x, y):
                return [float(z) for z in np.percentile(100 * (x[idx].sum(1) - y[idx].sum(1)) / ov[idx].sum(1), [2.5, 97.5])]
            res = {'n_files': len(ids), 'frozen_runs': len(frc), 'trained_seeds': len(trc), 'k': {}}
            for k in BUDGETS:
                F = np.array([np.mean([emin(runs[n][i], k) for n in frc]) for i in ids])
                S = {s: np.array([np.mean([emin(runs[n][i], k) for n in ns]) for i in ids]) for s, ns in trc.items()}
                T = np.mean(list(S.values()), axis=0)
                seeds = {s: red(v, ov) for s, v in S.items()}
                r = {'frozen': red(F, ov), 'trained_mean': float(np.mean(list(seeds.values()))),
                     'trained_sd': float(np.std(list(seeds.values()), ddof=1)) if len(seeds) > 1 else None,
                     'seeds_above_frozen': int(sum(v > red(F, ov) for v in seeds.values())),
                     'gain_pp': red(T, ov) - red(F, ov), 'ci95': ci(F, T),
                     'shortened_frozen': float(np.mean([np.mean([pshort(runs[n][i], orig[i], k) for i in ids]) for n in frc])),
                     'shortened_trained': float(np.mean([np.mean([pshort(runs[n][i], orig[i], k) for i in ids])
                                                         for ns in trc.values() for n in ns]))}
                if k >= 2:                # equal budget: k/2 frozen + k/2 trained samples, same decoding seed
                    P = collections.defaultdict(list)
                    for ns in trc.values():
                        for n in ns:
                            fn = [x for x in frc if x.endswith('__d' + n.split('__d')[-1])]
                            if fn:
                                for i in ids:
                                    P[i].append(emix(runs[fn[0]][i], runs[n][i], k // 2))
                    if P:
                        M = np.array([np.mean(P[i]) for i in ids])
                        r['mix'] = red(M, ov)
                        r['mix_minus_trained'] = {'gain_pp': red(M, ov) - red(T, ov), 'ci95': ci(T, M)}
                        r['mix_minus_frozen'] = {'gain_pp': red(M, ov) - red(F, ov), 'ci95': ci(F, M)}
                res['k'][k] = r
            out['sample_budget'][f'{g}|{c}'] = res

    # ---- per-sample behaviour and compiled candidates per run
    beh_groups = {'DeepSeek frozen': r'frozen__c2__d4[234]', 'DeepSeek trained': r's\d+__simple__d4[234]',
                  'Qwen frozen': r'qwenfrozen__c2__d4[23]', 'Qwen frozen, training prompt': r'qwenfrozensimple__simple__d42',
                  'Qwen trained': r'qwens\d+__simple__d4[23]'}
    out['behaviour'], out['file_checks'] = {}, {}
    for name, pat in beh_groups.items():
        names = sorted(n for n in runs if re.fullmatch(pat, n))
        for c in ('miniF2F-99', 'PutnamBench-34'):
            n = ident = short = 0
            cuts, cut_tokens = [], []
            for run in names:
                for i in coh[c]:
                    o = orig[i]
                    for (st, _), t in zip(status[run][i], runs[run][i]):
                        n += 1
                        ident += st == 'identical'
                        if t < o:
                            short += 1
                            cuts.append(1 - t / o)
                            cut_tokens.append(o - t)
            out['behaviour'][f'{name}|{c}'] = {'runs': len(names), 'samples': n, 'unchanged': ident / n, 'verified_shorter': short / n,
                                               'median_cut_pct': 100 * float(np.median(cuts)) if cuts else None,
                                               'median_tokens_cut': float(np.median(cut_tokens)) if cut_tokens else None}
        if name in ('DeepSeek frozen', 'DeepSeek trained'):
            for c in ('miniF2F-99', 'PutnamBench-19'):
                k = [len({(i, sha) for i in coh[c] for st, sha in status[run][i] if st == 'compile' and sha}) for run in names]
                out['file_checks'][f'{name}|{c}'] = {'runs': len(k), 'mean_per_run': float(np.mean(k))}

    a.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    for c, r in out['seeds'].items():
        print(f"{c:16s} frozen {r['frozen']:5.2f}  trained {r['trained_mean']:5.2f} +- {r['trained_sd']:.2f}  "
              f"gain {r['gain_pp']:+.2f} [{r['ci95'][0]:+.2f}, {r['ci95'][1]:+.2f}]  seeds above frozen {r['seeds_above_frozen']}/{r['n_seeds']}")
    r = out['sample_budget']['DeepSeek|miniF2F-all']['k']
    for k in BUDGETS:
        print(f"all 351 miniF2F, k={k:2d}: frozen {r[k]['frozen']:5.2f}  trained {r[k]['trained_mean']:5.2f}  "
              f"gain {r[k]['gain_pp']:+.2f} [{r[k]['ci95'][0]:+.2f}, {r[k]['ci95'][1]:+.2f}]")
    print('wrote', a.out)


if __name__ == '__main__':
    main()
