# SFT seed robustness: greedy valid-and-shorter on the 1,406 original held-out teacher sites

Protocol, identical for every seed: same data (sft_train.jsonl, 17,099 rows) and recipe (train_sft_lora.py: LoRA r32/a64, 2 epochs, lr 1e-4); only `--seed` changes. Greedy decoding, max 256 new tokens. A candidate counts as valid-and-shorter iff it is strictly shorter under count_appL AND one of the following holds: (a) it equals the teacher's kernel-verified reference edit; (b) the identical candidate (key sha256(file:start:end:replacement)) has kernel_verdict=pass in the archived verification; (c) it passes a fresh `lake env lean` splice verification run here (verify_full.py; all otherwise-unknown candidates were verified). 

## DeepSeek-Prover-V2-7B SFT

| Corpus / family | seed 42 | seed 1 | seed 2 | mean ± sd | unverified (all seeds) |
|---|---:|---:|---:|---:|---:|
| **minif2f** (n=1184) | 87.0 | 86.7 | 86.9 | 86.9 ± 0.1 | 0 |
| &nbsp;&nbsp;deletion (n=436) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=747) | 79.5 | 79.1 | 79.4 | 79.3 ± 0.2 | 0 |
| **putnam_verified** (n=80) | 86.2 | 85.0 | 86.2 | 85.8 ± 0.7 | 0 |
| &nbsp;&nbsp;deletion (n=37) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=43) | 74.4 | 72.1 | 74.4 | 73.6 ± 1.3 | 0 |
| **putnam2025_per_file** (n=142) | 79.6 | 79.6 | 79.6 | 79.6 ± 0.0 | 0 |
| &nbsp;&nbsp;deletion (n=85) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=57) | 49.1 | 49.1 | 49.1 | 49.1 ± 0.0 | 0 |


## Qwen2.5-Coder-7B-Instruct SFT

| Corpus / family | seed 42 | seed 1 | seed 2 | mean ± sd | unverified (all seeds) |
|---|---:|---:|---:|---:|---:|
| **minif2f** (n=1184) | 84.6 | 84.9 | 84.5 | 84.7 ± 0.2 | 0 |
| &nbsp;&nbsp;deletion (n=436) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=747) | 75.8 | 76.2 | 75.5 | 75.8 ± 0.3 | 0 |
| **putnam_verified** (n=80) | 81.2 | 83.8 | 81.2 | 82.1 ± 1.4 | 0 |
| &nbsp;&nbsp;deletion (n=37) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=43) | 65.1 | 69.8 | 65.1 | 66.7 ± 2.7 | 0 |
| **putnam2025_per_file** (n=142) | 76.8 | 76.8 | 77.5 | 77.0 ± 0.4 | 0 |
| &nbsp;&nbsp;deletion (n=85) | 100.0 | 100.0 | 100.0 | 100.0 ± 0.0 | 0 |
| &nbsp;&nbsp;tactic (n=57) | 42.1 | 42.1 | 43.9 | 42.7 ± 1.0 | 0 |

sd = sample standard deviation across the listed seeds. Per-seed JSONs: seeds/seed<k>_<model>.json; fresh verdicts: seeds/unk_*.verdicts.jsonl.
