# Frontier-prover releases: symbolic pass and verified hybrid

Runs LeanPolish, and then the verified hybrid (LeanPolish followed by the SFT neural editor on the
tactic sites LeanPolish left untouched), on unmodified frontier-prover proofs: six Seed-Prover 1.5
Putnam 2025 files (A1, A2, A4, A6, B2, B4) and Aristotle IMO 2025 P3 and P5. Lean 4.21.0 /
Mathlib v4.21.0. Every final file is re-checked with a fresh `lake env lean` (no error, no `sorry`).
Input provenance, hashes and licenses: `PROVENANCE.md`.

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `env.sh` | shared settings (`LEANPOLISH_ROOT`, `LEAN_PROJECT`, `WORK_DIR`, `REPL_BIN`, `ADAPTER`) |
| `prep_files.sh` | stage the unmodified inputs into `$WORK_DIR/files` and print their sha256 |
| `run_teacher.sh` | symbolic pass (`leanpolish/leanpolish.py`, 7,200 s per file; B2 14,400 s) |
| `build_base.py` | LeanPolish output -> hybrid base files + `teacher_edits.json` (regions LeanPolish changed) |
| `extract_hybrid.py` | sites on the base files that LeanPolish left untouched (uses `../hybrid/scripts/extract_sites.py`) |
| `screen_sites.py` | REPL pre-screen (variant of the hybrid screen that ignores lines inside block comments) |
| `make_verify_rows.py` | screen verdicts -> rows for `../hybrid/scripts/verify_full.py` |
| `quality_filter.py` | Python port of LeanPolish's `isQualityUpgrade` (the "filter" lanes) |
| `combine.py` | joint application of individually verified edits + fresh re-check of each final file |
| `pipeline.sh` | stages [1]-[5] for one set of files (generation uses `../hybrid/scripts/gen_sites.py`) |
| `gd_lane.sh` | extended lane: also verifies candidates whose REPL goals differ (`ext` rows) |
| `aggregate.py` | whole-file metrics with both token counters -> `metrics.json` |
| `make_tables.py` | `metrics.json` -> markdown tables |

The two token counters are imported from `leanpolish/` (`lean_counter.py`, primary;
`retokenize_appendixL.py`, secondary).

## How to run

```bash
export WORK_DIR=$PWD/work REPL_BIN=/path/to/repl ADAPTER=/path/to/deepseek_sft_adapter
SEED_SRC=... ARISTOTLE_SRC=... bash scripts/prep_files.sh
bash scripts/run_teacher.sh
bash scripts/pipeline.sh b1 seed/A1 seed/A2 seed/A4 seed/A6 seed/B4 aristotle/P3 aristotle/P5
bash scripts/pipeline.sh b2 seed/B2
bash scripts/gd_lane.sh b1 20 seed/A1 seed/A2 seed/A4 seed/A6 seed/B4 aristotle/P3   # optional ext lane
GEN_ARGS="--base Qwen/Qwen2.5-Coder-7B-Instruct" ADAPTER=/path/to/qwen_sft_adapter \
  bash scripts/pipeline.sh q1 seed/A1 ...                                           # second editor
python3 scripts/aggregate.py results $WORK_DIR deepseek:main:run_b1,run_b2 \
  deepseek:ext:run_b1 qwen:main:run_q1
python3 scripts/make_tables.py results/metrics.json > results/tables.md
```

The adapter is the DeepSeek-Prover-V2-7B SFT LoRA (`experiments/sft/train_sft_lora.py`, same data and
seed 42; see `adapters/` on the dataset). Generation needs one GPU; screening and verification are CPU-bound.

## Outputs

- `results/metrics.json`: per file and total, original / LeanPolish / hybrid token counts under both
  counters (A = `countLeanTokens` port, primary; B = `count_appL`), for the lanes
  {greedy+4, greedy+16} x {raw, quality-filtered} and editors `deepseek:main`, `deepseek:ext`, `qwen:main`.
- `results/tables.md`: the same as markdown, pipeline counts, and example kept edits (Seed-Prover only).
- Bulk artifacts (sites, generations, screen and verification verdicts, combine reports, Seed-Prover
  final files): `experiments/frontier_hybrid` in the dataset
  <https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>.

## Key numbers (counter A, DeepSeek editor, raw greedy+4 lane)

| Quantity | Paper | `results/metrics.json` |
|---|---:|---:|
| Six Seed-Prover 1.5 files, LeanPolish alone | 4.37% | 3,521 / 80,565 = 4.37% |
| Six Seed-Prover 1.5 files, verified hybrid | 6.36% | 5,127 / 80,565 = 6.36% |
| Aristotle P3, LeanPolish alone | 0.3% | 15 / 5,064 = 0.30% |

The Aristotle P5 figure in the paper (0.5%) and the Lean/Mathlib 4.22 Seed-Prover vs. AxiomProver
comparison (App. "Frontier-Prover Details") come from the standalone symbolic runs, not from this
hybrid run; here the P5 symbolic pass produced no output within its budget, so P5 is credited 0 for
LeanPolish alone.
