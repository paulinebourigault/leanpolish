
#### Goedel-val (779 sites; 581 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 7.1 | 7.0 | 24.1 | 18.5 | 50.0 | 50.0 |
| menu_first | 14.6 | 18.1 | 14.6 | 13.0 | 56.4 | 59.5 |
| menu_last | 0.0 | 0.0 | 33.7 | 8.7 | 43.6 | 40.5 |
| shortest | 7.3 | 9.1 | 7.3 | 6.5 | 45.6 | 42.7 |
| tactic_prior(train) | 35.8 | 37.7 | 45.4 | 43.7 | 73.1 | 77.1 |
| lp_dsp7b | 34.3 | 30.9 | 76.2 | 74.0 | 71.6 | 80.6 |
| lp_dsp7b_sum | 50.3 | 46.8 | 83.0 | 82.6 | 65.8 | 77.0 |
| lp_qwen7b | 44.8 | 41.7 | 79.3 | 78.6 | 67.6 | 74.1 |
| lp_qwen7b_sum | 45.3 | 42.6 | 75.9 | 76.3 | 64.5 | 69.7 |
| rk_nogoal | 68.8 | 65.1 | 90.5 | 92.5 | 96.8 | 97.4 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 59.3 | 59.3 | 82.1 | 63.6 | 96.8 | 97.4 |
| rk_full | 80.7 | 78.4 | 94.5 | 95.6 | 99.4 | 99.4 |
| rk_full[valid-head,shortest-if-p>0.5] | 71.5 | 69.4 | 93.6 | 81.4 | 99.4 | 99.4 |
| ref:first_success(verifier) | 73.8 | 66.4 | 100.0 | 99.9 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### Mathlib-sub3000 (3000 sites; 500 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 10.4 | 8.2 | 19.0 | 11.9 | 50.0 | 50.0 |
| menu_first | 22.2 | 31.8 | 22.2 | 7.7 | 32.1 | 23.7 |
| menu_last | 14.6 | 0.0 | 62.4 | 42.5 | 67.9 | 76.3 |
| shortest | 11.2 | 15.9 | 11.2 | 3.9 | 30.5 | 22.5 |
| tactic_prior(train) | 6.8 | 1.8 | 7.4 | 0.9 | 65.1 | 68.7 |
| lp_dsp7b | 36.9 | 17.7 | 75.9 | 39.7 | 83.6 | 88.8 |
| lp_dsp7b_sum | 35.2 | 40.4 | 42.4 | 13.1 | 48.5 | 42.8 |
| lp_qwen7b | 29.2 | 7.2 | 71.6 | 43.9 | 79.5 | 83.7 |
| lp_qwen7b_sum | 13.0 | 8.1 | 17.8 | 4.1 | 42.1 | 29.8 |
| rk_nogoal | 41.3 | 51.8 | 45.5 | 29.1 | 92.7 | 95.4 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 34.1 | 40.8 | 44.3 | 29.8 | 92.7 | 95.4 |
| rk_full | 53.8 | 65.5 | 56.4 | 42.2 | 95.6 | 96.2 |
| rk_full[valid-head,shortest-if-p>0.5] | 48.4 | 50.4 | 57.7 | 47.8 | 95.6 | 96.2 |
| ref:first_success(verifier) | 91.4 | 80.7 | 100.0 | 99.4 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### pooled (3779 sites; 1081 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 8.6 | 7.4 | 21.7 | 18.1 | 50.0 | 50.0 |
| menu_first | 18.1 | 22.6 | 18.1 | 12.7 | 44.8 | 37.9 |
| menu_last | 6.8 | 0.0 | 47.0 | 11.0 | 55.2 | 62.1 |
| shortest | 9.1 | 11.3 | 9.1 | 6.3 | 40.1 | 30.5 |
| tactic_prior(train) | 22.4 | 25.9 | 27.8 | 40.8 | 68.3 | 72.1 |
| lp_dsp7b | 35.5 | 26.6 | 76.1 | 71.7 | 76.6 | 85.5 |
| lp_dsp7b_sum | 43.3 | 44.7 | 64.2 | 78.0 | 59.0 | 56.4 |
| lp_qwen7b | 37.6 | 30.3 | 75.8 | 76.2 | 71.7 | 79.8 |
| lp_qwen7b_sum | 30.3 | 31.2 | 49.0 | 71.4 | 54.0 | 45.7 |
| rk_nogoal | 56.1 | 60.7 | 69.7 | 88.2 | 93.5 | 96.2 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 47.6 | 53.2 | 64.6 | 61.3 | 93.5 | 96.2 |
| rk_full | 68.3 | 74.1 | 76.9 | 92.0 | 97.1 | 97.5 |
| rk_full[valid-head,shortest-if-p>0.5] | 60.8 | 63.2 | 77.0 | 79.2 | 97.1 | 97.5 |
| ref:first_success(verifier) | 82.0 | 71.2 | 100.0 | 99.9 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

