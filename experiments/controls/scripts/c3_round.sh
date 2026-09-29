#!/usr/bin/env bash
# Alternation (LeanPolish <-> trained editor), one round r >= 1.
# usage: c3_round.sh <corpus_tag> <r>
# Inputs: $FR/<corpus>/c3_r{r-1}/*.lean (round 0 = main hybrid outputs). Steps: LeanPolish on every file ->
# tactic sites (extract_sites.py) -> trained editor (gen_sites.py: greedy + 4 samples) -> screen -> compose.
# Outputs: $FR/<corpus>/c3_r<r>lp/ (after LeanPolish), $FR/<corpus>/c3_r<r>/ (after the editor), c3/*.jsonl.
# Env: CONTROLS_WORKDIR (default .), LEAN_PROJECT, REPL_BIN, MODEL (default deepseek-ai/DeepSeek-Prover-V2-7B),
#      ADAPTER (trained LoRA adapter, HF adapters/), JOBS (default 8).
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; BT="$HERE/../../hybrid/scripts"
cd "${CONTROLS_WORKDIR:-.}"; J=${JOBS:-8}
C=$1; r=$2; p=$((r-1))
FR=files; CC=$C
[ "$C" = minif2f100 ] && { FR=files100; CC=minif2f; }
mkdir -p c3 screen compose
python3 "$HERE/run_leanpolish.py" --inputs $FR/$CC/c3_r$p/*.lean --workdir lpwork/c3_${C}_r$r \
  --outdir $FR/$CC/c3_r${r}lp --report c3/lp_${C}_r$r.jsonl --timeout 7200 --jobs $J
python3 "$BT/extract_sites.py" --files-root $FR --corpus $CC --variant c3_r${r}lp --jobs $J --out c3/sites_${C}_r$r.jsonl
python3 "$BT/gen_sites.py" --base "${MODEL:-deepseek-ai/DeepSeek-Prover-V2-7B}" --adapter "$ADAPTER" \
  --sites c3/sites_${C}_r$r.jsonl --out c3/gens_${C}_r$r.jsonl
python3 "$BT/screen_sites.py" --sites c3/sites_${C}_r$r.jsonl --gens c3/gens_${C}_r$r.jsonl --files-root $FR \
  --out screen/c3_${C}_r$r.jsonl --jobs $J --cands-per-worker 80 --max-split 12
python3 "$BT/compose.py" --sites c3/sites_${C}_r$r.jsonl --gens c3/gens_${C}_r$r.jsonl --verdicts screen/c3_${C}_r$r.jsonl \
  --decodings all --corpus $CC --variant c3_r${r}lp --outvariant c3_r$r --files-root $FR --jobs $J \
  --report compose/c3_${C}_r$r.jsonl
