### T1. Whole-corpus reduction. Counter A (Lean-aware, comment-skipping) is primary; appL is secondary

| corpus | files | A tokens | FS saved A (%) | CM saved A (%) | CM+timeout-all saved A (%) | FS appL % | CM appL % | files w/o report FS/CM |
|---|---|---|---|---|---|---|---|---|
| PutnamBench-verified (19) | 19 | 22116 | 2624 (11.865) | 2636 (11.919) | 2639 (11.933) | 11.210 | 11.262 | 0/0 |
| Putnam 2025 AxiomProver (12), rerun | 12 | 133686 | 1882 (1.408) | 1729 (1.293) | 1678 (1.255) | 1.138 | 1.047 | 1/2 |
| Putnam 2025 AxiomProver (12), first run | 12 | 133686 | 1031 (0.771) | 1045 (0.782) | not run | 0.644 | 0.661 | 3/4 |
| miniF2F-verified (351) | 351 | 140040 | 29388 (20.985) | 28925 (20.655) | not run | 20.907 | 20.629 | 3/3 |
| Mathlib sample (300, seed 0) | 300 | 670439 | 1879 (0.280) | 1989 (0.297) | not run | 0.196 | 0.209 | 10/10 |

### T2. Accepted edits and same-site tactic changes (FS vs CM, after whole-file verification)

| corpus | accepted tactic FS | CM | accepted all FS | CM | same site same tactic | same site different tactic (CM shorter in chars) | A-token delta at those sites | byte delta | only FS | only CM | top transitions |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PutnamBench-verified (19) | 58 | 63 | 138 | 143 | 40 | 17 (17) | 0 | 64 | 1 | 6 | norm_cast -> omega ×8; norm_cast -> tauto ×4; linarith -> omega ×4; by norm_cast -> by omega ×1 |
| Putnam 2025 AxiomProver (12), rerun | 75 | 82 | 160 | 162 | 64 | 6 (6) | 0 | 23 | 5 | 12 | by norm_cast -> by omega ×2; by linarith -> by omega ×1; norm_cast -> tauto ×1; norm_cast -> omega ×1 |
| Putnam 2025 AxiomProver (12), first run | 68 | 92 | 111 | 130 | 58 | 8 (8) | 0 | 30 | 2 | 26 | norm_cast -> omega ×3; by norm_cast -> by omega ×2; by linarith -> by omega ×1; norm_cast -> tauto ×1 |
| miniF2F-verified (351) | 794 | 799 | 1313 | 1317 | 611 | 155 (155) | 0 | 545 | 28 | 33 | norm_cast -> omega ×77; linarith -> omega ×32; linarith -> tauto ×12; norm_num -> omega ×6 |
| Mathlib sample (300, seed 0) | 285 | 317 | 293 | 325 | 245 | 28 (28) | 0 | 111 | 12 | 44 | norm_cast -> tauto ×9; norm_cast -> omega ×6; by norm_cast -> by tauto ×6; by norm_cast -> by omega ×4 |

### T3. Runtime and cost

| corpus | wall mean FS / CM (s) | wall median FS / CM | wall total FS / CM (s) | files hitting fold budget FS / CM | menu search time in CM run: complete / first-success simulated (s) | ratio |
|---|---|---|---|---|---|---|
| PutnamBench-verified (19) | 135.3 / 133.3 | 41.3 / 38.8 | 2570 / 2532 | 6 / 6 | 134.1 / 106.6 | 1.26 |
| Putnam 2025 AxiomProver (12), rerun | 506.2 / 664.5 | 199.3 / 199.8 | 6074 / 7974 | 11 / 9 | 507.0 / 393.7 | 1.29 |
| Putnam 2025 AxiomProver (12), first run | 889.4 / 911.6 | 299.6 / 294.6 | 10673 / 10939 | 6 / 9 | 601.0 / 496.6 | 1.21 |
| miniF2F-verified (351) | 111.4 / 118.6 | 28.0 / 29.0 | 39094 / 41633 | 28 / 28 | 3576.4 / 2806.8 | 1.27 |
| Mathlib sample (300, seed 0) | 110.0 / 111.3 | 14.0 / 14.9 | 33004 / 33389 | 14 / 18 | 2896.8 / 2632.6 | 1.10 |

### T4. Candidate pools (CM run, detection-time sites)

| corpus | sites | sites with ≥1 valid+shorter | mean valid / site (given ≥1) | frac ≥2 valid (given ≥1) | sites with chosen edit | chosen ≠ first-success pick | label counts |
|---|---|---|---|---|---|---|---|
| PutnamBench-verified (19) | 403 | 255 | 2.70 | 0.667 | 134 | 44 | chosen 134, rejected_kernel 4598, rejected_length 13, rejected_quality 375, skipped_length 475, valid_not_chosen 180 |
| Putnam 2025 AxiomProver (12), rerun | 965 | 454 | 3.05 | 0.725 | 227 | 53 | chosen 227, rejected_kernel 9681, rejected_length 157, rejected_quality 749, skipped_length 3024, timeout 2, valid_not_chosen 410 |
| Putnam 2025 AxiomProver (12), first run | 1247 | 556 | 2.92 | 0.700 | 253 | 63 | chosen 253, rejected_kernel 12991, rejected_length 191, rejected_quality 916, skipped_length 3657, timeout 5, valid_not_chosen 452 |
| miniF2F-verified (351) | 4951 | 3302 | 3.36 | 0.735 | 1990 | 440 | chosen 1990, rejected_kernel 53576, rejected_length 423, rejected_quality 5984, skipped_length 8982, timeout 4, valid_not_chosen 3111 |
| Mathlib sample (300, seed 0) | 13586 | 3832 | 2.22 | 0.548 | 2847 | 536 | chosen 2847, rejected_kernel 167439, rejected_length 1749, rejected_quality 2576, skipped_length 18349, timeout 48, valid_not_chosen 3102 |

### T5. Ranking diagnostic: top-1 accuracy (%) of simple rules at recovering the chosen candidate (ties give expected accuracy)

| corpus | pool | n | earliest in menu | latest in menu | shortest string | random |
|---|---|---|---|---|---|---|
| PutnamBench-verified (19) | **v1 released-style group** (winner + earlier failures, ≥2 rows) | 51 | 0.0 | **100.0** | 0.0 | 19.2 |
| PutnamBench-verified (19) | CM: all tried candidates | 134 | 2.2 | 0.0 | 1.1 | 7.2 |
| PutnamBench-verified (19) | CM: valid+shorter only | 134 | 67.2 | 46.3 | 82.5 | 57.1 |
| PutnamBench-verified (19) | CM: selectable (valid, shorter, gate) | 134 | 67.2 | 56.0 | 89.6 | 62.2 |
| PutnamBench-verified (19) | CM: selectable, ≥2 options | 78 | 43.6 | 24.4 | 82.1 | 35.1 |
| Putnam 2025 AxiomProver (12), rerun | **v1 released-style group** (winner + earlier failures, ≥2 rows) | 36 | 0.0 | **100.0** | 0.0 | 19.2 |
| Putnam 2025 AxiomProver (12), rerun | CM: all tried candidates | 227 | 37.4 | 0.0 | 18.7 | 9.1 |
| Putnam 2025 AxiomProver (12), rerun | CM: valid+shorter only | 227 | 76.7 | 27.8 | 84.6 | 44.3 |
| Putnam 2025 AxiomProver (12), rerun | CM: selectable (valid, shorter, gate) | 227 | 76.7 | 45.4 | 95.6 | 52.7 |
| Putnam 2025 AxiomProver (12), rerun | CM: selectable, ≥2 options | 159 | 66.7 | 22.0 | 93.7 | 32.4 |
| Putnam 2025 AxiomProver (12), first run | **v1 released-style group** (winner + earlier failures, ≥2 rows) | 31 | 0.0 | **100.0** | 0.0 | 20.4 |
| Putnam 2025 AxiomProver (12), first run | CM: all tried candidates | 253 | 35.2 | 0.0 | 17.6 | 9.0 |
| Putnam 2025 AxiomProver (12), first run | CM: valid+shorter only | 253 | 75.1 | 29.2 | 83.2 | 45.0 |
| Putnam 2025 AxiomProver (12), first run | CM: selectable (valid, shorter, gate) | 253 | 75.1 | 48.6 | 96.0 | 53.3 |
| Putnam 2025 AxiomProver (12), first run | CM: selectable, ≥2 options | 175 | 64.0 | 25.7 | 94.3 | 32.5 |
| miniF2F-verified (351) | **v1 released-style group** (winner + earlier failures, ≥2 rows) | 700 | 0.0 | **100.0** | 0.0 | 22.0 |
| miniF2F-verified (351) | CM: all tried candidates | 1990 | 9.2 | 0.0 | 4.6 | 7.0 |
| miniF2F-verified (351) | CM: valid+shorter only | 1990 | 77.9 | 36.1 | 80.6 | 51.4 |
| miniF2F-verified (351) | CM: selectable (valid, shorter, gate) | 1990 | 77.9 | 47.6 | 92.6 | 60.2 |
| miniF2F-verified (351) | CM: selectable, ≥2 options | 1205 | 63.5 | 13.5 | 87.7 | 34.3 |
| Mathlib sample (300, seed 0) | **v1 released-style group** (winner + earlier failures, ≥2 rows) | 194 | 0.0 | **100.0** | 0.0 | 18.0 |
| Mathlib sample (300, seed 0) | CM: all tried candidates | 2847 | 15.0 | 9.3 | 7.8 | 8.8 |
| Mathlib sample (300, seed 0) | CM: valid+shorter only | 2847 | 81.2 | 50.7 | 89.8 | 65.3 |
| Mathlib sample (300, seed 0) | CM: selectable (valid, shorter, gate) | 2847 | 81.2 | 51.5 | 90.2 | 65.8 |
| Mathlib sample (300, seed 0) | CM: selectable, ≥2 options | 1522 | 64.8 | 9.3 | 81.7 | 36.1 |
