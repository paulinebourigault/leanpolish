#!/usr/bin/env bash
# Screen + compose for the controls. usage:
#   c1_c2_compose.sh c1 <corpus> <sites.jsonl> <gens.jsonl> <tag>             frozen few-shot hybrid (tactic sites)
#   c1_c2_compose.sh c2 <corpus> <units.jsonl> <gens_prefix> <model_tag> <variant>  whole-proof rewrite
#     <variant> = orig (LLM rewrite alone) | base (release LeanPolish -> LLM) | lp_rerun (clean LeanPolish -> LLM)
# For c1 the gens come from gen_c1_fewshot.py and the main hybrid's screen_sites.py / compose.py are used
# (greedy / all / all + specificity filter). For c2 the gens come from gen_c2_whole.py (<prefix>_k16.jsonl and
# <prefix>_k4.jsonl); c2_screen.py screens the k=16 pool and compose.py is run for k=4 and k=16.
# Run in $CONTROLS_WORKDIR (default .), which holds files/<corpus>/<variant>/*.lean. Outputs: screen/, compose/, files/.
# Env: LEAN_PROJECT, REPL_BIN, JOBS (default 8).
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; BT="$HERE/../../hybrid/scripts"
cd "${CONTROLS_WORKDIR:-.}"; J=${JOBS:-8}; mkdir -p screen compose
MODE=$1; C=$2; S=$3; G=$4; T=$5; V=${6:-base}
# <corpus> minif2f100 = the fixed 100-file miniF2F subset under files100/minif2f
FR=files; CC=$C; [ "$C" = minif2f100 ] && { FR=files100; CC=minif2f; }
if [ "$MODE" = c1 ]; then
  python3 "$BT/screen_sites.py" --sites $S --gens $G --files-root $FR --out screen/$T.jsonl --jobs $J --cands-per-worker 80 --max-split 12
  for D in greedy all all_qf; do
    QF=""; DD=$D; [ $D = all_qf ] && { QF=--quality-filter; DD=all; }
    python3 "$BT/compose.py" --sites $S --gens $G --verdicts screen/$T.jsonl --decodings $DD $QF --corpus $CC --variant base \
      --outvariant ${T}_$D --files-root $FR --jobs $J --timeout 3600 --report compose/${T}_$D.jsonl
  done
else
  python3 "$HERE/c2_screen.py" --sites $S --gens ${G}_k16.jsonl --files-root $FR --out screen/${T}_${C}_${V}.jsonl --jobs $J
  for K in k16 k4; do
    python3 "$BT/compose.py" --sites $S --gens ${G}_$K.jsonl --verdicts screen/${T}_${C}_${V}.jsonl --decodings all \
      --corpus $CC --variant $V --outvariant ${T}_${K}_${V} --files-root $FR --jobs $J --timeout 3600 \
      --report compose/${T}_${C}_${V}_$K.jsonl
  done
fi
