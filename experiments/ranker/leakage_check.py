#!/usr/bin/env python3
"""Goal-hash overlap between the ranker's training pools and each eval pool
(whitespace-normalised goal_state, same normalisation as experiments/sft/build_sft_data.py).

usage: leakage_check.py OUT.json TRAIN_POOLS[,TRAIN_POOLS...] NAME=EVAL_POOLS ...
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import load_sites, goal_hash
train = {goal_hash(s["goal_state"]) for p in sys.argv[2].split(",") for s in load_sites(p) if s.get("goal_state")}
res = {"train_goal_hashes": len(train)}
for spec in sys.argv[3:]:
    n, p = spec.split("=", 1)
    ss = [s for s in load_sites(p) if s.get("goal_state")]
    ov = sum(goal_hash(s["goal_state"]) in train for s in ss)
    res[n] = {"sites": len(ss), "sites_goal_seen_in_train": ov, "pct": 100 * ov / max(1, len(ss))}
Path(sys.argv[1]).write_text(json.dumps(res, indent=2)); print(json.dumps(res, indent=2))
