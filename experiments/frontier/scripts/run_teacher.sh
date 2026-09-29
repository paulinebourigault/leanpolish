#!/usr/bin/env bash
# Symbolic pass (LeanPolish, default configuration) on each staged file, single-file mode,
# 7,200 s per file (Seed-Prover B2: 14,400 s). Files run concurrently; logs in $WORK_DIR/logs.
source "$(dirname "$0")/env.sh"
mkdir -p "$WORK_DIR/logs"
LP="$LEANPOLISH_ROOT/leanpolish/leanpolish.py"
cd "$LEAN_PROJECT"
for f in $F/seed/lp/{A1,A2,A4,A6,B4}.lean $F/aristotle/lp/{P3,P5}.lean; do
  n=$(basename $(dirname $(dirname $f)))_$(basename $f .lean)
  python3 "$LP" "$f" --timeout 7200 > "$WORK_DIR/logs/teacher_$n.log" 2>&1 < /dev/null &
done
python3 "$LP" $F/seed/lp/B2.lean --timeout 14400 > "$WORK_DIR/logs/teacher_seed_B2.log" 2>&1 < /dev/null &
wait
