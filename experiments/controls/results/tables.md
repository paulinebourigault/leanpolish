
### Whole-file token reduction, % of ALL original tokens -- countLeanTokens (Lean-aware, comment-skipping; PRIMARY)

| Condition | PB-verified (24 files) | PB-verified, paper 19 (19 files) | Putnam 2025 AxiomProver (12 files) | miniF2F-100 (100 files) |
|---|---:|---:|---:|---:|
| Original | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) |
| LeanPolish alone (paper run, = hybrid F1) | 3.97 (1,359; 16f) | 6.14 (1,359; 16f) | 1.31 (1,746; 10f) | 19.81 (7,614; 91f) |
| LeanPolish alone, clean rerun | 7.69 (2,635; 18f) | 11.91 (2,635; 18f) | 1.41 (1,888; 9f) | 20.68 (7,950; 91f) |
| Hybrid, SFT editor, greedy | 5.74 (1,965; 19f) | 8.88 (1,965; 19f) | 3.42 (4,566; 12f) | 22.11 (8,497; 97f) |
| Hybrid, SFT editor, greedy+4 samples | 5.82 (1,994; 19f) | 9.02 (1,994; 19f) | 3.65 (4,879; 12f) | 22.20 (8,532; 97f) |
| Hybrid, SFT editor, +quality filter | 5.19 (1,779; 19f) | 8.04 (1,779; 19f) | 2.38 (3,186; 12f) | 21.16 (8,131; 92f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy | 5.55 (1,903; 18f) | 8.61 (1,903; 18f) | 3.17 (4,237; 12f) | 22.06 (8,480; 94f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy+4 | 6.01 (2,059; 18f) | 9.31 (2,059; 18f) | 3.66 (4,898; 12f) | 22.91 (8,806; 95f) |
| C1 frozen hybrid, DeepSeek few-shot, +quality filter | 6.00 (2,057; 18f) | 9.30 (2,057; 18f) | 3.66 (4,890; 12f) | 22.91 (8,803; 95f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=4 | 0.79 (272; 4f) | 1.23 (272; 4f) | 1.04 (1,388; 11f) | 10.75 (4,130; 29f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=16 | 1.78 (611; 6f) | 2.76 (611; 6f) | — | 13.08 (5,027; 39f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=4 | 4.21 (1,443; 16f) | 6.53 (1,443; 16f) | 2.34 (3,129; 12f) | 23.47 (9,020; 95f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=16 | 5.09 (1,743; 16f) | 7.88 (1,743; 16f) | — | 28.04 (10,775; 95f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=4 | 4.83 (1,655; 16f) | 7.48 (1,655; 16f) | 2.53 (3,377; 12f) | 26.95 (10,359; 93f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=16 | 6.69 (2,291; 17f) | 10.36 (2,291; 17f) | — | 28.39 (10,912; 95f) |
| C2 LLM-only, Qwen2.5-Coder-32B, k=4 | 0.32 (111; 1f) | 0.50 (111; 1f) | 1.84 (2,459; 12f) | — |
| C2 LLM-only, Qwen2.5-Coder-32B, k=16 | 1.34 (458; 3f) | 2.07 (458; 3f) | — | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=4 | 4.87 (1,668; 16f) | 7.54 (1,668; 16f) | 3.08 (4,118; 12f) | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=16 | 5.02 (1,720; 16f) | 7.78 (1,720; 16f) | — | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=4 | 4.27 (1,462; 16f) | 6.61 (1,462; 16f) | 3.35 (4,472; 12f) | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=16 | 5.26 (1,802; 16f) | 8.15 (1,802; 16f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=4 | 8.17 (2,800; 18f) | 12.66 (2,800; 18f) | — | 23.29 (8,951; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=16 | 8.29 (2,841; 18f) | 12.85 (2,841; 18f) | — | 27.53 (10,580; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=4 | 8.59 (2,944; 18f) | 13.31 (2,944; 18f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=16 | 8.74 (2,996; 18f) | 13.55 (2,996; 18f) | — | — |
| C3 round 1: LeanPolish on hybrid output | 10.82 (3,709; 19f) | 16.77 (3,709; 19f) | 4.69 (6,269; 12f) | — |
| C3 round 1: + SFT editor | 10.90 (3,734; 19f) | 16.88 (3,734; 19f) | 4.76 (6,364; 12f) | — |
| C3 round 2: LeanPolish | 12.13 (4,155; 19f) | 18.79 (4,155; 19f) | 5.05 (6,751; 12f) | — |
| C3 round 2: + SFT editor | 12.13 (4,155; 19f) | 18.79 (4,155; 19f) | — | — |
| C3 round 3: LeanPolish | 13.07 (4,479; 19f) | 20.25 (4,479; 19f) | — | — |

Original tokens (this counter): putnam_verified 34,265, putnam_verified19 22,116, putnam2025 133,686, minif2f100 38,433

### Whole-file token reduction, % of ALL original tokens -- appL (counts comments)

| Condition | PB-verified (24 files) | PB-verified, paper 19 (19 files) | Putnam 2025 AxiomProver (12 files) | miniF2F-100 (100 files) |
|---|---:|---:|---:|---:|
| Original | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) |
| LeanPolish alone (paper run, = hybrid F1) | 3.40 (1,338; 16f) | 5.80 (1,338; 16f) | 1.06 (1,458; 10f) | 20.31 (7,778; 91f) |
| LeanPolish alone, clean rerun | 6.59 (2,594; 18f) | 11.25 (2,594; 18f) | 1.15 (1,582; 9f) | 21.17 (8,105; 91f) |
| Hybrid, SFT editor, greedy | 4.77 (1,876; 19f) | 8.14 (1,876; 19f) | 2.58 (3,561; 12f) | 22.27 (8,529; 97f) |
| Hybrid, SFT editor, greedy+4 samples | 4.84 (1,905; 19f) | 8.26 (1,905; 19f) | 2.77 (3,813; 12f) | 22.35 (8,558; 97f) |
| Hybrid, SFT editor, +quality filter | 4.30 (1,690; 19f) | 7.33 (1,690; 19f) | 1.84 (2,530; 12f) | 21.37 (8,181; 92f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy | 4.75 (1,868; 18f) | 8.10 (1,868; 18f) | 2.54 (3,500; 12f) | 22.49 (8,610; 94f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy+4 | 5.15 (2,024; 18f) | 8.78 (2,024; 18f) | 2.92 (4,024; 12f) | 23.26 (8,906; 95f) |
| C1 frozen hybrid, DeepSeek few-shot, +quality filter | 5.14 (2,022; 18f) | 8.77 (2,022; 18f) | 2.91 (4,016; 12f) | 23.25 (8,903; 95f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=4 | 1.10 (434; 5f) | 1.88 (434; 5f) | 1.01 (1,398; 12f) | 13.07 (5,004; 35f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=16 | 2.27 (893; 8f) | 3.87 (893; 8f) | — | 15.61 (5,976; 43f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=4 | 3.62 (1,422; 16f) | 6.17 (1,422; 16f) | 2.07 (2,853; 12f) | 25.05 (9,591; 95f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=16 | 4.62 (1,819; 17f) | 7.89 (1,819; 17f) | — | 30.77 (11,783; 95f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=4 | 4.63 (1,823; 16f) | 7.91 (1,823; 16f) | 2.22 (3,065; 12f) | 29.19 (11,176; 94f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=16 | 6.51 (2,561; 17f) | 11.11 (2,561; 17f) | — | 30.80 (11,792; 95f) |
| C2 LLM-only, Qwen2.5-Coder-32B, k=4 | 0.28 (111; 1f) | 0.48 (111; 1f) | 1.63 (2,250; 12f) | — |
| C2 LLM-only, Qwen2.5-Coder-32B, k=16 | 1.29 (508; 3f) | 2.20 (508; 3f) | — | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=4 | 4.62 (1,817; 16f) | 7.88 (1,817; 16f) | 2.65 (3,657; 12f) | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=16 | 4.76 (1,871; 16f) | 8.11 (1,871; 16f) | — | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=4 | 3.66 (1,441; 16f) | 6.25 (1,441; 16f) | 2.85 (3,931; 12f) | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=16 | 4.66 (1,833; 16f) | 7.95 (1,833; 16f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=4 | 7.01 (2,759; 18f) | 11.96 (2,759; 18f) | — | 24.91 (9,540; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=16 | 7.41 (2,914; 18f) | 12.64 (2,914; 18f) | — | 30.38 (11,634; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=4 | 7.81 (3,073; 18f) | 13.33 (3,073; 18f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=16 | 7.95 (3,127; 18f) | 13.56 (3,127; 18f) | — | — |
| C3 round 1: LeanPolish on hybrid output | 9.17 (3,606; 19f) | 15.64 (3,606; 19f) | 3.69 (5,079; 12f) | — |
| C3 round 1: + SFT editor | 9.23 (3,631; 19f) | 15.75 (3,631; 19f) | 3.75 (5,161; 12f) | — |
| C3 round 2: LeanPolish | 10.30 (4,050; 19f) | 17.56 (4,050; 19f) | 4.00 (5,506; 12f) | — |
| C3 round 2: + SFT editor | 10.30 (4,050; 19f) | 17.56 (4,050; 19f) | — | — |
| C3 round 3: LeanPolish | 11.12 (4,374; 19f) | 18.97 (4,374; 19f) | — | — |

Original tokens (this counter): putnam_verified 39,330, putnam_verified19 23,059, putnam2025 137,805, minif2f100 38,290

### Whole-file token reduction, % of ALL original tokens -- appL on comment-stripped text

| Condition | PB-verified (24 files) | PB-verified, paper 19 (19 files) | Putnam 2025 AxiomProver (12 files) | miniF2F-100 (100 files) |
|---|---:|---:|---:|---:|
| Original | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) | 0.00 (0; 0f) |
| LeanPolish alone (paper run, = hybrid F1) | 4.06 (1,338; 16f) | 6.15 (1,338; 16f) | 1.20 (1,458; 10f) | 20.44 (7,365; 91f) |
| LeanPolish alone, clean rerun | 7.88 (2,594; 18f) | 11.93 (2,594; 18f) | 1.30 (1,582; 9f) | 21.34 (7,692; 91f) |
| Hybrid, SFT editor, greedy | 5.70 (1,876; 19f) | 8.63 (1,876; 19f) | 2.93 (3,561; 12f) | 22.52 (8,116; 97f) |
| Hybrid, SFT editor, greedy+4 samples | 5.78 (1,905; 19f) | 8.76 (1,905; 19f) | 3.13 (3,813; 12f) | 22.60 (8,145; 97f) |
| Hybrid, SFT editor, +quality filter | 5.13 (1,690; 19f) | 7.77 (1,690; 19f) | 2.08 (2,530; 12f) | 21.55 (7,768; 92f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy | 5.67 (1,868; 18f) | 8.59 (1,868; 18f) | 2.88 (3,500; 12f) | 22.75 (8,197; 94f) |
| C1 frozen hybrid, DeepSeek few-shot, greedy+4 | 6.14 (2,024; 18f) | 9.31 (2,024; 18f) | 3.31 (4,024; 12f) | 23.57 (8,493; 95f) |
| C1 frozen hybrid, DeepSeek few-shot, +quality filter | 6.14 (2,022; 18f) | 9.30 (2,022; 18f) | 3.30 (4,016; 12f) | 23.56 (8,490; 95f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=4 | 0.81 (266; 4f) | 1.22 (266; 4f) | 1.06 (1,290; 11f) | 11.08 (3,992; 29f) |
| C2 LLM-only, DeepSeek-Prover-V2-7B, k=16 | 1.84 (605; 6f) | 2.78 (605; 6f) | — | 13.46 (4,851; 39f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=4 | 4.32 (1,422; 16f) | 6.54 (1,422; 16f) | 2.26 (2,745; 12f) | 24.25 (8,741; 95f) |
| C2 PRE-PASS (LeanPolish -> DeepSeek), k=16 | 5.23 (1,722; 16f) | 7.92 (1,722; 16f) | — | 28.92 (10,424; 95f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=4 | 4.92 (1,621; 16f) | 7.46 (1,621; 16f) | 2.43 (2,957; 12f) | 27.77 (10,007; 93f) |
| C2 POST-PASS (DeepSeek -> LeanPolish), k=16 | 6.85 (2,257; 17f) | 10.38 (2,257; 17f) | — | 29.21 (10,528; 95f) |
| C2 LLM-only, Qwen2.5-Coder-32B, k=4 | 0.34 (111; 1f) | 0.51 (111; 1f) | 1.85 (2,250; 12f) | — |
| C2 LLM-only, Qwen2.5-Coder-32B, k=16 | 1.38 (454; 3f) | 2.09 (454; 3f) | — | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=4 | 4.99 (1,645; 16f) | 7.57 (1,645; 16f) | 3.00 (3,657; 12f) | — |
| C2 PRE-PASS (LeanPolish -> Qwen-32B), k=16 | 5.16 (1,699; 16f) | 7.82 (1,699; 16f) | — | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=4 | 4.38 (1,441; 16f) | 6.63 (1,441; 16f) | 3.23 (3,931; 12f) | — |
| C2 POST-PASS (Qwen-32B -> LeanPolish), k=16 | 5.40 (1,779; 16f) | 8.18 (1,779; 16f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=4 | 8.38 (2,759; 18f) | 12.69 (2,759; 18f) | — | 24.14 (8,701; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=16 | 8.50 (2,800; 18f) | 12.88 (2,800; 18f) | — | 28.54 (10,286; 95f) |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=4 | 8.81 (2,901; 18f) | 13.34 (2,901; 18f) | — | — |
| C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=16 | 8.97 (2,955; 18f) | 13.59 (2,955; 18f) | — | — |
| C3 round 1: LeanPolish on hybrid output | 10.95 (3,606; 19f) | 16.59 (3,606; 19f) | 4.17 (5,079; 12f) | — |
| C3 round 1: + SFT editor | 11.02 (3,631; 19f) | 16.70 (3,631; 19f) | 4.24 (5,161; 12f) | — |
| C3 round 2: LeanPolish | 12.30 (4,050; 19f) | 18.63 (4,050; 19f) | 4.53 (5,506; 12f) | — |
| C3 round 2: + SFT editor | 12.30 (4,050; 19f) | 18.63 (4,050; 19f) | — | — |
| C3 round 3: LeanPolish | 13.28 (4,374; 19f) | 20.12 (4,374; 19f) | — | — |

Original tokens (this counter): putnam_verified 32,938, putnam_verified19 21,741, putnam2025 121,683, minif2f100 36,039

### C2 cost and candidate statistics (per model / corpus / input / k)

Lean calls = REPL declaration re-elaborations (screen) + REPL file boots + fresh `lake env lean` compiles (compose). GPU-s = generation run GPU seconds (incl. model load) apportioned by generated tokens. "compile rate" = screen-pass / distinct strictly-shorter rewrites (exhaustive screens only; Axiom uses exact early stopping, marked *). Saved = whole-file countLeanTokens saved vs the ORIGINAL files (pre-pass rows include LeanPolish's savings).

| model | corpus | input | k | units | samples | parse ok | stmt changed / no code / other | shorter rewrites | compile rate | units w/ pass | edits applied | gen tokens | GPU-s | Lean calls | saved | saved / 1k Lean calls |
|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| c2ds_ax | putnam2025 | LeanPolish (archived) | k4 | 443 | 1768 | 1757 | 3 / 1 / 7 | 140 | 24%* | 34 | 34 | 812,758 | 848.0 | 157 | 3129 | 19,930 |
| c2ds_ax | putnam2025 | original | k4 | 443 | 1768 | 1758 | 3 / 2 / 5 | 146 | 23%* | 34 | 34 | 830,529 | 866.6 | 157 | 1388 | 8,841 |
| c2ds_mf | minif2f100 | LeanPolish (archived) | k16 | 100 | 1600 | 1594 | 0 / 0 / 6 | 167 | 81% | 32 | 32 | 806,809 | 491.8 | 399 | 10775 | 27,005 |
| c2ds_mf | minif2f100 | LeanPolish (archived) | k4 | 100 | 400 | 397 | 0 / 0 / 3 | 48 | 77% | 20 | 20 | 200,243 | 122.1 | 268 | 9020 | 33,657 |
| c2ds_mf | minif2f100 | original | k16 | 100 | 1600 | 1598 | 0 / 0 / 2 | 188 | 87% | 43 | 43 | 1,003,490 | 611.6 | 431 | 5027 | 11,664 |
| c2ds_mf | minif2f100 | original | k4 | 100 | 400 | 400 | 0 / 0 / 0 | 71 | 87% | 35 | 35 | 246,099 | 150.0 | 306 | 4130 | 13,497 |
| c2ds_pv | putnam_verified | LeanPolish (archived) | k16 | 22 | 320 | 318 | 0 / 0 / 2 | 51 | 31% | 6 | 6 | 608,366 | 876.3 | 91 | 1743 | 19,154 |
| c2ds_pv | putnam_verified | LeanPolish (archived) | k4 | 22 | 80 | 80 | 0 / 0 / 0 | 15 | 33% | 3 | 3 | 154,794 | 223.0 | 61 | 1443 | 23,656 |
| c2ds_pv | putnam_verified | original | k16 | 22 | 320 | 315 | 0 / 0 / 5 | 63 | 30% | 8 | 8 | 625,526 | 901.0 | 102 | 611 | 5,990 |
| c2ds_pv | putnam_verified | original | k4 | 22 | 80 | 80 | 0 / 0 / 0 | 16 | 44% | 5 | 5 | 159,104 | 229.2 | 63 | 272 | 4,317 |
| c2q32_ax | putnam2025 | LeanPolish (archived) | k4 | 443 | 1772 | 1772 | 0 / 0 / 0 | 1324 | 7%* | 98 | 98 | 429,671 | 584.9 | 1280 | 4118 | 3,217 |
| c2q32_ax | putnam2025 | original | k4 | 443 | 1772 | 1772 | 0 / 0 / 0 | 1325 | 7%* | 98 | 98 | 421,775 | 574.1 | 1279 | 2459 | 1,923 |
| c2q32_mf | minif2f100 | LeanPolish (archived) | k4 | 100 | 400 | 399 | 1 / 0 / 0 | 216 | 11% | 16 | 0 | 58,837 | 134.7 | 311 | - | - |
| c2q32_mf | minif2f100 | original | k4 | 100 | 400 | 398 | 2 / 0 / 0 | 296 | 14% | 24 | 0 | 61,089 | 139.9 | 365 | - | - |
| c2q32_pv | putnam_verified | LeanPolish (archived) | k16 | 22 | 336 | 333 | 3 / 0 / 0 | 274 | 3% | 3 | 3 | 137,508 | 254.0 | 293 | 1720 | 5,870 |
| c2q32_pv | putnam_verified | LeanPolish (archived) | k4 | 22 | 84 | 83 | 1 / 0 / 0 | 75 | 4% | 3 | 3 | 35,798 | 66.1 | 118 | 1668 | 14,136 |
| c2q32_pv | putnam_verified | original | k16 | 22 | 336 | 330 | 6 / 0 / 0 | 282 | 3% | 3 | 3 | 142,675 | 263.5 | 300 | 458 | 1,527 |
| c2q32_pv | putnam_verified | original | k4 | 22 | 84 | 83 | 1 / 0 / 0 | 81 | 1% | 1 | 1 | 38,467 | 71.0 | 121 | 111 | 917 |
