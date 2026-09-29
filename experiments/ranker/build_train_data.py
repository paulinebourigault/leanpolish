#!/usr/bin/env python3
"""Build pointwise ranker training samples from complete-menu TRAINING pools.

One sample per run (non-skipped) menu candidate of a site:
  text        [GOAL]/[ORIGINAL]/[CANDIDATE]      (full model)
  text_nogoal [ORIGINAL]/[CANDIDATE]              (goal-ablated model)
  valid       1 if the candidate closes the goal (kernel-valid)
  best        1 if acceptable (valid, shorter, passes quality gate) with minimal length
No outcome/err/menu-index/wall-time fields enter the model input.

Site sampling: all sites with >=1 valid candidate; sites with 0 valid candidates are
subsampled to at most --zero-valid-ratio x (#sites with >=1 valid).  Leakage control:
sites whose whitespace-normalised goal hash appears in any eval pool are dropped.
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import annotate, cand_text, goal_hash, load_sites  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train-pools", nargs="+", required=True)
    ap.add_argument("--eval-pools", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--zero-valid-ratio", type=float, default=0.5)
    ap.add_argument("--max-sites", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    eval_h = set()
    for p in args.eval_pools:
        for s in load_sites(p):
            if s.get("goal_state"):
                eval_h.add(goal_hash(s["goal_state"]))
    sites = [annotate(s) for p in args.train_pools for s in load_sites(p)]
    st = Counter(sites_total=len(sites))
    kept = []
    for s in sites:
        if not s["_cands"]:
            st["no_run_candidates"] += 1
            continue
        if s.get("goal_state") and goal_hash(s["goal_state"]) in eval_h:
            st["dropped_goal_overlap_eval"] += 1
            continue
        kept.append(s)
    pos = [s for s in kept if s["n_valid"] > 0]
    zero = [s for s in kept if s["n_valid"] == 0]
    rng.shuffle(zero)
    zero = zero[: int(args.zero_valid_ratio * len(pos))]
    use = pos + zero
    rng.shuffle(use)
    if args.max_sites:
        use = use[: args.max_sites]
    st.update(sites_with_valid=len(pos), zero_valid_sites_used=len(zero), sites_used=len(use))
    samples = []
    for s in use:
        for c in s["_cands"]:
            samples.append({
                "site": f"{s['file']}|{s['start_byte']}",
                "text": cand_text(s, c, True),
                "text_nogoal": cand_text(s, c, False),
                "valid": int(c["is_valid"]), "best": int(c["is_best"]),
            })
    rng.shuffle(samples)
    st["samples"] = len(samples)
    st["pos_valid"] = sum(x["valid"] for x in samples)
    st["pos_best"] = sum(x["best"] for x in samples)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for x in samples:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    Path(args.out).with_suffix(".stats.json").write_text(json.dumps(st, indent=2))
    print(json.dumps(st, indent=2))


if __name__ == "__main__":
    main()
