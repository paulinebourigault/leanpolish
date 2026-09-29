# Unified token metrics and corpus statistics (Table 1, App. token counters)

Whole-corpus token metrics for every source, computed with two tokenizers on the same
reconstructed text:

* **A, primary**: `count_lean_tokens` (`leanpolish/lean_counter.py`), a Python port of
  `countLeanTokens` in `LeanPolish.lean`. It skips comments and is the counter behind the
  per-file `tokens_original` / `tokens_shortened` fields.
* **B, comment-counting**: `count_appL` (`leanpolish/retokenize_appendixL.py`).

Definitions. *Inputs* = every input file of the corpus (explicit lists in `file_lists/`).
The shortened text is rebuilt from the released accepted edits. Span edits are applied in
descending byte order, and each one is checked to match the original bytes. Files that are not
shortened count 0 saved tokens. *Token reduction* = saved / original tokens over all inputs.
*Density* = accepted edits per 1,000 original tokens. *tok/edit* = saved tokens per accepted edit.
Learning-table success (`recompute_numbers.py`) is strict: a candidate succeeds only if it has a
saved exact-verifier `pass` verdict **and** is strictly shorter.

## Scripts

| Script | Output (`results/`) | Paper |
|---|---|---|
| `compute_metrics.py` | `metrics.json`, `per_file.json`, `file_lists/*.txt` | Table 1 (reduction, density, tok/edit), hybrid whole-file rows |
| `recompute_numbers.py` | `recompute_numbers.json` (+ markdown on stdout) | Table 2, family table, bootstrap CIs, ranker/selection, dataset totals |
| `learning_table_port.py` | `recompute_numbers_port.json` | learning table under counter A |
| `reference_row.py` | `reference_row.json` | "Reference (pipeline)" row, both counters |
| `fewshot_port.py`, `frontier_port.py` | `fewshot_metrics_port.json`, `fewshot_results_port.md`, `frontier_port.json` | few-shot and frontier rows under counter A |
| `make_tables.py` | `tables.tex`, `tables.md`, `tab_sft_port.json` | collected tables |
| `corpus/aggregate_headline.py` | `headline_v4.json` | released totals (files, accepted, failed siblings) |
| `corpus/corpus_stats_v2.py` | `corpus_stats_v2.{json,md}` | per-corpus statistics |
| `corpus/dedup_leakage.py` | `dedup_leakage.json` | goal-state overlap between training and held-out corpora |
| `corpus/linter_aggregate.py` | `linter_baseline.{json,md}` | linter baseline |
| `corpus/g3_sample.py` | `g3_sample.json` | generalization-gate (G3) sample statistics |
| `corpus/make_paper_figures.py` | `figs/*.pdf` | release composition figures |

## Running

```bash
# unified corpus metrics (CPU, ~5-10 min): needs the LeanPolish run directory (Lake project with
# Mathlib, corpus sources, released shards/<corpus>/training_pairs.jsonl)
CORPUS_ROOT=/path/to/run EVAL_ROOT=/path/to/run HYBRID_DATA=/path/to/beyond_teacher \
  python3 compute_metrics.py
# learning-table numbers from saved candidates and verdicts (CPU, ~10 s)
python3 recompute_numbers.py
python3 learning_table_port.py
python3 reference_row.py
FEWSHOT_DATA=/path/to/fewshot python3 fewshot_port.py
FRONTIER_DATA=/path/to/frontier_hybrid python3 frontier_port.py
python3 make_tables.py
```

`LEANPOLISH_ROOT` (default: the release root, found from the script location) locates
`leanpolish/`. `RESULTS_DIR` is the saved learning-experiment record tree (`data/`,
`exp1_sft_dpo/`, `exp2_ranker/`, `exp4_corpus_variation/`). It is shipped at
`<release>/results_data/` (the default), so `recompute_numbers.py`, `learning_table_port.py` and
`reference_row.py` run offline. Other inputs are under `experiments/` in the HF dataset
(https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression). `per_file.json` (6 MB)
is also on HF. Frontier-prover inputs from Aristotle are not redistributed.

## Key numbers (Table 1)

| Source | Inputs | Files | Accepted | Failed siblings | Tok. red. (%) | Density | tok/edit |
|---|---|---|---|---|---|---|---|
| Mathlib v4.21.0 subset | 5,789 | 2,233 | 6,695 | 26,912 | 0.27 | 0.46 | 5.9 |
| Goedel-Workbook | 29,750 | 10,052 | 20,822 | 28,525 | 5.48 | 4.72 | 11.6 |
| PutnamBench sample | 437 | 352 | 4,354 | 5,930 | 8.14 | 9.10 | 8.9 |
| miniF2F verified | 351 | 308 | 1,184 | 3,753 | 19.72 | 8.45 | 23.3 |
| PutnamBench verified | 19 | 16 | 80 | 254 | 6.14 | 3.62 | 17.0 |
| Putnam 2025 (AxiomProver) | 12 | 10 | 142 / 125 | 147 / 75 | 1.31 | 1.06 | 12.3 |
| Total | | 12,972 | 33,402 | 65,596 | | | |

The Files / Accepted / Failed columns count released shard rows (`headline_v4.json`, the
release totals written by `corpus/aggregate_headline.py`). They include
92 linter-baseline files (`*_linter.lean`), so 12,880 files are genuine inputs. `metrics.json`
reports input-file-only counts (for example Goedel 9,966 files / 20,704 edits). The reduction, density
and tok/edit columns come from `metrics.json` (counter A).
