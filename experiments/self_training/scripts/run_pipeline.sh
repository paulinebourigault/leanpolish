#!/bin/bash
# Screen -> queue -> exact verification for one set of generated candidates.
#   run_pipeline.sh NAME SITES "GENS..." [JOBS_SCREEN] [JOBS_VERIFY] [VERIFY_NAME]
# Stages: screen_sites.py (REPL pre-filter) -> prep_verify.py -> verify_full.py (fresh `lake env lean`).
# Resumable; the verify file can be shared across models (keyed by site_id+replacement).
# Run from the working directory holding sites/, gens/, verdicts/.
# Environment: LEAN_PROJECT (Lake project, default <release>/leanpolish), FILES_ROOT (Lean sources
#   the sites refer to, default ./files), REPL_BIN (leanprover-community/repl binary).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${LEANPOLISH_ROOT:-$(cd "$HERE/../../.." && pwd)}"
LEAN_PROJECT="${LEAN_PROJECT:-$ROOT/leanpolish}"
FILES_ROOT="${FILES_ROOT:-$PWD/files}"
REPL_BIN="${REPL_BIN:-repl/.lake/build/bin/repl}"
N=$1; SITES=$2; GENS=$3; JS=${4:-12}; JV=${5:-12}; VN=${6:-$1}
mkdir -p verdicts
python3 "$HERE/screen_sites.py" --sites "$SITES" --gens $GENS --files-root "$FILES_ROOT" \
  --project "$LEAN_PROJECT" --repl "$REPL_BIN" --jobs "$JS" --out "verdicts/screen_$N.jsonl"
python3 "$HERE/prep_verify.py" --sites "$SITES" --screen "verdicts/screen_$N.jsonl" \
  --out "verdicts/queue_$N.jsonl" --done "verdicts/verify_$VN.jsonl"
python3 "$HERE/verify_full.py" --inp "verdicts/queue_$N.jsonl" --out "verdicts/verify_$VN.jsonl" \
  --files-root "$FILES_ROOT" --project "$LEAN_PROJECT" --jobs "$JV" --timeout 600
