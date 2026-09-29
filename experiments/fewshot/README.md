# Frozen 4-shot baseline — `4-shot` rows of Table 2

DeepSeek-Prover-V2-7B and Qwen2.5-Coder-7B-Instruct, not fine-tuned. Each
model receives its own chat template with four fixed demonstrations as prior
user/assistant turns (two tactic replacements, two deletions; verbatim rows of
`sft_train.jsonl`, selected with seed 0), then the eval-site prompt. Greedy
decoding (≤256 new tokens) on all 1,406 held-out sites. Success = `pass`
verdict from `leanpolish/verify_pair.py` on the spliced file AND strictly
fewer tokens; everything else counts zero.

## Files

| File | Purpose |
|---|---|
| `gen_fewshot.py` | Demo selection, chat-template rendering, vLLM generation, output parsing. |
| `run_gen_gpu.sh` | Generates candidates for both models (`DATA_DIR`, `OUT_DIR`). |
| `verify_fewshot.py` | Parallel, resumable exact verification (wraps `verify_pair.verify_row`). |
| `compute_fewshot_metrics.py` | Valid-and-shorter@1 and token savings per corpus / edit family, file-bootstrap CIs. |
| `fewshot_demos.json` | The four demonstrations, in conversation order. |
| `fewshot_prompt_rendered_fs_*.txt` | Fully rendered prompt for one site, per model. |

## Run

```bash
DATA_DIR=../sft/data OUT_DIR=out bash run_gen_gpu.sh          # one GPU
python3 verify_fewshot.py --cands out/cands_fewshot_*.jsonl \
    --root "$EVAL_ROOT" --project-root "$LEAN_PROJECT" --workers 24 --out out/verdicts_fewshot.jsonl
LEANPOLISH_COUNTER=lean python3 compute_fewshot_metrics.py --cands out/cands_fewshot_*.jsonl \
    --verdicts out/verdicts_fewshot.jsonl --out fewshot_metrics.json --md fewshot_results.md
```

`LEANPOLISH_COUNTER=lean` uses the `countLeanTokens` port (paper tables);
the default `appL` uses `retokenize_appendixL.count_appL`. Candidates and
verdicts are in the HF dataset `experiments/fewshot` tarball
(<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>).

## Results (`results/`)

- `fewshot_metrics.json`, `fewshot_results.md` — `countLeanTokens` counter (paper).
- `fewshot_metrics_appL.json` — same with `count_appL`.

| Method | miniF2F All | Tac. | Tok. | PB-verified All | Tac. | Tok. | Putnam 2025 All | Tac. | Tok. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| DeepSeek-Prover-V2-7B, 4-shot | 36.9 | 4.7 | 7,539 | 48.8 | 4.7 | 979 | 53.5 | 0.0 | 1,350 |
| Qwen2.5-Coder-7B, 4-shot | 46.9 | 17.9 | 9,046 | 48.8 | 7.0 | 964 | 59.2 | 12.3 | 1,401 |

The frozen models output `<DELETE>` at 1,103 (DeepSeek) and 1,007 (Qwen) of
the 1,406 sites (72–78 %), so most of their successes are deletions.
