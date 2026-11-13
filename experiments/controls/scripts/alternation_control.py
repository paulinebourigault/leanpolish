#!/usr/bin/env python3
"""Matched alternating control: LeanPolish alternated with a frozen or a trained local editor.

Both editors run the same schedule, sampling and verification, with three sampling seeds each
(42, 1, 2). The final file of a chain is the output of the last LeanPolish round
(PutnamBench: `..._r3lp`, AxiomProver: `..._r2lp`). Metric: whole-corpus token reduction relative
to the original inputs (primary counter). Differences come with a 95% paired file bootstrap
(100,000 resamples), on per-file results averaged over seeds.

Reads the saved output files only (no GPU, no Lean).
Usage: REPLICATION_DATA=<unpacked replication tarball> python3 alternation_control.py
"""
import argparse, json, os, sys
from pathlib import Path
import numpy as np

ROOT = Path(os.environ.get('LEANPOLISH_ROOT', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens  # noqa: E402

SEEDS = (42, 1, 2)
FINAL_ROUND = {'putnam_verified': 'r3lp', 'putnam2025': 'r2lp'}
LABEL = {'putnam_verified': 'PutnamBench-19', 'putnam2025': 'AxiomProver-12'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=os.environ.get('REPLICATION_DATA'))
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[1] / 'results' / 'alternation_control.json')
    a = ap.parse_args()
    if not a.data:
        sys.exit('set REPLICATION_DATA or pass --data (unpacked experiments/replication.tar.gz)')
    data = Path(a.data)
    pb19 = [Path(l.strip()).stem for l in open(ROOT / 'experiments/metrics/file_lists/putnam_verified.txt') if l.strip()]

    def tokens(path, fallback):
        return count_lean_tokens(path.read_text()) if path.exists() else fallback

    out = {}
    for corpus, final in FINAL_ROUND.items():
        names = pb19 if corpus == 'putnam_verified' else sorted(p.stem for p in (data / 'inputs' / corpus).glob('*.lean'))
        orig = {n: count_lean_tokens((data / 'inputs' / corpus / f'{n}.lean').read_text()) for n in names}
        total = sum(orig.values())
        fixed = {n: tokens(data / 'lp_fixed_point' / corpus / f'{n}.lean', orig[n]) for n in names}
        chains = {(e, s): {n: tokens(data / 'alternation' / 'files' / corpus / f'alt_{e}_s{s}_{final}' / f'{n}.lean', orig[n]) for n in names}
                  for e in ('frozen', 'trained') for s in SEEDS}

        def red(v):
            return 100 * (total - sum(v[n] for n in names)) / total
        mean = {e: {n: float(np.mean([chains[(e, s)][n] for s in SEEDS])) for n in names} for e in ('frozen', 'trained')}
        ov = np.array([orig[n] for n in names], float)
        idx = np.random.default_rng(0).integers(0, len(names), (100_000, len(names)))

        def boot(base, new):
            x = np.array([base[n] for n in names])
            y = np.array([new[n] for n in names])
            g = 100 * (x[idx].sum(1) - y[idx].sum(1)) / ov[idx].sum(1)
            return {'gain_pp': float(100 * (x.sum() - y.sum()) / ov.sum()), 'ci95': [float(z) for z in np.percentile(g, [2.5, 97.5])]}
        row = {'n_files': len(names), 'symbolic_fixed_point': red(fixed)}
        for e in ('frozen', 'trained'):
            per_seed = [red(chains[(e, s)]) for s in SEEDS]
            row[e] = {'per_seed': dict(zip(map(str, SEEDS), per_seed)), 'mean': red(mean[e]), 'sd': float(np.std(per_seed, ddof=1))}
        row['frozen_minus_fixed_point'] = boot(fixed, mean['frozen'])
        row['trained_minus_fixed_point'] = boot(fixed, mean['trained'])
        row['trained_minus_frozen'] = boot(mean['frozen'], mean['trained'])
        out[LABEL[corpus]] = row
        print(f"{LABEL[corpus]:15s} fixed point {row['symbolic_fixed_point']:5.2f}  frozen {row['frozen']['mean']:5.2f} +- {row['frozen']['sd']:.2f}  "
              f"trained {row['trained']['mean']:5.2f} +- {row['trained']['sd']:.2f}  trained - frozen {row['trained_minus_frozen']['gain_pp']:+.2f} "
              f"[{row['trained_minus_frozen']['ci95'][0]:+.2f}, {row['trained_minus_frozen']['ci95'][1]:+.2f}]")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
