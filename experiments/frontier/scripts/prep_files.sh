#!/usr/bin/env bash
# Stage the frontier-prover inputs (unmodified bytes) into $WORK_DIR/files.
# usage: SEED_SRC=<unzipped Seed-Prover Putnam2025 dir> ARISTOTLE_SRC=<harmonic-ai/IMO2025 checkout> prep_files.sh
#   Seed-Prover 1.5: Putnam2025.zip from ByteDance-Seed/Seed-Prover @ ac61b7dde308c889c44483e91216045990c10c63
#   Aristotle:       harmonic-ai/IMO2025 @ 72b62405a176a7eaeadb335a7fa6ee80b6667161
# Compare the printed sha256 values with PROVENANCE.md.
set -e
source "$(dirname "$0")/env.sh"
: "${SEED_SRC:?set SEED_SRC}"; : "${ARISTOTLE_SRC:?set ARISTOTLE_SRC}"
mkdir -p $F/seed/orig $F/aristotle/orig $F/seed/lp $F/aristotle/lp
for p in a1 a2 a4 a6 b2 b4; do
  cp "$SEED_SRC/Putnam2025/putnam_2025_$p.lean" $F/seed/orig/${p^^}.lean
done
for p in P3 P5; do cp "$ARISTOTLE_SRC/HarmonicLean/IMO2025$p.lean" $F/aristotle/orig/$p.lean; done
# working copies for the symbolic pass (leanpolish.py writes <stem>_shortened.lean + _report.json beside them)
cp $F/seed/orig/*.lean $F/seed/lp/; cp $F/aristotle/orig/*.lean $F/aristotle/lp/
sha256sum $F/*/orig/*.lean
