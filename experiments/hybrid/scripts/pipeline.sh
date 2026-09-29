#!/usr/bin/env bash
# Verified hybrid (Algorithm 2), screen + compose stage.
# usage: pipeline.sh <corpus> <variant> <screen_jobs> <compose_jobs>
#   <variant> = base  (LeanPolish-shortened files -> "hybrid" lanes)
#             | orig  (original files -> "neural alone" lanes)
# Run from the hybrid working directory ($HYBRID_WORKDIR, default: current directory), which holds
#   files/<corpus>/<variant>/*.lean   input files (make_bases.py)
#   sites_<corpus>_<variant>.jsonl    tactic sites (extract_sites.py)
#   gens/<corpus>_<variant>.jsonl     editor proposals (gen_sites.py)
# Outputs: screen/<corpus>_<variant>.jsonl (REPL pre-screen), compose/*.jsonl (per-file reports) and
#   files/<corpus>/{hybrid|neural}_{greedy,all,all_qf}/*.lean, each compiled with a fresh `lake env lean`.
# Env: LEAN_PROJECT (Lake project, default <release>/leanpolish), REPL_BIN (default `repl`).
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HYBRID_WORKDIR:-.}"
C=$1; V=$2; SJ=$3; CJ=$4
G=gens/${C}_${V}.jsonl; S=sites_${C}_${V}.jsonl
mkdir -p screen compose
python3 "$HERE/screen_sites.py" --sites $S --gens $G --out screen/${C}_${V}.jsonl --jobs $SJ \
   --cands-per-worker 80 --max-split 12
tag=$([ "$V" = base ] && echo hybrid || echo neural)
python3 "$HERE/compose.py" --sites $S --gens $G --verdicts screen/${C}_${V}.jsonl --decodings greedy --corpus $C --variant $V \
   --outvariant ${tag}_greedy --jobs $CJ --report compose/${C}_${V}_greedy.jsonl &
python3 "$HERE/compose.py" --sites $S --gens $G --verdicts screen/${C}_${V}.jsonl --decodings all --corpus $C --variant $V \
   --outvariant ${tag}_all --jobs $CJ --report compose/${C}_${V}_all.jsonl &
python3 "$HERE/compose.py" --sites $S --gens $G --verdicts screen/${C}_${V}.jsonl --decodings all --quality-filter --corpus $C --variant $V \
   --outvariant ${tag}_all_qf --jobs $CJ --report compose/${C}_${V}_all_qf.jsonl &
wait
echo "compose done: $C $V"
