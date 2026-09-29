#!/bin/bash
# End-to-end self-training (one round of verified self-generated edits); stages run sequentially.
# Run from a working directory containing:
#   files/            Lean sources (goedel_workbook/*, held-out corpora) the sites refer to
#   data/             sft_train.jsonl, sft_val.jsonl, eval_sites_<corpus>.jsonl, teacher_spans.json,
#                     selected_files.json, rest_600.stems (see ../data/)
#   sites/            sites_putnam_verified_base.jsonl, sites_putnam2025_base.jsonl (hybrid sites)
# Environment: BASE_MODEL (DeepSeek-Prover-V2-7B path or hub id), R1_ADAPTER (round-1 SFT adapter,
#   i.e. the released SFT adapter), CKPT_DIR (default ./ckpt), LEAN_PROJECT, FILES_ROOT, REPL_BIN,
#   SHARDS_ROOT (see run_pipeline.sh / heldout_hashes.py).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${LEANPOLISH_ROOT:-$(cd "$HERE/../../.." && pwd)}"
HYB="$ROOT/experiments/hybrid/scripts"
BASE_MODEL="${BASE_MODEL:-deepseek-ai/DeepSeek-Prover-V2-7B}"
R1_ADAPTER="${R1_ADAPTER:?set R1_ADAPTER to the round-1 SFT adapter}"
CKPT_DIR="${CKPT_DIR:-ckpt}"
LEAN_PROJECT="${LEAN_PROJECT:-$ROOT/leanpolish}"
FILES_ROOT="${FILES_ROOT:-$PWD/files}"
REPL_BIN="${REPL_BIN:-repl/.lake/build/bin/repl}"
export LEAN_PROJECT FILES_ROOT REPL_BIN
mkdir -p sites gens verdicts out "$CKPT_DIR"

# 1. held-out evaluation sites and leakage hashes
DATA_DIR=data python3 "$HERE/make_eval_sites.py"
python3 "$HERE/heldout_hashes.py"

# 2. training sites on the 1,000 selected Goedel training files (not covered by teacher edits)
#    (verify_subset_400.stems + rest_600.stems = the 1,000 files chosen by select_files.py)
STEMS="$(cat data/verify_subset_400.stems) $(cat data/rest_600.stems)"
python3 "$HERE/extract_sites.py" --files-root "$FILES_ROOT" --corpus goedel --variant orig \
  --project "$LEAN_PROJECT" --repl "$REPL_BIN" --jobs 8 --only $STEMS --out sites/train_sites_raw.jsonl
python3 "$HERE/filter_train_sites.py" sites/train_sites_raw.jsonl data/teacher_spans.json sites/train_sites.jsonl "$FILES_ROOT"

# 3. round-1 generation on training + evaluation sites, split by site set
python3 "$HYB/gen_sites.py" --base "$BASE_MODEL" --adapter "$R1_ADAPTER" \
  --sites sites/train_sites.jsonl sites/eval_teacher.jsonl sites/sites_putnam_verified_base.jsonl sites/sites_putnam2025_base.jsonl \
  --out gens/gens_r1_all.jsonl --gpu-mem-util 0.85
python3 - <<'PY'
import json
tr = {json.loads(l)['site_id'] for l in open('sites/train_sites.jsonl')}
with open('gens/gens_r1_train.jsonl', 'w') as a, open('gens/gens_r1_eval.jsonl', 'w') as b:
    for l in open('gens/gens_r1_all.jsonl'):
        (a if json.loads(l)['site_id'] in tr else b).write(l)
PY

# 4. verify round-1 candidates on training sites; build new edits (NAIVE and SEL variants)
bash "$HERE/run_pipeline.sh" train sites/train_sites.jsonl gens/gens_r1_train.jsonl 12 12
python3 "$HERE/build_new_edits.py" --sites sites/train_sites.jsonl --gens gens/gens_r1_train.jsonl \
  --verify verdicts/verify_train.jsonl --screen verdicts/screen_train.jsonl --sft-train data/sft_train.jsonl \
  --hashes data/heldout_goal_hashes.json --outdir out --files-root "$FILES_ROOT"

# 5. round 2: continue from round 1 for one epoch on new edits + replay; generate on evaluation sites
for V in naive sel; do
  python3 "$HERE/train_continue.py" --init-adapter "$R1_ADAPTER" --epochs 1 --seed 42 \
    --train out/r2_${V}_train.jsonl --val data/sft_val.jsonl --model "$BASE_MODEL" --out "$CKPT_DIR/r2_$V"
  python3 "$HYB/gen_sites.py" --base "$BASE_MODEL" --adapter "$CKPT_DIR/r2_$V" \
    --sites sites/eval_teacher.jsonl sites/sites_putnam_verified_base.jsonl sites/sites_putnam2025_base.jsonl \
    --out gens/gens_r2${V}_eval.jsonl --gpu-mem-util 0.85
done

# 6. evaluation: screen + exact-verify all three models' candidates per evaluation set
python3 - <<'PY'
import json
for fam in ('tactic', 'deletion'):
    with open(f'sites/eval_teacher_{fam}.jsonl', 'w') as f:
        for l in open('sites/eval_teacher.jsonl'):
            if json.loads(l).get('family') == fam: f.write(l)
PY
G="gens/gens_r1_eval.jsonl gens/gens_r2naive_eval.jsonl gens/gens_r2sel_eval.jsonl"
bash "$HERE/run_pipeline.sh" evalT sites/eval_teacher_tactic.jsonl "$G" 12 12 evalT
bash "$HERE/run_pipeline.sh" evalD sites/eval_teacher_deletion.jsonl "$G" 12 12 evalD
bash "$HERE/run_pipeline.sh" btPV sites/sites_putnam_verified_base.jsonl "$G" 12 12 btPV
bash "$HERE/run_pipeline.sh" btAX sites/sites_putnam2025_base.jsonl "$G" 12 12 btAX

# 7. metrics (paired file-level bootstrap vs round 1)
python3 "$HERE/eval_metrics.py" --sites sites/eval_teacher.jsonl sites/sites_putnam_verified_base.jsonl sites/sites_putnam2025_base.jsonl \
  --verify verdicts/verify_evalT.jsonl verdicts/verify_evalD.jsonl verdicts/verify_btPV.jsonl verdicts/verify_btAX.jsonl \
  --model r1=gens/gens_r1_eval.jsonl --model r2naive=gens/gens_r2naive_eval.jsonl --model r2sel=gens/gens_r2sel_eval.jsonl \
  --ref r1 --out metrics.json
