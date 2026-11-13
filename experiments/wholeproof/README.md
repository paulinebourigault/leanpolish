# Whole-proof rewriter trained on LeanPolish pairs

Fine-tunes DeepSeek-Prover-V2-7B (LoRA) as a whole-proof rewriter on (original -> LeanPolish-shortened)
Goedel-Workbook proof pairs, and compares it with a frozen rewriter, with LeanPolish alone, and with
LeanPolish followed by the trained rewriter, on miniF2F-100, PutnamBench-verified (19 files) and
Putnam 2025 (AxiomProver, 12 files). Every candidate must keep every theorem statement unchanged, must
not add `sorry`/`axiom`/`native_decide` and similar, and must compile with a fresh `lake env lean`.

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `build_pairs.py` | reconstruct LeanPolish-shortened training files from the accepted-edit shard (SFT train split only) -> `wp_train.jsonl`, `build_stats.json` |
| `train_lora.py` | LoRA SFT (r 32, alpha 64, dropout 0.05, lr 1e-4 cosine, 2 epochs, seed 42) |
| `build_items.py` | evaluation items (original and LeanPolish-shortened variants) |
| `gen_whole.py` | vLLM generation, frozen or LoRA, `simple` (whole file) or `c2` (theorem, spliced) prompt |
| `parse_verify.py` | parse, gate, and verify each unique candidate with a fresh `lake env lean` |
| `verify_refs.py` | reference compile of every input file |
| `analyze.py` | whole-file metrics under both token counters -> `results/metrics.json` |
| `make_table.py` | `results/metrics.json` -> markdown table |
| `run.sh` | all steps in order |

## How to run

```bash
mkdir work && cd work
SHARDS_ROOT=/path/to/dataset SFT_DATA=/path/to/sft_data \
HYBRID_FILES=/path/to/beyond_teacher/files CONTROLS_DIR=/path/to/hybrid_controls \
  bash ../scripts/run.sh
```

Inputs come from the dataset <https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>
(`shards/`, and the `experiments/beyond_teacher` and `experiments/hybrid_controls` tarballs for the
evaluation files). Training and generation need one GPU (H100 used); verification is CPU-bound.
The trained adapter is in `adapters/` on the dataset; generations, verdicts and the compile cache
are in the `experiments/wholeproof` tarball. To recompute the metrics from those files only:
`WORK_DIR=<unpacked tarball> python3 scripts/analyze.py`.

## Outputs (`results/`)

- `metrics.json`: per corpus and condition, reduction under counter A (`countLeanTokens` port,
  primary) and B (`count_appL`), files improved, generated tokens, GPU-seconds, compile pass rates.
- `table.md`: the same as a table. `build_stats.json`: training-pair construction.
  `adapter_trainstats.json`: optimizer steps and wall time.

## Key numbers (counter A)

| Quantity | Paper | `results/` |
|---|---:|---:|
| Training pairs (Goedel-Workbook) | 7,708 | 7,708 |
| Unchanged pairs | 11% | 856 / 7,708 = 11.1% |
| Training time | 67 GPU-minutes | 3,999 s |
| Trained rewriter, k=16, miniF2F-100 (99 files) | 16.36 | 16.36 |
| Trained rewriter, k=16, PutnamBench-verified | 5.53 | 5.53 |
| LeanPolish (release) -> trained rewriter, miniF2F-100 | 27.13 | 27.13 |
| LeanPolish (release) -> trained rewriter, PutnamBench-verified | 8.36 | 8.36 |
| Samples yielding a verified shorter proof, trained vs. frozen (miniF2F-100, k=16) | 62% vs. 16% | 62% vs. 16% |

The frozen-rewriter baseline quoted in the paper (12.52 on miniF2F-99, 2.76 on PutnamBench,
Table 4) is the frozen whole-proof rewrite of `experiments/controls`; the frozen conditions
re-run here with the same gate give 12.52 (C2 prompt) and 6.83 (SFT prompt) on the same 99 files and
3.05 / 1.92 on PutnamBench-verified at k=16. On Putnam 2025 only 3 of 12 AxiomProver files fit the
rewriter's context and no rewrite improves on LeanPolish.

## Replication over seeds, problems and base models

`scripts/replication.py` recomputes, from saved verdicts only (CPU, about a minute):

```bash
REPLICATION_DATA=/path/to/replication python3 scripts/replication.py     # -> results/replication.json
```

* five trained rewriters (training seeds 42, 1, 2, 3, 4), each decoded with three seeds, against the
  frozen model decoded with the same seeds;
* 252 further miniF2F proofs and 15 further PutnamBench problems;
* a second base model, Qwen2.5-Coder-7B-Instruct, with a prompt control;
* sample budgets: the result with k of the 16 samples, k = 1, 2, 4, 8, 16.

The frozen models use the theorem-level prompt (`c2`), which works best for them; trained models use
their training prompt (`simple`). Differences come with a 95% paired file bootstrap.

| Whole-corpus reduction (%), 16 samples | Frozen | Trained, mean ± SD over seeds | Gain (pp) | Seeds above frozen |
|---|---:|---:|---:|---:|
| DeepSeek, miniF2F-99 | 11.73 | 16.94 ± 1.08 | +5.21 [−0.73, +11.24] | 5/5 |
| DeepSeek, 252 further miniF2F proofs | 13.69 | 15.21 ± 0.82 | +1.52 [−2.72, +5.83] | 5/5 |
| DeepSeek, PutnamBench-19 | 3.56 | 5.19 ± 0.89 | +1.63 [−0.67, +5.09] | 5/5 |
| DeepSeek, 15 further PutnamBench problems | 4.01 | 3.47 ± 0.79 | −0.54 [−3.30, +1.88] | 1/5 |
| Qwen2.5-Coder, miniF2F-99 | 16.90 | 9.16 | −7.74 [−12.94, −3.44] | 0/2 |

| All 351 miniF2F proofs, k samples per proof | Frozen | Trained | Gain (pp) | Proofs shortened, frozen / trained |
|---|---:|---:|---:|---:|
| k = 1 | 3.37 | 8.63 | +5.26 [+3.52, +7.13] | 12% / 58% |
| k = 2 | 5.22 | 10.43 | +5.22 [+3.09, +7.45] | 17% / 68% |
| k = 4 | 7.52 | 12.21 | +4.70 [+2.13, +7.35] | 24% / 77% |
| k = 8 | 10.15 | 13.95 | +3.79 [+0.82, +6.84] | 31% / 83% |
| k = 16 | 13.15 | 15.56 | +2.42 [−1.11, +5.96] | 36% / 86% |

Reading: fine-tuning makes the rewriter reliable, so it helps most when few samples can be verified.
Eight frozen plus eight trained samples reach 20.68%, above sixteen of either. There is no gain on
PutnamBench, whose proofs are much longer than the training proofs, and training makes Qwen, which
already cuts aggressively when prompted, more conservative (frozen Qwen with the training prompt:
13.96%). `results/metrics.json` above is the single seed-42 run.

Verdicts, generations and evaluation items of all runs are in the `experiments/replication` tarball
of the dataset; the seed-42 rewriter adapter is `adapters/wholeproof_deepseek`.
