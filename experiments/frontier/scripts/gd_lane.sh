#!/usr/bin/env bash
# Extended lane ("ext"): also fully verify candidates whose REPL replay left different goals
# than the original (screen verdict fail_goals_differ); such edits can still be valid when later
# tactics absorb the difference. A fresh `lake env lean` run is the only arbiter. Re-combines with
# the union of verdicts into run_<TAG>/final_ext/ and combine_ext.json.
# usage: gd_lane.sh TAG JOBS corpus/NAME ...      (after pipeline.sh TAG ...)
set -uo pipefail
TAG=$1; JOBS=$2; shift 2
source "$(dirname "$0")/env.sh"
W=$WORK_DIR/run_$TAG; cd "$LEAN_PROJECT"
python3 $S/make_verify_rows.py $W/sites.jsonl $W/screen.jsonl $W/verify_in_gd.jsonl --goals-differ
python3 $H/verify_full.py --inp $W/verify_in_gd.jsonl --out $W/verdicts_gd.jsonl --files-root $F \
    --project "$LEAN_PROJECT" --jobs $JOBS --timeout 3600
cat $W/verdicts.jsonl $W/verdicts_gd.jsonl > $W/verdicts_ext.jsonl
python3 $S/combine.py --sites $W/sites.jsonl --gens $W/gens.jsonl --verdicts $W/verdicts_ext.jsonl \
    --teacher-edits $WORK_DIR/teacher_edits.json --files-root $F --project "$LEAN_PROJECT" \
    --final-root $W/final_ext --only "$@" --out $W/combine_ext.json
