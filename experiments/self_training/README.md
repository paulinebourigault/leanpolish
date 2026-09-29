# Self-training on verified outputs (paper §5, "Self-training on verified outputs")

One round of expert iteration with the fine-tuned DeepSeek-Prover-V2-7B editor. The round-1 editor
proposes rewrites at tactic sites that LeanPolish left unchanged in 1,000 Goedel-Workbook training
proofs; candidates that are strictly shorter and pass the exact verifier become new edits. Two
round-2 variants continue from round 1 for one epoch on new edits plus a fixed replay sample:

* **naive**: all new edits (deduplicated to one per site, held-out goal hashes removed);
* **selection-aware**: only non-deletion edits accepted by LeanPolish's specificity filter
  (`quality_filter.py`, a port of `isQualityUpgrade`).

Success at a held-out site = candidate differs from the original, is strictly shorter under the
comment-counting tokenizer (`leanpolish/retokenize_appendixL.py`), and passes the exact check
(spliced into the original file, fresh `lake env lean`, no errors and no new `sorry`). The REPL
screen is only a pre-filter. CIs: file-level bootstrap, 2,000 resamples, seed 42; round-2 vs round-1
differences are paired over files.

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `select_files.py` | choose the 1,000 training files with most tactic lines not covered by teacher edits (seed 42) |
| `extract_sites.py`, `filter_train_sites.py` | REPL tactic-site extraction; drop sites overlapping teacher edits |
| `make_eval_sites.py`, `heldout_hashes.py` | held-out teacher sites (1,406) and goal hashes for leakage filtering |
| `screen_sites.py`, `prep_verify.py`, `verify_full.py`, `run_pipeline.sh` | REPL pre-screen, verification queue, exact verification |
| `build_new_edits.py` | verified candidates to new edits (release schema) and round-2 training sets |
| `train_continue.py` | continue a LoRA adapter (round-2); `train_sft_lora.py` for the from-base variant |
| `eval_metrics.py` | vs@1 / vs@5 per corpus and family, beyond-teacher savings, compliance, paired CIs |
| `shard.py` | split a site file into K shards by source file |
| `run_self_training.sh` | end-to-end driver (all stages in order) |

`gen_sites.py`, `compose.py` and `quality_filter.py` are shared with the hybrid experiment and are
imported from `../hybrid/scripts/`; the tokenizers from `../../leanpolish/`. `extract_sites.py`,
`screen_sites.py` and `verify_full.py` are the hybrid versions with process-group cleanup on timeout
and environment-variable defaults; `train_sft_lora.py` is `experiments/sft/train_sft_lora.py` with
an optional `--no-grad-ckpt` flag.

## Running

```bash
export LEAN_PROJECT=<release>/leanpolish      # built Lake project (Lean 4.21.0, Mathlib v4.21.0)
export REPL_BIN=<path>/repl/.lake/build/bin/repl   # leanprover-community/repl, same toolchain
export FILES_ROOT=$PWD/files BASE_MODEL=deepseek-ai/DeepSeek-Prover-V2-7B R1_ADAPTER=<released SFT adapter>
export SHARDS_ROOT=<HF dataset>/shards DATA_DIR=$PWD/data CORPUS_ROOT=<corpus dir>
bash scripts/run_self_training.sh
```

Requires one GPU (vLLM, PEFT) and a multi-core CPU for verification. `data/` holds the selected
files (`selected_files.json`) and the two stem lists that make up the 1,000 files. Sites, generations,
screen/verify verdicts and round-2 training sets are in the HF dataset under
`experiments/self_improve` (https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression).

## Results (`results/`)

* `new_edits_stats.json`: training-site funnel (sites, candidates, verdicts, new edits).
* `metrics_main.json`: round 1 vs naive vs selection-aware on all held-out sets, with compliance.
* `metrics_tactic_with_frombase.json`: tactic-family sites incl. the from-base retrain (`r2b*`).
* `metrics.json`: combined summary.

| Quantity (paper §5) | Value |
|---|---|
| Tactic sites left unchanged by LeanPolish in 1,000 training proofs | 5,472 |
| Shorter proposals that compile | 410 |
| New edits after deduplication | 372 (0.55% of the files' tokens) |
| Deletions / specificity-filter violations | 2 / 147 (40%) |
| Held-out tactic sites (n = 847), round 1 | 74.9% |
| Naive round 2 (paired diff, 95% CI) | 72.9% (−2.0, [−3.6, −0.5]) |
| Selection-aware round 2 (paired diff, 95% CI) | 70.7% (−4.1, [−6.1, −2.2]) |
| Filter compliance of verified outputs: teacher sites / off-distribution / naive round 2 | 96% / 32% / 34% |
| Round-2 optimizer steps | 10–12 |
