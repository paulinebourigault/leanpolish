#!/usr/bin/env bash
# Verified hybrid on files whose symbolic pass (run_teacher.sh) has finished.
# usage: pipeline.sh TAG corpus/NAME [corpus/NAME ...]      e.g. pipeline.sh b1 seed/A1 seed/A2
#   [1] build base (LeanPolish output) + extract sites LeanPolish left untouched (REPL allTactics)
#   [2] SFT LoRA generation: greedy + 16 samples (T=0.6, top-p 0.95, seed 42)       (GPU)
#   [3] REPL screen (pre-filter only)
#   [4] fresh `lake env lean` verification of every surviving candidate             (final verdict)
#   [5] joint combine of individually verified edits + fresh re-check of each final file
# Env: see env.sh; SCREEN_JOBS / VERIFY_JOBS (default 20); GEN_ARGS extra args for gen_sites.py
#      (e.g. GEN_ARGS="--base Qwen/Qwen2.5-Coder-7B-Instruct" with ADAPTER=<qwen adapter>).
# Outputs: $WORK_DIR/run_<TAG>/{sites,gens,screen,verify_in,verdicts}.jsonl, final/, combine.json
set -uo pipefail
TAG=$1; shift
source "$(dirname "$0")/env.sh"
W=$WORK_DIR/run_$TAG; mkdir -p $W; cd "$LEAN_PROJECT"
echo "[1] base + extract"
python3 $S/build_base.py $F "$@" || exit 1
[ -s $W/sites.jsonl ] || python3 $S/extract_hybrid.py --only "$@" --files-root $F \
    --teacher-edits $WORK_DIR/teacher_edits.json --repl $REPL_BIN --out $W/sites.jsonl || exit 1
echo "[2] generate"
if [ ! -s $W/gens.jsonl ]; then
  python3 $H/gen_sites.py ${GEN_ARGS:-} --adapter "$ADAPTER" --sites $W/sites.jsonl \
    --k 16 --out $W/gens.jsonl.tmp && mv $W/gens.jsonl.tmp $W/gens.jsonl || exit 1
fi
echo "[3] screen"
python3 $S/screen_sites.py --sites $W/sites.jsonl --gens $W/gens.jsonl --files-root $F \
    --project "$LEAN_PROJECT" --repl $REPL_BIN --jobs ${SCREEN_JOBS:-20} --max-split 4 --cands-per-worker 150 \
    --tac-timeout 120 --decl-timeout 600 --out $W/screen.jsonl
python3 $S/make_verify_rows.py $W/sites.jsonl $W/screen.jsonl $W/verify_in.jsonl
echo "[4] verify"
python3 $H/verify_full.py --inp $W/verify_in.jsonl --out $W/verdicts.jsonl --files-root $F \
    --project "$LEAN_PROJECT" --jobs ${VERIFY_JOBS:-20} --timeout 3600
echo "[5] combine"
python3 $S/combine.py --sites $W/sites.jsonl --gens $W/gens.jsonl --verdicts $W/verdicts.jsonl \
    --teacher-edits $WORK_DIR/teacher_edits.json --files-root $F --project "$LEAN_PROJECT" \
    --final-root $W/final --only "$@" --out $W/combine.json
