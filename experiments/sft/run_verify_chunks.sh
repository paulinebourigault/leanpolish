#!/usr/bin/env bash
# Resumable driver for the exact verify_pair.py lane (final verdicts).
# Loops over chunk_*.jsonl (and agreement_*.jsonl) in $CHUNK_DIR, skipping any
# chunk that already has a .kernel_verified.jsonl (safe to rerun).
# Inputs: CHUNK_DIR (from prepare_final_verify.py), ROOT (eval sources),
#         PROJECT_ROOT (Lean project, default <archive>/leanpolish).
# Outputs: <chunk>.kernel_verified.jsonl next to each chunk.
#
# Usage: CHUNK_DIR=verify_chunks ROOT=$EVAL_ROOT \
#        PROJECT_ROOT=/path/to/leanpolish JOBS=6 bash run_verify_chunks.sh
set -uo pipefail
CHUNK_DIR="${CHUNK_DIR:?}"
ROOT="${ROOT:?}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$HERE/../../leanpolish}"
JOBS="${JOBS:-6}"
TIMEOUT="${TIMEOUT:-300}"
PY="${PY:-python3}"
VERIFY_PAIR="${VERIFY_PAIR:-$HERE/../../leanpolish/verify_pair.py}"
export PATH="$HOME/.elan/bin:$PATH"

shopt -s nullglob
for chunk in "$CHUNK_DIR"/chunk_*.jsonl "$CHUNK_DIR"/agreement_*.jsonl; do
  done_file="${chunk%.jsonl}.kernel_verified.jsonl"
  if [[ -s "$done_file" ]]; then
    echo "[skip] $chunk"
    continue
  fi
  echo "[verify] $chunk ($(date))"
  "$PY" "$VERIFY_PAIR" "$chunk" \
      --root "$ROOT" \
      --project-root "$PROJECT_ROOT" \
      --jobs "$JOBS" --timeout-sec "$TIMEOUT"
done
echo "[verify] all chunks done ($(date))"
