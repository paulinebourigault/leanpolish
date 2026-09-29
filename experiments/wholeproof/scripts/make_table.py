#!/usr/bin/env python3
"""Render results/metrics.json as a markdown table (stdout)."""
import json
from pathlib import Path
W = Path(__file__).resolve().parent.parent  # experiment folder
M = json.load(open(W / 'results' / 'metrics.json'))
LAB = {'frozen_simple': 'Frozen, SFT prompt (whole file)', 'frozen_c2prompt': 'Frozen, C2 prompt (theorem, spliced)',
       'trained': 'LeanPolish-SFT optimizer', 'leanpolish_then_trained': 'LeanPolish, then SFT optimizer'}
print('| Corpus | Method | k | **Red. A** | Red. B (appL) | files improved (A) | gen tokens | GPU-s | unique compiles | compile pass | samples verified |')
print('|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
for c, r in M.items():
    lp = r['leanpolish_alone']
    print(f"| {c} ({r['n_files']} files; A {r['orig_tokens']['A']:,} tok) | LeanPolish alone | - | **{lp['red_A_pct']:.2f}%** | {lp['red_B_pct']:.2f}% | {lp['files_improved_A']} | - | CPU only | - | - | - |")
    for key, lab in LAB.items():
        for k in (4, 16):
            x = r.get(key, {}).get(f'k{k}')
            if not x:
                continue
            cp = f"{100 * x['compile_pass_frac']:.0f}%" if x['compile_pass_frac'] is not None else '-'
            print(f"| {c} | {lab} | {k} | **{x['red_A_pct']:.2f}%** | {x['red_B_pct']:.2f}% | "
                  f"{x['files_improved_vs_original_A']} | {x['generated_tokens']:,} | {x['gpu_s']:.0f} | {x['unique_compiles']} | {cp} | "
                  f"{100 * x['frac_samples_verified']:.0f}% |")
    for k, v in r.get('comparisons', {}).items():
        print(f"| {c} | per-file min(SFT optimizer, LeanPolish) | {k[1:]} | **{v['min_trained_LP_red_A_pct']:.2f}%** | | "
              f"SFT<LP on {v['trained_beats_LP_files_A']}, LP<SFT on {v['LP_beats_trained_files_A']} | | | | | |")
