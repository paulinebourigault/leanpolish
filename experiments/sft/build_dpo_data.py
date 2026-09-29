#!/usr/bin/env python3
"""Build DPO preference pairs from LeanPolish same-attempt rejected siblings.

For every attempt group in the TRAIN corpora (goedel + mathlib) whose winner
survived the SFT data filters (accepted, positive width, no goal-hash overlap
with any eval shard):
  chosen   = the accepted replacement (empty -> <DELETE>)
  rejected = a rejected sibling's candidate text from the same attempt_id

Hard negatives first: siblings whose err_msg indicates a real kernel/tactic
failure are preferred over parser/unknown-tactic noise (excluded from the
primary set, kept in a separate easy-negatives file for the ablation).
At most --max-neg negatives per attempt (highest rank_in_attempt first —
the closest competitors).

Prompts are built with the SAME builder as the SFT data, so the policy sees
one distribution across SFT and DPO.

Output: dpo_pairs.jsonl {prompt, chosen, rejected, reason_class, attempt_id,
file}, dpo_pairs_easy.jsonl, dpo_stats.json.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import re
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sft_data import (DELETE_TOKEN, EVAL_SHARDS, TRAIN_SHARDS,
                            build_prompt, goal_hash, is_placeholder_goal,
                            iter_shard, row_goal, savings_bytes)

EASY_NEG_RE = re.compile(
    r"unknown tactic|unknown identifier|unexpected token|unknown constant"
    r"|function expected|unexpected identifier", re.I)


def iter_rejected(shards_root: Path, shard: str):
    files = sorted(glob.glob(str(shards_root / shard / "rejected_pairs*.jsonl.gz")))
    files = [f for f in files if f.endswith(".jsonl.gz")]
    for fn in files:
        with gzip.open(fn, "rt") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shards-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-neg", type=int, default=2)
    ap.add_argument("--max-goal-chars", type=int, default=2000)
    ap.add_argument("--max-ctx-chars", type=int, default=1200)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # eval goal hashes — identical discipline to build_sft_data
    eval_hashes: set[str] = set()
    for shard in EVAL_SHARDS:
        for r in iter_shard(args.shards_root, shard):
            for key in ("goal_type", "goal_state", "goal_pretty"):
                g = r.get(key)
                if g and not is_placeholder_goal(g):
                    eval_hashes.add(goal_hash(g))

    # accepted winners passing the SFT filters, keyed by attempt_id
    winners: dict[str, dict] = {}
    for shard in TRAIN_SHARDS:
        for r in iter_shard(args.shards_root, shard):
            if r.get("outcome") != "accepted" or savings_bytes(r) <= 0:
                continue
            g = row_goal(r)
            if g and goal_hash(g) in eval_hashes:
                continue
            winners[r["attempt_id"]] = r

    # rejected siblings joined to surviving winners
    stats = Counter()
    hard_f = (args.out / "dpo_pairs.jsonl").open("w")
    easy_f = (args.out / "dpo_pairs_easy.jsonl").open("w")
    neg_count: Counter = Counter()
    reasons = Counter()
    for shard in TRAIN_SHARDS:
        for r in iter_rejected(args.shards_root, shard):
            aid = r["attempt_id"]
            w = winners.get(aid)
            if w is None:
                stats["no_surviving_winner"] += 1
                continue
            neg = r.get("replacement") or ""
            chosen = w["replacement"] if w["replacement"] else DELETE_TOKEN
            neg_txt = neg if neg else DELETE_TOKEN
            if neg_txt == chosen:
                stats["neg_equals_chosen"] += 1
                continue
            if neg_count[aid] >= args.max_neg:
                stats["over_max_neg"] += 1
                continue
            err = (r.get("err_msg") or "")
            easy = bool(EASY_NEG_RE.search(err))
            reason = "easy_parse" if easy else (
                "timeout" if "timeout" in err.lower() else "kernel_or_tactic")
            reasons[reason] += 1
            rec = {
                "prompt": build_prompt(w, args.max_goal_chars, args.max_ctx_chars),
                "chosen": chosen,
                "rejected": neg_txt,
                "reason_class": reason,
                "attempt_id": aid,
                "file": w["file"],
            }
            (easy_f if easy else hard_f).write(
                json.dumps(rec, ensure_ascii=False) + "\n")
            neg_count[aid] += 1
            stats["pairs_easy" if easy else "pairs_hard"] += 1
    hard_f.close(); easy_f.close()

    out_stats = {
        "winners_surviving_filters": len(winners),
        "attempts_with_pairs": len(neg_count),
        "pair_counts": dict(stats),
        "reason_classes": dict(reasons),
    }
    (args.out / "dpo_stats.json").write_text(json.dumps(out_stats, indent=2))
    print(json.dumps(out_stats, indent=2))


if __name__ == "__main__":
    main()
