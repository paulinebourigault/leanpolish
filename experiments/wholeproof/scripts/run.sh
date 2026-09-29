#!/usr/bin/env bash
# Whole-proof rewriter experiment, end to end. Run from a working directory (data/, gens/,
# verdicts/, logs/ are created there).
#   Env: LEANPOLISH_ROOT (archive root; default three levels above this file)
#        LEAN_PROJECT    Lake project with Mathlib v4.21.0 (default $LEANPOLISH_ROOT/leanpolish)
#        SHARDS_ROOT     dataset root containing shards/ (for build_pairs.py)
#        SFT_DATA        directory with sft_train.jsonl / sft_val.jsonl (experiments/sft/build_sft_data.py)
#        HYBRID_FILES, CONTROLS_DIR   see build_items.py
#        MODEL           base model (default deepseek-ai/DeepSeek-Prover-V2-7B); ADAPTER output dir (default ./adapter)
#   Steps: [1] SFT pairs  [2] LoRA training  [3] eval items  [4] generation (GPU, n=16, T=0.7)
#          [5] gate + fresh `lake env lean` verification (CPU)  [6] metrics + table
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LEANPOLISH_ROOT="${LEANPOLISH_ROOT:-$(cd "$HERE/../../.." && pwd)}"
export LEAN_PROJECT="${LEAN_PROJECT:-$LEANPOLISH_ROOT/leanpolish}"
export VLLM_WORKER_MULTIPROC_METHOD=spawn
A="${ADAPTER:-$PWD/adapter}"
mkdir -p data gens verdicts logs
D=data

# [1] + [2] training
[ -s $D/wp_train.jsonl ] || python3 $HERE/build_pairs.py $D
[ -s $A/adapter_config.json ] || python3 $HERE/train_lora.py --data $D/wp_train.jsonl --out $A > logs/train.log 2>&1
# [3] eval items (orig and LeanPolish-shortened base variants)
python3 $HERE/build_items.py

g() { # name lora prompt items...   (extra generation args via $EXTRA)
  local name=$1 lora=$2 pr=$3; shift 3
  [ -s gens/$name.jsonl ] && return
  if [ "$lora" = none ]; then L=""; else L="--lora $lora"; fi
  python3 $HERE/gen_whole.py $L --prompt $pr ${EXTRA:-} --out gens/$name.jsonl.tmp --items "$@" > logs/gen_$name.log 2>&1 \
    && mv gens/$name.jsonl.tmp gens/$name.jsonl && mv gens/$name.jsonl.tmp.cost.json gens/$name.cost.json
}
v() { # name mode timeout items...
  local name=$1 mode=$2 to=$3; shift 3
  [ -s verdicts/$name.jsonl ] && return
  python3 $HERE/parse_verify.py --mode $mode --timeout $to --gens gens/$name.jsonl --out verdicts/$name.jsonl.tmp \
    --items "$@" > logs/verify_$name.log 2>&1 && mv verdicts/$name.jsonl.tmp verdicts/$name.jsonl
}

MF="$D/items_minif2f100_orig.jsonl $D/items_putnam_verified_orig.jsonl"
MB="$D/items_minif2f100_base.jsonl $D/items_putnam_verified_base.jsonl"
AO=$D/items_putnam2025_orig.jsonl; AB=$D/items_putnam2025_base.jsonl

# reference compile of every input (orig and base)
[ -s verdicts/refs_minif_pb.jsonl ] || python3 $HERE/verify_refs.py verdicts/refs_minif_pb.jsonl $MF $MB
[ -s verdicts/refs_axiom.jsonl ] || python3 $HERE/verify_refs.py verdicts/refs_axiom.jsonl $AO $AB

# [4]+[5] miniF2F-100 and PutnamBench-verified: n=16 samples, 32k context
g trained_orig_mfpb       $A   simple $MF; v trained_orig_mfpb       simple 600 $MF
g frozen_simple_orig_mfpb none simple $MF; v frozen_simple_orig_mfpb simple 600 $MF
g frozen_c2_orig_mfpb     none c2     $MF; v frozen_c2_orig_mfpb     c2     600 $MF
g trained_base_mfpb       $A   simple $MB; v trained_base_mfpb       simple 600 $MB

# [4]+[5] Putnam 2025 (AxiomProver): n=4 samples at 32k context (only 3 of 12 files fit)
EXTRA="--n 4 --max-model-len 32768"
g trained_orig_axiom4        $A   simple $AO; v trained_orig_axiom4        simple 1200 $AO
g frozen_simple_orig_axiom4  none simple $AO; v frozen_simple_orig_axiom4  simple 1200 $AO
g trained_base_axiom4        $A   simple $AB; v trained_base_axiom4        simple 1200 $AB
unset EXTRA

# [6] metrics (needs verdicts/compile_cache.jsonl written by parse_verify.py)
WORK_DIR=$PWD OUT_DIR=$HERE/../results python3 $HERE/analyze.py
python3 $HERE/make_table.py > $HERE/../results/table.md
