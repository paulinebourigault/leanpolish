#!/usr/bin/env bash
# Few-shot generation for both frozen models (greedy), resumable per model.
# Inputs : $DATA_DIR/eval_sites_*.jsonl and $DATA_DIR/sft_train.jsonl (from experiments/sft).
# Outputs: $OUT_DIR/cands_fewshot_deepseek.jsonl, $OUT_DIR/cands_fewshot_qwen.jsonl
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-./data}"
OUT_DIR="${OUT_DIR:-./out}"
mkdir -p "$OUT_DIR"
export TRITON_LIBCUDA_PATH="${TRITON_LIBCUDA_PATH:-/usr/lib/x86_64-linux-gnu}"
SITES="$DATA_DIR/eval_sites_minif2f.jsonl $DATA_DIR/eval_sites_putnam_verified.jsonl $DATA_DIR/eval_sites_putnam2025_per_file.jsonl"
for spec in "deepseek-ai/DeepSeek-Prover-V2-7B fewshot_deepseek" \
            "Qwen/Qwen2.5-Coder-7B-Instruct fewshot_qwen"; do
  set -- $spec
  out="$OUT_DIR/cands_$2.jsonl"
  if [[ -s "$out" ]]; then echo "[skip] $out"; continue; fi
  echo "[gen] $1 -> $out ($(date))"
  python3 "$HERE/gen_fewshot.py" --model "$1" --tag "$2" --sites $SITES \
      --train "$DATA_DIR/sft_train.jsonl" --out "$out.tmp" && mv "$out.tmp" "$out"
done
echo "[gen] done ($(date))"
