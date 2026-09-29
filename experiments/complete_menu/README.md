# Complete-menu search and fixed-point iteration

Two extensions of the LeanPolish optimizer (paper Sec. 3, Sec. 5, Table 4,
Table 11):

* **Complete-menu search** (`--complete-menu`): every automation-menu candidate is evaluated at
  every site. The shortest valid, filter-passing candidate is accepted, and every other candidate
  is labelled `valid_not_chosen`, `rejected_kernel`, `timeout`, or filtered. This produces complete
  candidate pools. Default (first-success) behaviour is unchanged.
* **Fixed-point iteration**: LeanPolish is re-run on its own verified output until no file changes.
  Every round is re-checked in a fresh Lean process.

The patched optimizer is `leanpolish/LeanPolish.lean` and `leanpolish/leanpolish.py` at the
repository root. `patches/` contains the diff of the complete-menu mode against the first-success
optimizer, for reference only.

## Files

| File | Purpose |
|---|---|
| `fixpoint.py` | Iterates LeanPolish to a fixed point (re-runs only the files that changed) |
| `fp_compile.py` | Fresh `lake env lean` check of every file state after a round |
| `fp_metrics.py` | Per-round whole-corpus reduction, written to `results/fixedpoint_*` |
| `analyze_complete_menu.py` | First-success vs complete-menu comparison; extracts the pools |
| `final_metrics.py` | Final tables T1 to T5, written to `results/final_*` |
| `clean_subset.py`, `perfile_diff.py` | Budget-clean subset and per-file differences |
| `make_tables.py` | Markdown tables from `results/metrics.json` |
| `minif2f_subsample100.txt` | The fixed miniF2F-100 subset |
| `smoke/` | Two small inputs, plus the expected shortened output for `amc12_2000_p5` |

## How to run

```bash
cd leanpolish                                   # the Lake project (LEAN_PROJECT)
# complete-menu run on a folder (raw Lean logs with [MENU_POOL] lines go to LEANPOLISH_RAWLOG_DIR)
LEANPOLISH_RAWLOG_DIR=raw/cm/putnam_verified \
  python3 leanpolish.py --batch runs/cm/putnam_verified --complete-menu \
  --workers 6 --threads 4 --chunk-size 1 --timeout 1800
# fixed point: round 1 = an existing first-success run over corpora/<corpus>/
python3 ../experiments/complete_menu/fixpoint.py putnam_verified runs/base/putnam_verified 6 10
python3 ../experiments/complete_menu/fp_compile.py putnam_verified 5 8
```

Metrics are computed from the saved runs. Download the `experiments/complete_menu_runs` and
`experiments/complete_menu_fixedpoint` archives from the dataset
(<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>) and unpack them into
`DATA_DIR` (default `./data`):

```bash
export DATA_DIR=/path/to/complete_menu_runs      # corpora/, runs/, raw/, cm2/
python3 analyze_complete_menu.py                 # results/metrics.json, $DATA_DIR/pools/
python3 final_metrics.py                         # results/final_metrics.json, final_tables.md
DATA_DIR=/path/to/complete_menu_fixedpoint python3 fp_metrics.py   # results/fixedpoint_*
```

Environment variables:

* `LEAN_PROJECT` (default `<repo>/leanpolish`)
* `DATA_DIR` (default `./data`)
* `OUT_DIR` (default `./results`)
* `FILE_LISTS` (default `<repo>/experiments/metrics/file_lists`)
* `LEANPOLISH_ROOT` (default: the repository root)
* `LEAN_PATH_PREFIX` (default `~/.elan/bin`)

The full candidate pools are in the `experiments/complete_menu_pools` archive.

## Outputs (`results/`)

* `metrics.json`: first-success vs complete-menu comparison (`analyze_complete_menu.py`)
* `final_metrics.json`, `final_tables.md`: tables T1 to T5 (`final_metrics.py`)
* `fixedpoint_metrics.json`, `fixedpoint_table.md`: fixed-point rounds (`fp_metrics.py`)
* `clean_subset.json`: budget-clean subset (`clean_subset.py`)
* `perfile_<corpus>.json`: per-file differences (`perfile_diff.py`); `axiom_r2` is the second
  (rerun) Putnam 2025 / AxiomProver run, reported as "rerun" in `final_tables.md`

## Key numbers (paper)

Fixed point: whole-file token reduction (%), Lean-aware counter; source is `results/fixedpoint_table.md`.

| Corpus | Single clean pass | Fixed point | Rounds to fixed point |
|---|---:|---:|---:|
| AxiomProver (12) | 1.41 | 1.76 | 4 |
| PutnamBench-verified (19) | 11.91 | 16.07 | 5 |
| miniF2F-99 | 20.52 | 29.76 | 8 |
| miniF2F (all 351) | | 27.5 | 8 |

The single-pass column is the "clean rerun" row of Table 4. Round 1 of the fixed-point
table was computed on a separate first-success run, which gives 11.85 on PutnamBench and 20.86 on
miniF2F-100. miniF2F-99 drops the one linter-baseline artifact from the 100-file subset;
`results/fixedpoint_table.md` reports the 100-file values (fixed point 29.96).

Complete-menu pools (Sec. 3; source is `results/final_tables.md`, T3 and T4):

| Quantity | Paper | Saved |
|---|---|---|
| Valid candidates per site (sites with at least one) | 2.2 to 3.4 | 2.22 to 3.36 |
| Sites with at least two valid candidates | 55 to 74% | 54.8 to 73.5% |
| Menu-search time, complete vs first-success | 1.1 to 1.3x | 1.10 to 1.29x |

Table 11 (PutnamBench `putnam_1975_a1`): 15 menu candidates. `omega` is chosen
(5 characters). `linarith` (the first-success winner), `gcongr`, and `tauto` are valid but not
chosen. The remaining 11 are kernel failures.
