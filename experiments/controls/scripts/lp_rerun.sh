#!/usr/bin/env bash
# "Clean rerun": LeanPolish alone re-run on the original files of each corpus (single-file mode, no resource
# contention). Run in $CONTROLS_WORKDIR (default .) holding files/<corpus>/orig/*.lean (miniF2F-100 under files100/).
# Outputs: files*/<corpus>/lp_rerun/*.lean and lprerun/<corpus>.jsonl.  Env: LEAN_PROJECT, JOBS (default 4).
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${CONTROLS_WORKDIR:-.}"; J=${JOBS:-4}; mkdir -p lprerun
python3 "$HERE/run_leanpolish.py" --inputs files/putnam_verified/orig/*.lean --workdir lpwork/rerun_pv --outdir files/putnam_verified/lp_rerun --report lprerun/putnam_verified.jsonl --timeout 1800 --jobs $J
python3 "$HERE/run_leanpolish.py" --inputs files100/minif2f/orig/*.lean --workdir lpwork/rerun_mf --outdir files100/minif2f/lp_rerun --report lprerun/minif2f100.jsonl --timeout 1800 --jobs $J
python3 "$HERE/run_leanpolish.py" --inputs files/putnam2025/orig/*.lean --workdir lpwork/rerun_p25 --outdir files/putnam2025/lp_rerun --report lprerun/putnam2025.jsonl --timeout 7200 --jobs $J
