#!/usr/bin/env python3
"""Build SFT train/val/eval data for the learning experiment (Table 2).

Train corpora : goedel + mathlib   (accepted rows, strict positive UTF-8 byte width)
Eval corpora  : minif2f, putnam_verified, putnam2025_per_file (reference sites)

Leakage control (same normalisation as experiments/metrics/corpus/dedup_leakage.py):
  - normalize goals by whitespace collapse + strip, hash with SHA-256
  - drop every TRAINING row whose goal hash appears in ANY eval shard
    (checked over goal_type, goal_state and goal_pretty of eval rows)
  - train/val split is by source file, never by row

Prompt format (fixed for all conditions):

    You are editing a Lean 4 proof. Return only a shorter replacement that
    preserves the goal. Return <DELETE> if the fragment should be removed.

    [GOAL]
    {goal_state}

    [LOCAL CONTEXT]
    {context}

    [ORIGINAL FRAGMENT]
    {original}

    [REPLACEMENT]

Target: "{replacement}" or "<DELETE>" when the replacement is empty.

Label-leaking fields (outcome, savings, tokens_*, rank_in_attempt, corpus,
file path, rejection reason, kind) are excluded from the model input.

Outputs (under --out):
  sft_train.jsonl        {prompt, target, file, attempt_id}
  sft_val.jsonl          same schema, held-out source files from train corpora
  eval_sites_<c>.jsonl   full verification metadata + prompt per reference row
  build_stats.json       all counts and filter decisions
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

WS = re.compile(r"\s+")

# Placeholder goal_type values emitted for non-tactic edit classes. They are
# category labels, not goals: they must not participate in goal-hash leakage
# matching, and they must not appear in the model prompt (teacher-produced edit
# categories such as `kind` are excluded from the model input).
PLACEHOLDER_GOAL_RE = re.compile(r"^(cleanup|dead_code|L2_arity\d+_(lemma|prop))$")
NO_GOAL_TEXT = "(no local goal)"


def is_placeholder_goal(s: str) -> bool:
    return bool(PLACEHOLDER_GOAL_RE.match(s.strip()))

PROMPT_TEMPLATE = (
    "You are editing a Lean 4 proof. Return only a shorter replacement that\n"
    "preserves the goal. Return <DELETE> if the fragment should be removed.\n"
    "\n"
    "[GOAL]\n{goal}\n"
    "\n"
    "[LOCAL CONTEXT]\n{context}\n"
    "\n"
    "[ORIGINAL FRAGMENT]\n{original}\n"
    "\n"
    "[REPLACEMENT]\n"
)

DELETE_TOKEN = "<DELETE>"

TRAIN_SHARDS = ["goedel", "mathlib"]
EVAL_SHARDS = ["minif2f", "putnam_verified", "putnam2025_per_file"]

# Kinds verify_pair.py cannot re-elaborate (line-based offsets / empty edits).
SKIP_EVAL_TYPES = {"warning_cleanup", "l2_detection"}


def norm(s: str) -> str:
    return WS.sub(" ", s).strip()


def goal_hash(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()


def iter_shard(shards_root: Path, shard: str):
    files = sorted(glob.glob(str(shards_root / shard / "training_pairs*.jsonl.gz")))
    if not files:
        raise FileNotFoundError(f"no training_pairs*.jsonl.gz under {shards_root/shard}")
    for fn in files:
        with gzip.open(fn, "rt") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def row_goal(row: dict) -> str:
    # Same priority as experiments/metrics/corpus/dedup_leakage.py:load_train_jsonl, but
    # placeholder category labels do not count as goals.
    g = (row.get("goal_type") or row.get("goal_state")
         or row.get("goal_pretty") or "")
    return "" if is_placeholder_goal(g) else g


def savings_bytes(row: dict) -> int:
    return (len(row["original"].encode("utf-8"))
            - len(row["replacement"].encode("utf-8")))


def build_prompt(row: dict, max_goal_chars: int, max_ctx_chars: int) -> str:
    goal = row.get("goal_state") or row.get("goal_pretty") or row.get("goal_type") or ""
    if not goal or is_placeholder_goal(goal):
        goal = NO_GOAL_TEXT
    ctx = row.get("context") or ""
    if len(goal) > max_goal_chars:
        goal = goal[:max_goal_chars] + " …"
    if len(ctx) > max_ctx_chars:
        # keep the tail: it is closest to the rewrite site
        ctx = "… " + ctx[-max_ctx_chars:]
    return PROMPT_TEMPLATE.format(goal=goal, context=ctx, original=row["original"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shards-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--val-file-frac", type=float, default=0.02)
    ap.add_argument("--max-goal-chars", type=int, default=2000)
    ap.add_argument("--max-ctx-chars", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    stats: dict = {"seed": args.seed}

    # ── 1. eval goal hashes (all rows, all goal representations) ────────────
    eval_hashes: set[str] = set()
    eval_rows_by_shard: dict[str, list[dict]] = {}
    for shard in EVAL_SHARDS:
        rows = list(iter_shard(args.shards_root, shard))
        eval_rows_by_shard[shard] = rows
        for r in rows:
            for key in ("goal_type", "goal_state", "goal_pretty"):
                g = r.get(key)
                if g and not is_placeholder_goal(g):
                    eval_hashes.add(goal_hash(g))
    stats["eval_goal_hashes"] = len(eval_hashes)

    # ── 2. training rows: filter + dedup ────────────────────────────────────
    train_rows: list[dict] = []
    counts = Counter()
    seen_triples: set[str] = set()
    for shard in TRAIN_SHARDS:
        for r in iter_shard(args.shards_root, shard):
            counts[f"{shard}_total"] += 1
            if r.get("outcome") != "accepted":
                counts["drop_not_accepted"] += 1
                continue
            if savings_bytes(r) <= 0:
                counts["drop_nonpositive_width"] += 1
                continue
            g = row_goal(r)
            if g and goal_hash(g) in eval_hashes:
                counts["drop_goal_overlap_with_eval"] += 1
                continue
            triple = hashlib.sha256(
                (norm(row_goal(r)) + "\x00" + r["original"] + "\x00" + r["replacement"])
                .encode("utf-8")).hexdigest()
            if triple in seen_triples:
                counts["drop_exact_duplicate_triple"] += 1
                continue
            seen_triples.add(triple)
            r["_shard"] = shard
            train_rows.append(r)
    stats["train_filter_counts"] = dict(counts)
    stats["train_rows_kept"] = len(train_rows)

    # ── 3. file-level train/val split ────────────────────────────────────────
    files = sorted({r["file"] for r in train_rows})
    rng.shuffle(files)
    n_val = max(1, int(len(files) * args.val_file_frac))
    val_files = set(files[:n_val])
    stats["train_files"] = len(files) - n_val
    stats["val_files"] = n_val

    def to_sft(r: dict) -> dict:
        target = r["replacement"] if r["replacement"] else DELETE_TOKEN
        return {
            "prompt": build_prompt(r, args.max_goal_chars, args.max_ctx_chars),
            "target": target,
            "file": r["file"],
            "attempt_id": r["attempt_id"],
            "shard": r["_shard"],
            "type": r["type"],
        }

    n_train = n_val_rows = 0
    with (args.out / "sft_train.jsonl").open("w") as ftr, \
         (args.out / "sft_val.jsonl").open("w") as fva:
        for r in train_rows:
            rec = to_sft(r)
            if r["file"] in val_files:
                fva.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_val_rows += 1
            else:
                ftr.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_train += 1
    stats["sft_train_rows"] = n_train
    stats["sft_val_rows"] = n_val_rows
    stats["train_type_dist"] = dict(Counter(r["type"] for r in train_rows))

    # ── 4. eval site files ───────────────────────────────────────────────────
    eval_stats = {}
    for shard, rows in eval_rows_by_shard.items():
        kept = skipped = 0
        with (args.out / f"eval_sites_{shard}.jsonl").open("w") as f:
            for r in rows:
                if r["type"] in SKIP_EVAL_TYPES:
                    skipped += 1
                    continue
                rec = {
                    "prompt": build_prompt(r, args.max_goal_chars, args.max_ctx_chars),
                    "corpus": shard,
                    "file": r["file"],
                    "start_byte": r["start_byte"],
                    "end_byte": r["end_byte"],
                    "original": r["original"],
                    "reference_replacement": r["replacement"],
                    "content_sha256": r.get("content_sha256"),
                    "type": r["type"],
                    "kind": r.get("kind"),
                    "attempt_id": r["attempt_id"],
                    "goal_hash": goal_hash(row_goal(r)) if row_goal(r) else None,
                    "tokens_original": r.get("tokens_original"),
                    "bytes_original": r.get("bytes_original"),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                kept += 1
        eval_stats[shard] = {
            "reference_rows": len(rows), "eval_sites": kept,
            "skipped_types": skipped,
            "files": len({r["file"] for r in rows}),
            "type_dist": dict(Counter(r["type"] for r in rows)),
        }
    stats["eval"] = eval_stats

    (args.out / "build_stats.json").write_text(json.dumps(stats, indent=2))
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
