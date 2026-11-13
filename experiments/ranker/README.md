# Complete-pool ranker

Candidate selection on complete candidate pools (paper Sec. 4.2, Table 3, Appendix
"Complete-pool ranker, further splits"). In complete-menu mode every menu candidate is labelled at
every proof state. The task is to pick the best candidate, meaning the shortest one that is valid
and passes the filter. We compare model-free rules, frozen log-probabilities, and a pointwise
two-head ranker: DeepSeek-Prover-V2-7B with LoRA r=16, heads P(valid) and P(best), one epoch,
seed 42. The ranker is trained on Goedel-Workbook pools that share no goal hash with the held-out
pools.

## Files

| File | Purpose |
|---|---|
| `run.sh` | End-to-end driver (`STAGE=pools\|train\|score\|eval`); documents all environment variables |
| `run_pools.py` | Runs the complete-menu LeanPolish in parallel and saves the raw `[MENU_POOL]` logs (resumable) |
| `extract_pools.py`, `poolcommon.py` | Parse logs into site-level pools; shared helpers |
| `build_train_data.py` | Pointwise samples (full and goal-ablated text); excludes held-out goal hashes |
| `train_pointwise.py`, `score_models.py` | Ranker training; ranker and frozen log-prob scoring (GPU) |
| `eval_metrics.py`, `make_results_tables.py` | Top-1 best, top-1 valid, savings, AUROC; markdown tables |
| `bootstrap_ci.py` | File-clustered bootstrap 95% CIs and paired differences |
| `pool_stats_all.py`, `leakage_check.py`, `compare_rerun.py` | Pool statistics, goal-hash overlap, label stability |
| `file_lists/` | Goedel training parts A to D (`run.sh` builds the training pools from parts A and B), Goedel validation files, Mathlib files |

## How to run

```bash
# evaluation only, from the released pools and scores (CPU, minutes)
export DATA_DIR=/path/to/complete_pools_ranker      # the dataset's experiments/ archive
STAGE=eval bash run.sh                               # writes results/
# full pipeline: complete-menu pools (Lean, CPU), training and scoring (one H100)
LEAN_PROJECT=../../leanpolish bash run.sh
```

The held-out pools are the complete-menu pools of `experiments/complete_menu`. Pools, scores,
and the two ranker adapters are available from
<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>. The pools and scores are
in `experiments/complete_pools_ranker`; the adapters are in `adapters/`.

## Outputs (`results/`)

* `metrics_heldout_official.{json,txt}` and `tables_heldout_official.md`: Table 3, per
  corpus and pooled
* `metrics_extra.{json,txt}` and `tables_extra.md`: Goedel validation split and the 3,000-state
  Mathlib sample
* `bootstrap_ci.json`: file-clustered 95% CIs
* `pool_stats_all.{json,md}`: pool statistics per source
* `leakage_goal_overlap.json`: goal-hash overlap with the training pools
* `label_stability_rerun.json`: validity labels re-checked in a low-parallelism re-run
* `first_success_order_rule.json`: the menu-order rule on the biased first-success ranking groups
  (`eval_metrics.py --first-success-groups-dir`; the groups are shipped as
  `results_data/exp2_ranker/data/eval_groups_*.jsonl`). Source of the "Last in menu order" row below
* `train/`: training-loss logs and sample statistics

## Key numbers (paper, Table 3; top-1 best, %, 2,388 pooled held-out states)

| Method | Top-1 |
|---|---:|
| Last in menu order (100% on the 718 biased first-success groups) | 0.0 |
| First in menu order | 11.6 |
| Random | 8.2 |
| Shortest string | 5.8 |
| Per-tactic prior | 22.6 |
| Frozen Qwen-32B log-prob | 28.3 |
| Frozen DeepSeek-7B log-prob | 36.9 |
| Trained ranker, no goal | 51.0 |
| Trained ranker | **70.1** |
| Ref.: verifier, first success | 76.9 |

Further numbers:

* Trained ranker: file-clustered 95% CI 66.3 to 73.9, validity AUROC 96.8, and 79% of oracle
  savings.
* Removing the goal costs 19.1 points (CI 15.2 to 22.7).
* Pools cover 6,641 held-out states and 53,272 Goedel-Workbook and Mathlib states.
* The ranker is trained on 13,290 Goedel states.
* A lower-parallelism re-run reproduced all 9,920 validity labels.
* On Goedel validation pools the ranker reaches 80.7% (no goal: 68.8%; AUROC 99.4).
* On the Mathlib sample the ranker reaches 53.8% (no goal: 41.3%), against 91.4% for the verifier.

All of these numbers match the saved files in `results/`.

## Ranker inside a search with a budget of Lean checks

`budgeted_search.py` replays the recorded complete-menu runs on all 6,641 held-out states, including
the 4,253 with no acceptable edit. A policy orders the candidates, spends at most b Lean checks per
state and keeps the first acceptable edit.

```bash
DATA_DIR=/path/to/complete_pools_ranker python3 budgeted_search.py      # CPU -> results/budgeted_search.json
```

| Share of the exhaustive token savings (38,144 tokens) | b = 1 | b = 2 | b = 4 | b = 8 | Checks to try every candidate |
|---|---:|---:|---:|---:|---:|
| Symbolic menu order | 7.7% | 38.5% | 46.9% | 75.6% | 63,458 |
| Shortest string | 7.7% | 7.7% | 38.5% | 73.4% | 64,862 |
| Per-tactic prior (training pools) | 34.8% | 38.5% | 66.9% | 92.2% | 60,132 |
| Frozen Qwen-7B log-prob | 47.7% | 60.6% | 73.9% | 89.1% | 58,895 |
| Frozen DeepSeek-7B log-prob | 63.5% | 75.6% | 89.3% | 97.3% | 56,632 |
| Trained ranker, no goal | 66.5% | 82.1% | 92.3% | 96.3% | 56,020 |
| Trained ranker | **81.1%** | **86.8%** | **95.4%** | **99.96%** | **54,886** |

With one check per state the ranker finds an acceptable edit in 27.4% of the states (menu order:
4.2%; 36.0% have one). Its maximum candidate score also tells states with an acceptable edit from
the others (AUROC 0.83; frozen DeepSeek 0.79).
