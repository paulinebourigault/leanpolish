#!/usr/bin/env python3
"""LeanPolish and AXLE's `simplify_theorems` on the same inputs: reduction table.

Conditions, all measured against the original inputs (whole-corpus token reduction, primary counter):
  LeanPolish fixed point, AXLE, LeanPolish fixed point -> AXLE, AXLE -> LeanPolish fixed point.
A file with no verified output in a condition keeps its input for that condition.

Reads the saved output files only (no Lean, no AXLE call).
Usage: REPLICATION_DATA=<unpacked replication tarball> python3 compare.py
"""
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(os.environ.get('LEANPOLISH_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens  # noqa: E402

LABEL = {'minif2f': 'miniF2F-99', 'putnam_verified': 'PutnamBench-19', 'putnam2025': 'AxiomProver-12'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', type=Path, default=os.environ.get('REPLICATION_DATA'))
    ap.add_argument('--out', type=Path, default=Path(__file__).resolve().parent / 'results' / 'table.json')
    a = ap.parse_args()
    if not a.data:
        sys.exit('set REPLICATION_DATA or pass --data (unpacked experiments/replication.tar.gz)')
    data = Path(a.data)
    pb19 = {Path(l.strip()).stem for l in open(ROOT / 'experiments/metrics/file_lists/putnam_verified.txt') if l.strip()}
    keep = {'minif2f': lambda n: not n.endswith('_linter'), 'putnam_verified': lambda n: n in pb19, 'putnam2025': lambda n: True}

    def tokens(path, fallback):
        return count_lean_tokens(path.read_text()) if path.exists() else fallback

    out = {}
    for corpus, label in LABEL.items():
        names = sorted(p.stem for p in (data / 'inputs' / corpus).glob('*.lean') if keep[corpus](p.stem))
        orig = {n: count_lean_tokens((data / 'inputs' / corpus / f'{n}.lean').read_text()) for n in names}
        total = sum(orig.values())
        lp = {n: tokens(data / 'lp_fixed_point' / corpus / f'{n}.lean', orig[n]) for n in names}
        axle = {n: tokens(data / 'axle' / 'outputs' / 'original' / corpus / f'{n}.lean', orig[n]) for n in names}
        lp_axle = {n: tokens(data / 'axle' / 'outputs' / 'lp_fixed_point' / corpus / f'{n}.lean', lp[n]) for n in names}
        # where AXLE left a file unchanged, AXLE -> LeanPolish is LeanPolish on the original
        axle_lp = {n: tokens(data / 'axle' / 'then_leanpolish' / corpus / f'{n}.lean', lp[n] if axle[n] == orig[n] else axle[n])
                   for n in names}

        def red(v):
            return 100 * (total - sum(v.values())) / total
        # AXLE's own report: responses that say the simplification failed and was reverted
        failed = sum('Reverting to last valid iteration' in p.read_text()
                     for p in (data / 'axle' / 'raw' / 'original' / corpus).glob('*.json') if keep[corpus](p.stem))
        out[label] = {'n_files': len(names), 'original_tokens': total,
                      'LeanPolish fixed point': red(lp), 'AXLE': red(axle),
                      'LeanPolish fixed point -> AXLE': red(lp_axle), 'AXLE -> LeanPolish fixed point': red(axle_lp),
                      'files_LeanPolish_shorter': sum(lp[n] < axle[n] for n in names), 'files_AXLE_shorter': sum(axle[n] < lp[n] for n in names),
                      'AXLE_reported_failures': failed}
        print(label, {k: round(v, 2) if isinstance(v, float) else v for k, v in out[label].items()})
    a.out.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(a.out, 'w'), indent=1)
    print('wrote', a.out)


if __name__ == '__main__':
    main()
