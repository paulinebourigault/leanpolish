#!/usr/bin/env bash
# "LLM rewrite -> LeanPolish": run LeanPolish on the composed LLM-rewrite outputs (variant orig).
# usage: post_c2.sh <model_tag> <corpus> <k4|k16> <jobs> [timeout]
# Only files the LLM changed are re-run; for unchanged files the result equals LeanPolish(original).
# Run in $CONTROLS_WORKDIR (default .). Inputs: compose/<model>_<corpus>_orig_<k>.jsonl and
# files/<corpus>/<model>_<k>_orig/. Outputs: files/<corpus>/<model>_<k>_post/ and post/<model>_<corpus>_<k>.jsonl.
set -eu
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${CONTROLS_WORKDIR:-.}"
M=$1; C=$2; K=$3; J=$4; TO=${5:-7200}
FR=files; CC=$C
[ "$C" = minif2f100 ] && { FR=files100; CC=minif2f; }
R=compose/${M}_${C}_orig_$K.jsonl
IN=$(python3 -c "
import json
for l in open('$R'):
    r=json.loads(l)
    if r['n_applied']>0: print('$FR/$CC/${M}_${K}_orig/'+r['file'].split('/')[-1])
")
mkdir -p post
[ -z "$IN" ] && { echo "$M $C $K: no changed files"; exit 0; }
python3 "$HERE/run_leanpolish.py" --inputs $IN --workdir lpwork/${M}_${C}_$K --outdir $FR/$CC/${M}_${K}_post \
   --report post/${M}_${C}_$K.jsonl --timeout $TO --jobs $J
