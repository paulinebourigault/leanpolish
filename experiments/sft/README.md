# Learning from LeanPolish edits (SFT / DPO) — Table 2

Fine-tunes a 7B model on accepted LeanPolish edits and evaluates it on all
1,406 held-out teacher sites (miniF2F 1,184, PutnamBench-verified 80,
Putnam 2025 / AxiomProver 142). A site counts as a success only if the
spliced file receives a `pass` verdict from `leanpolish/verify_pair.py`
(fresh `lake env lean`, Lean 4.21.0 / Mathlib v4.21.0) and the replacement
is strictly shorter in tokens; failures save zero.

## Scripts

| Script | Purpose |
|---|---|
| `build_sft_data.py` | HF shards → `sft_train.jsonl` (17,099), `sft_val.jsonl` (437), `eval_sites_*.jsonl`, `build_stats.json`. Goal-hash leakage filter, file-level split, seed 42. |
| `build_dpo_data.py` | Same-attempt (accepted, failed sibling) pairs → `dpo_pairs.jsonl` (16,839 hard pairs), `dpo_stats.json`. |
| `train_sft_lora.py` | BF16 LoRA SFT (r 32, α 64, dropout 0.05, all-linear, 2 epochs, lr 1e-4 cosine, eff. batch 64, seed 42). `--model` selects DeepSeek-Prover-V2-7B (default) or Qwen2.5-Coder-7B-Instruct. |
| `train_dpo_lora.py` | DPO from the merged DeepSeek SFT model (1 epoch, β 0.1, lr 1e-5). |
| `gen_candidates.py` | vLLM generation: greedy + 4 samples (T 0.6, top-p 0.95), ≤256 new tokens. |
| `screen_candidates.py` | Optional REPL pre-screen (filter only; needs a leanprover-community/repl client, not shipped, via `REPL_CLIENT_DIR`). |
| `prepare_final_verify.py` | Joins screen results, writes `chunk_NNN.jsonl` for the exact lane. |
| `run_verify_chunks.sh` | Resumable exact lane: runs `leanpolish/verify_pair.py` on every chunk. Only these verdicts are used. |
| `compute_metrics.py` | Per (condition, corpus) rates, savings, file-bootstrap CIs. |

Environment variables: `LEANPOLISH_ROOT` (archive root, default: two levels
up), `LEAN_PROJECT` / `PROJECT_ROOT` (Lean project, default `<archive>/leanpolish`),
`EVAL_ROOT` (directory with the held-out source files), `CKPT_DIR` (checkpoints),
`LEANPOLISH_COUNTER` (`appL` default, or `lean` for the `countLeanTokens` port).

## Run

```bash
python build_sft_data.py --shards-root $SHARDS --out data/
python build_dpo_data.py --shards-root $SHARDS --out data_dpo/
python train_sft_lora.py --train data/sft_train.jsonl --val data/sft_val.jsonl \
    --out $CKPT_DIR/sft-deepseek --merge            # add --model Qwen/Qwen2.5-Coder-7B-Instruct for Qwen
python train_dpo_lora.py --pairs data_dpo/dpo_pairs.jsonl \
    --model $CKPT_DIR/sft-deepseek/merged --out $CKPT_DIR/dpo-deepseek --merge
for tag in frozen sft dpo; do                       # frozen: --model deepseek-ai/DeepSeek-Prover-V2-7B
  python gen_candidates.py --model <model> --tag $tag \
      --sites data/eval_sites_*.jsonl --out cands_$tag.jsonl
done
python screen_candidates.py --cands cands_*.jsonl --root $EVAL_ROOT --workers 6 --out screen_results.jsonl
python prepare_final_verify.py --cands cands_*.jsonl --screen screen_results.jsonl \
    --out-dir verify_chunks --strip-sha minif2f putnam_verified
CHUNK_DIR=verify_chunks ROOT=$EVAL_ROOT JOBS=6 bash run_verify_chunks.sh
python compute_metrics.py --cands cands_*.jsonl --screen screen_results.jsonl \
    --exact-glob 'verify_chunks/*.kernel_verified.jsonl' --out metrics.json --bootstrap 2000
```

Screening can be skipped by sending every candidate to `verify_pair.py`.
For miniF2F and PutnamBench-verified, `content_sha256` is dropped
(`--strip-sha`) because the source snapshots differ in bytes outside every
edit span; byte-exact span equality is still enforced.

The paper table (Table 2) uses the strict policy (only exact-lane `pass`
verdicts, reference-identical outputs re-verified) and the `countLeanTokens`
counter; it is recomputed from the saved candidates and verdicts by
`experiments/metrics/` and saved here as `results/tab_sft.json`.

## Data and models

Generated candidates, screen results, verdict chunks and held-out eval sites are shipped in
`<release>/results_data/` (`data/`, `exp1_sft_dpo/`); the training files rebuild from the HF shards
with `build_sft_data.py` / `build_dpo_data.py` (seed 42). The SFT and DPO LoRA adapters are under `adapters/`
(<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>).

## Results (`results/`)

- `tab_sft.json` — the rows of Table 2 (strict policy, `countLeanTokens`).
- `deepseek_frozen_vs_sft_appL.json`, `qwen_frozen_vs_sft_appL.json` — `compute_metrics.py`
  output (`count_appL` counter, 2,000 bootstrap resamples; includes valid@4, exact match, novel edits).
- `build_stats.json`, `dpo_stats.json` — data-construction statistics.

Key numbers (Table 2; All / Tac. = valid-and-shorter %, Tok. = verified token savings):

| Method | miniF2F All | Tac. | Tok. | PB-verified All | Tac. | Tok. | Putnam 2025 All | Tac. | Tok. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Reference (pipeline) | 94.6 | 91.6 | 27,622 | 88.8 | 79.1 | 1,359 | 84.5 | 61.4 | 1,746 |
| Delete rule (no model) | 36.8 | 0.0 | 8,122 | 46.3 | 0.0 | 975 | 59.9 | 0.0 | 1,500 |
| DeepSeek-Prover-V2-7B, frozen | 0.1 | 0.1 | 28 | 0.0 | 0.0 | 0 | 0.0 | 0.0 | 0 |
| Qwen2.5-Coder-7B, frozen | 0.5 | 0.8 | 189 | 0.0 | 0.0 | 0 | 1.4 | 0.0 | 32 |
| DeepSeek-Prover-V2-7B, SFT | 86.7 | 79.0 | 26,163 | 86.3 | 74.4 | 1,337 | 79.6 | 49.1 | 1,666 |
| Qwen2.5-Coder-7B, SFT | 84.5 | 75.5 | 25,317 | 82.5 | 67.4 | 1,316 | 76.8 | 42.1 | 1,648 |
| DeepSeek-Prover-V2-7B, DPO | 84.5 | 75.6 | 25,614 | 85.0 | 72.1 | 1,333 | 73.2 | 33.3 | 1,618 |

4-shot rows: see `experiments/fewshot/`. Greedy exact match with the
reference (DeepSeek SFT): 82.7 / 82.5 / 91.5 %.
