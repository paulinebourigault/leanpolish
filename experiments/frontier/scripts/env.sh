#!/usr/bin/env bash
# Shared settings for the frontier-prover hybrid scripts (sourced, not executed).
#   LEANPOLISH_ROOT  root of this archive              (default: three levels above this file)
#   LEAN_PROJECT     Lake project with Mathlib v4.21.0  (default: $LEANPOLISH_ROOT/leanpolish)
#   WORK_DIR         working tree: files/, run_<TAG>/    (default: ./work)
#   REPL_BIN         leanprover-community/repl binary   (default: repl on PATH)
#   ADAPTER          SFT LoRA adapter directory         (default: $LEANPOLISH_ROOT/adapters/deepseek)
#   BASE_MODEL       base model id for the adapter      (default: set inside gen_sites.py)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LEANPOLISH_ROOT="${LEANPOLISH_ROOT:-$(cd "$HERE/../../.." && pwd)}"
export LEAN_PROJECT="${LEAN_PROJECT:-$LEANPOLISH_ROOT/leanpolish}"
export WORK_DIR="$(mkdir -p "${WORK_DIR:-work}" && cd "${WORK_DIR:-work}" && pwd)"
export REPL_BIN="${REPL_BIN:-repl}"
export ADAPTER="${ADAPTER:-$LEANPOLISH_ROOT/adapters/deepseek}"
S="$HERE"                                   # frontier scripts
H="$LEANPOLISH_ROOT/experiments/hybrid/scripts"   # shared hybrid scripts (extract/gen/verify)
F="$WORK_DIR/files"
