
#### miniF2F (4982 sites; 1995 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 8.0 | 8.6 | 23.0 | 14.1 | 50.0 | 50.0 |
| menu_first | 9.2 | 14.2 | 9.2 | 6.6 | 42.5 | 41.4 |
| menu_last | 0.0 | 0.0 | 20.7 | 3.7 | 57.5 | 58.6 |
| shortest | 4.6 | 7.1 | 4.6 | 3.3 | 42.7 | 41.3 |
| tactic_prior(train) | 25.5 | 34.3 | 32.6 | 38.9 | 65.5 | 70.2 |
| lp_dsp7b | 22.8 | 17.7 | 51.6 | 49.4 | 66.1 | 68.6 |
| lp_dsp7b_sum | 34.6 | 30.9 | 59.7 | 63.7 | 63.4 | 67.2 |
| lp_qwen7b | 24.5 | 17.9 | 53.3 | 47.3 | 60.5 | 63.3 |
| lp_qwen7b_sum | 30.2 | 27.0 | 53.4 | 50.3 | 55.7 | 57.2 |
| lp_qwen32b | 22.9 | 16.9 | 55.3 | 48.7 | 63.1 | 65.6 |
| lp_qwen32b_sum | 26.7 | 20.3 | 55.0 | 56.1 | 59.6 | 62.2 |
| rk_nogoal | 49.8 | 53.0 | 66.1 | 67.4 | 90.9 | 91.3 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 40.2 | 45.5 | 56.0 | 48.6 | 90.9 | 91.3 |
| rk_full | 70.8 | 74.8 | 84.1 | 80.0 | 97.0 | 96.3 |
| rk_full[valid-head,shortest-if-p>0.5] | 61.3 | 66.1 | 79.3 | 73.3 | 97.0 | 96.3 |
| ref:first_success(verifier) | 77.9 | 63.5 | 100.0 | 99.1 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### PutnamBench-verified (412 sites; 140 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 8.8 | 9.8 | 20.1 | 13.6 | 50.0 | 50.0 |
| menu_first | 2.1 | 2.4 | 2.1 | 0.1 | 34.9 | 32.3 |
| menu_last | 0.0 | 0.0 | 12.9 | 12.8 | 65.1 | 67.7 |
| shortest | 1.1 | 1.2 | 1.1 | 0.0 | 44.7 | 39.4 |
| tactic_prior(train) | 12.9 | 21.4 | 14.3 | 17.2 | 61.4 | 65.9 |
| lp_dsp7b | 32.1 | 19.0 | 46.4 | 51.2 | 65.5 | 67.3 |
| lp_dsp7b_sum | 47.1 | 36.9 | 57.1 | 66.9 | 64.2 | 65.1 |
| lp_qwen7b | 32.9 | 20.2 | 50.0 | 55.4 | 58.8 | 63.0 |
| lp_qwen7b_sum | 37.1 | 26.2 | 45.7 | 47.4 | 53.7 | 52.8 |
| lp_qwen32b | 34.3 | 20.2 | 56.4 | 59.9 | 64.1 | 66.4 |
| lp_qwen32b_sum | 40.0 | 31.0 | 54.3 | 64.5 | 60.4 | 60.9 |
| rk_nogoal | 47.9 | 53.6 | 58.6 | 50.2 | 90.6 | 91.0 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 50.4 | 58.3 | 60.7 | 66.0 | 90.6 | 91.0 |
| rk_full | 75.0 | 79.8 | 80.7 | 74.9 | 97.6 | 96.9 |
| rk_full[valid-head,shortest-if-p>0.5] | 57.5 | 67.9 | 66.1 | 45.7 | 97.6 | 96.9 |
| ref:first_success(verifier) | 65.7 | 42.9 | 100.0 | 97.5 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### AxiomProver-Putnam2025 (1247 sites; 253 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 9.5 | 8.8 | 32.6 | 20.2 | 50.0 | 50.0 |
| menu_first | 35.2 | 45.1 | 35.2 | 39.4 | 40.7 | 36.4 |
| menu_last | 0.0 | 0.0 | 48.2 | 3.8 | 59.3 | 63.6 |
| shortest | 17.6 | 22.6 | 17.6 | 19.7 | 44.0 | 36.5 |
| tactic_prior(train) | 4.7 | 2.9 | 19.0 | 22.4 | 60.2 | 63.8 |
| lp_dsp7b | 33.2 | 21.7 | 68.4 | 24.5 | 70.3 | 72.7 |
| lp_dsp7b_sum | 49.2 | 42.0 | 72.7 | 55.8 | 65.5 | 62.4 |
| lp_qwen7b | 30.4 | 19.4 | 68.0 | 11.3 | 66.2 | 66.8 |
| lp_qwen7b_sum | 27.7 | 16.0 | 49.4 | 17.4 | 59.8 | 50.0 |
| lp_qwen32b | 28.1 | 20.0 | 69.2 | 17.1 | 68.3 | 67.2 |
| lp_qwen32b_sum | 34.8 | 29.1 | 62.1 | 33.2 | 62.4 | 55.3 |
| rk_nogoal | 62.5 | 57.7 | 81.8 | 67.8 | 92.3 | 91.4 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 38.3 | 42.0 | 54.9 | 51.1 | 92.3 | 91.4 |
| rk_full | 62.1 | 58.3 | 77.5 | 69.3 | 95.5 | 93.8 |
| rk_full[valid-head,shortest-if-p>0.5] | 48.8 | 42.9 | 70.4 | 62.4 | 95.5 | 93.8 |
| ref:first_success(verifier) | 75.1 | 64.0 | 100.0 | 97.3 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### pooled (6641 sites; 2388 with >=1 acceptable candidate)

| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |
|---|---:|---:|---:|---:|---:|---:|
| random | 8.2 | 8.7 | 23.8 | 14.2 | 50.0 | 50.0 |
| menu_first | 11.6 | 17.2 | 11.6 | 7.4 | 41.9 | 40.1 |
| menu_last | 0.0 | 0.0 | 23.1 | 4.0 | 58.1 | 59.9 |
| shortest | 5.8 | 8.6 | 5.8 | 3.7 | 43.3 | 40.5 |
| tactic_prior(train) | 22.6 | 29.8 | 30.1 | 37.5 | 64.6 | 69.0 |
| lp_dsp7b | 24.5 | 18.3 | 53.1 | 48.7 | 66.6 | 69.1 |
| lp_dsp7b_sum | 36.9 | 32.6 | 61.0 | 63.6 | 64.0 | 66.4 |
| lp_qwen7b | 25.6 | 18.2 | 54.6 | 46.4 | 61.1 | 63.8 |
| lp_qwen7b_sum | 30.3 | 25.6 | 52.5 | 49.1 | 56.2 | 55.9 |
| lp_qwen32b | 24.1 | 17.5 | 56.8 | 48.1 | 63.9 | 65.8 |
| lp_qwen32b_sum | 28.3 | 22.0 | 55.7 | 55.6 | 60.2 | 61.1 |
| rk_nogoal | 51.0 | 53.6 | 67.3 | 66.7 | 91.0 | 91.3 |
| rk_nogoal[valid-head,shortest-if-p>0.5] | 40.6 | 45.8 | 56.2 | 49.4 | 91.0 | 91.3 |
| rk_full | 70.1 | 73.1 | 83.2 | 79.4 | 96.8 | 96.0 |
| rk_full[valid-head,shortest-if-p>0.5] | 59.8 | 63.4 | 77.6 | 71.9 | 96.8 | 96.0 |
| ref:first_success(verifier) | 76.9 | 62.4 | 100.0 | 99.0 | 100.0 | 100.0 |
| oracle | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

#### Pool statistics

| stat | train | miniF2F | PutnamBench-verified | AxiomProver-Putnam2025 | pooled |
|---|---:|---:|---:|---:|---:|
| sites | 13217 | 4969 | 394 | 1231 | 6594 |
| files | 2400 | 348 | 18 | 11 | 377 |
| mean_run_candidates_per_site | 14.48 | 13.18 | 13.79 | 12.03 | 13.00 |
| mean_valid_per_site | 2.54 | 2.32 | 1.87 | 1.47 | 2.14 |
| pct_sites_ge1_valid | 69.88 | 67.38 | 67.51 | 47.60 | 63.69 |
| pct_sites_ge2_valid | 56.34 | 49.67 | 45.43 | 32.82 | 46.27 |
| pct_ge2_valid_given_ge1 | 80.63 | 73.72 | 67.29 | 68.94 | 72.64 |
| sites_ge1_acceptable | 8588 | 1995 | 140 | 253 | 2388 |
| mean_acceptable_given_ge1 | 3.05 | 2.56 | 2.44 | 2.79 | 2.58 |
| pct_ge2_acceptable_given_ge1 | 77.47 | 60.45 | 60.00 | 69.17 | 61.35 |
| pct_first_success_not_shortest | 13.11 | 22.06 | 34.29 | 24.90 | 23.07 |
| pct_first_success_no_edit_but_acceptable_exists | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| first_success_savings_frac_of_oracle | 0.999 | 0.991 | 0.975 | 0.973 | 0.990 |
