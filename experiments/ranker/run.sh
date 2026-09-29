#!/usr/bin/env bash
# Complete-pool ranker (paper Sec. 4.2, Table 3): end-to-end driver.
#
# Stages (each can be run on its own by setting STAGE=pools|train|score|eval):
#   pools  complete-menu LeanPolish over the Goedel-Workbook training files (run_pools.py),
#          then parse the raw logs into site-level pools (extract_pools.py)       [CPU + Lean]
#   train  build pointwise samples and train the full and the goal-ablated ranker  [1 GPU]
#   score  score held-out pools with both rankers and the frozen log-prob baselines [1 GPU]
#   eval   selection metrics, bootstrap CIs, pool statistics, leakage check        [CPU]
#
# Environment (defaults in brackets):
#   LEAN_PROJECT  LeanPolish Lake project with the complete-menu binary built [<repo>/leanpolish]
#   DATA_DIR      working directory for logs/, pools/, data/, ckpt/, scores/  [./data]
#   OUT_DIR       metrics output                                              [./results]
#   BASE_MODEL    ranker backbone / frozen scorer [deepseek-ai/DeepSeek-Prover-V2-7B]
#   QWEN7B, QWEN32B  frozen baselines [Qwen/Qwen2.5-Coder-7B-Instruct, Qwen/Qwen2.5-Coder-32B-Instruct]
#   OLD_GROUPS_DIR   first-success ranking groups (eval_groups_*.jsonl) for the order-rule contrast [unset]
#   PROCS         parallel Lean processes [16];  MAXS  training-sample cap [80000]
# Held-out pools are the complete-menu pools of experiments/complete_menu
# ($DATA_DIR/pools/cm_{minif2f,putnam_verified,axiom}.jsonl.gz); the prebuilt pools are in the
# `experiments/complete_pools_ranker` archive of the dataset.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${LEANPOLISH_ROOT:-$(cd "$HERE/../.." && pwd)}"
LEAN_PROJECT="${LEAN_PROJECT:-$REPO/leanpolish}"
DATA_DIR="${DATA_DIR:-$PWD/data}"
OUT_DIR="${OUT_DIR:-$HERE/results}"
BASE_MODEL="${BASE_MODEL:-deepseek-ai/DeepSeek-Prover-V2-7B}"
QWEN7B="${QWEN7B:-Qwen/Qwen2.5-Coder-7B-Instruct}"
QWEN32B="${QWEN32B:-Qwen/Qwen2.5-Coder-32B-Instruct}"
PROCS="${PROCS:-16}"
MAXS="${MAXS:-80000}"
STAGE="${STAGE:-all}"
export BASE_MODEL
P="$DATA_DIR/pools"; S="$DATA_DIR/scores"; C="$DATA_DIR/ckpt"
mkdir -p "$P" "$S" "$C" "$DATA_DIR/data" "$DATA_DIR/logs" "$OUT_DIR"
cd "$HERE"

HELDOUT="$P/cm_minif2f.jsonl.gz $P/cm_putnam_verified.jsonl.gz $P/cm_axiom.jsonl.gz"
EXTRA="$P/goedel_val.jsonl.gz $P/mathlib_heldout_sub3000.jsonl.gz"

if [[ $STAGE == all || $STAGE == pools ]]; then
  # Goedel-Workbook training sources are expected under $LEAN_PROJECT/src/goedel/
  for part in A B; do
    python3 run_pools.py --lake-root "$LEAN_PROJECT" --src-dir src/goedel \
      --file-list "file_lists/train_files_part$part.txt" --logdir "$DATA_DIR/logs/goedel_$part" \
      --procs "$PROCS" --chunk-size 4
  done
  python3 extract_pools.py --logdir "$DATA_DIR/logs/goedel_A" "$DATA_DIR/logs/goedel_B" \
    --corpus goedel_train --out "$P/goedel_train.jsonl.gz"
fi

if [[ $STAGE == all || $STAGE == train ]]; then
  python3 build_train_data.py --train-pools "$P/goedel_train.jsonl.gz" \
    --eval-pools $HELDOUT --out "$DATA_DIR/data/train_samples.jsonl"
  python3 train_pointwise.py --train "$DATA_DIR/data/train_samples.jsonl" --out "$C/ranker_full" --max-samples "$MAXS"
  python3 train_pointwise.py --train "$DATA_DIR/data/train_samples.jsonl" --out "$C/ranker_nogoal" --no-goal --max-samples "$MAXS"
fi

if [[ $STAGE == all || $STAGE == score ]]; then
  python3 score_models.py --pools $HELDOUT $EXTRA --method ranker --name rk_full --adapter "$C/ranker_full/adapter" --out "$S/rk_full.jsonl"
  python3 score_models.py --pools $HELDOUT $EXTRA --method ranker --name rk_nogoal --no-goal --adapter "$C/ranker_nogoal/adapter" --out "$S/rk_nogoal.jsonl"
  python3 score_models.py --pools $HELDOUT $EXTRA --method frozen_lp --name lp_dsp7b --model "$BASE_MODEL" --bs 32 --out "$S/lp_dsp7b.jsonl"
  python3 score_models.py --pools $HELDOUT $EXTRA --method frozen_lp --name lp_qwen7b --model "$QWEN7B" --bs 32 --out "$S/lp_qwen7b.jsonl"
  python3 score_models.py --pools $HELDOUT --method frozen_lp --name lp_qwen32b --model "$QWEN32B" --bs 8 --out "$S/lp_qwen32b.jsonl"
fi

if [[ $STAGE == all || $STAGE == eval ]]; then
  SC="$S/rk_full.jsonl $S/rk_nogoal.jsonl $S/lp_dsp7b.jsonl $S/lp_qwen7b.jsonl $S/lp_qwen32b.jsonl"
  EV="minif2f=$P/cm_minif2f.jsonl.gz putnam_verified=$P/cm_putnam_verified.jsonl.gz axiom=$P/cm_axiom.jsonl.gz"
  OG=(); [[ -n "${OLD_GROUPS_DIR:-}" ]] && OG=(--old-groups-dir "$OLD_GROUPS_DIR")
  python3 eval_metrics.py --eval-pools $EV --train-pools "$P/goedel_train.jsonl.gz" --scores $SC \
    "${OG[@]}" --out "$OUT_DIR/metrics_heldout_official.json" > "$OUT_DIR/metrics_heldout_official.txt"
  python3 make_results_tables.py "$OUT_DIR/metrics_heldout_official.json" > "$OUT_DIR/tables_heldout_official.md"
  python3 eval_metrics.py --eval-pools "goedel_val=$P/goedel_val.jsonl.gz" "mathlib=$P/mathlib_heldout_sub3000.jsonl.gz" \
    --train-pools "$P/goedel_train.jsonl.gz" --scores $SC --out "$OUT_DIR/metrics_extra.json" > "$OUT_DIR/metrics_extra.txt"
  python3 bootstrap_ci.py "$OUT_DIR/bootstrap_ci.json" --scores $SC --eval-pools $EV
  python3 leakage_check.py "$OUT_DIR/leakage_goal_overlap.json" "$P/goedel_train.jsonl.gz" \
    goedel_val="$P/goedel_val.jsonl.gz" cm_minif2f="$P/cm_minif2f.jsonl.gz" \
    cm_putnam_verified="$P/cm_putnam_verified.jsonl.gz" cm_axiom="$P/cm_axiom.jsonl.gz"
fi
