#!/usr/bin/env python3
"""Label-stability check: compare per-candidate outcomes of the same files run twice
(full-parallelism run vs a low-parallelism re-run with more cores per process).

usage: compare_rerun.py --a POOLS_A --b POOLS_B --out OUT.json  (writes results/label_stability_rerun.json)
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import load_sites

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True); ap.add_argument("--b", required=True); ap.add_argument("--out", required=True)
args = ap.parse_args()
def idx(p):
    d = {}
    for s in load_sites(p):
        d[(Path(s["file"]).name, s["start_byte"], s["end_byte"])] = s
    return d
A, B = idx(args.a), idx(args.b)
files_b = {k[0] for k in B}
common = [k for k in B if k in A]
onlyA = [k for k in A if k[0] in files_b and k not in B]
c = Counter(); flips = Counter()
for k in common:
    ca = {x["menu_idx"]: x for x in A[k]["candidates"]}
    cb = {x["menu_idx"]: x for x in B[k]["candidates"]}
    c["sites"] += 1
    c["same_chosen"] += A[k].get("chosen_idx") == B[k].get("chosen_idx")
    for i in ca:
        if i in cb and not ca[i].get("skipped"):
            c["cands"] += 1
            if ca[i]["valid"] == cb[i]["valid"]:
                c["valid_agree"] += 1
            else:
                flips[(ca[i]["menu_name"], ca[i]["outcome"], cb[i]["outcome"])] += 1
            c["timeouts_a"] += bool(ca[i].get("timed_out")); c["timeouts_b"] += bool(cb[i].get("timed_out"))
res = {"files_rerun": len(files_b), "sites_rerun": len(B), "sites_common": len(common),
       "sites_only_in_production_for_rerun_files": len(onlyA),
       "sites_only_in_rerun": len([k for k in B if k not in A]), **c,
       "valid_agreement": c["valid_agree"] / max(1, c["cands"]),
       "chosen_agreement": c["same_chosen"] / max(1, c["sites"]),
       "flips": {" | ".join(k): v for k, v in flips.most_common()}}
Path(args.out).write_text(json.dumps(res, indent=2)); print(json.dumps(res, indent=2))
