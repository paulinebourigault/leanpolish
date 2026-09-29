#!/usr/bin/env python3
"""Render the seed-robustness markdown table from results/seeds/*.json (stdout)."""
import json, statistics, glob, os
from pathlib import Path
# Reads seed*_{deepseek,qwen}.json (written by seeds_eval.py) from SEEDS_DIR (default ../results/seeds)
D = Path(os.environ.get('SEEDS_DIR', Path(__file__).resolve().parents[1] / 'results' / 'seeds'))
rows = ['minif2f', 'putnam_verified', 'putnam2025_per_file']
fams = ['deletion', 'tactic']
L = ['# SFT seed robustness: greedy valid-and-shorter on the 1,406 original held-out teacher sites', '',
     'Protocol, identical for every seed: same data (sft_train.jsonl, 17,099 rows) and recipe (train_sft_lora.py: LoRA r32/a64, 2 epochs, lr 1e-4); only `--seed` changes. '
     'Greedy decoding, max 256 new tokens. A candidate counts as valid-and-shorter iff it is strictly shorter under count_appL AND one of the following holds: (a) it equals the teacher\'s kernel-verified reference edit; '
     '(b) the identical candidate (key sha256(file:start:end:replacement)) has kernel_verdict=pass in the archived verification; '
     '(c) it passes a fresh `lake env lean` splice verification run here (verify_full.py; all otherwise-unknown candidates were verified). '
     '']
for model in ('deepseek', 'qwen'):
    seeds = {}
    for p in sorted(D.glob(f'seed*_{model}.json')):
        s = p.stem.split('_')[0].replace('seed', '')
        seeds[s] = json.load(open(p))
    if not seeds: continue
    order = sorted(seeds, key=lambda x: {'42': 0}.get(x, int(x) + 1))
    L += [f'## {"DeepSeek-Prover-V2-7B" if model == "deepseek" else "Qwen2.5-Coder-7B-Instruct"} SFT', '',
          '| Corpus / family | ' + ' | '.join(f'seed {s}' for s in order) + ' | mean ± sd | unverified (all seeds) |',
          '|---|' + '---:|' * (len(order) + 2)]
    for c in rows:
        for key in [c] + [f'{c}/{f}' for f in fams]:
            if key not in seeds[order[0]]: continue
            vals = [seeds[s][key]['vs_pct'] for s in order if key in seeds[s]]
            unk = sum(seeds[s][key].get('unknown', 0) for s in order if key in seeds[s])
            n = seeds[order[0]][key]['sites']
            ms = f'{statistics.mean(vals):.1f} ± {statistics.stdev(vals):.1f}' if len(vals) > 1 else f'{vals[0]:.1f}'
            lab = f'**{c}** (n={n})' if '/' not in key else f'&nbsp;&nbsp;{key.split("/")[1]} (n={n})'
            L.append(f'| {lab} | ' + ' | '.join(f'{v:.1f}' for v in vals) + f' | {ms} | {unk} |')
    L.append('')
L.append('sd = sample standard deviation across the listed seeds. Per-seed JSONs: seeds/seed<k>_<model>.json; fresh verdicts: seeds/unk_*.verdicts.jsonl.')
(D / 'RESULTS_seeds.md').write_text('\n'.join(L) + '\n')
print('\n'.join(L))
