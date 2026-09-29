#!/usr/bin/env python3
"""Check exact and normalized goal-state overlap across corpora.

The audit compares training and held-out corpora by normalized ``goal_before``
strings and reports pairwise intersections, corpus sizes, and Jaccard scores.

Usage:
  python3 experiments/metrics/corpus/dedup_leakage.py \\
      --train goedel:training_pairs.jsonl \\
      --eval minif2f:goedel_eval/minif2f_verified \\
      --eval putnam:goedel_eval/putnam_verified \\
      --out dedup_leakage.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


WS = re.compile(r"\s+")


def norm(s: str) -> str:
    return WS.sub(" ", s).strip()


def goal_hash(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()


def load_train_jsonl(p: Path) -> set[str]:
    hashes: set[str] = set()
    with open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            g = (obj.get("goal_type") or obj.get("goal_state")
                 or obj.get("goal_pretty") or obj.get("goal_before")
                 or obj.get("input") or "")
            if g:
                hashes.add(goal_hash(g))
    return hashes


def load_eval_dir(p: Path) -> set[str]:
    """Eval split: a tree of *.lean files. Hash each `:= by` body's goal
    by treating the source between `theorem ... : <type> := by` as the goal."""
    hashes: set[str] = set()
    type_re = re.compile(
        r"(?:theorem|lemma|example)\b[^:]*:\s*(.*?)\s*:= by",
        re.DOTALL,
    )
    for f in sorted(p.rglob("*.lean")):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in type_re.finditer(text):
            g = m.group(1)
            if g:
                hashes.add(goal_hash(g))
    return hashes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="append", default=[],
                    help="name:path.jsonl")
    ap.add_argument("--eval", action="append", default=[],
                    help="name:dir (Lean source tree)")
    ap.add_argument("--eval-jsonl", action="append", default=[],
                    help="name:path.jsonl (held-out training_pairs JSONL)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    sets: dict[str, set[str]] = {}
    for spec in args.train:
        name, pth = spec.split(":", 1)
        sets[name] = load_train_jsonl(Path(pth))
        print(f"train  {name}: {len(sets[name])} unique goal hashes")
    for spec in args.eval:
        name, pth = spec.split(":", 1)
        sets[name] = load_eval_dir(Path(pth))
        print(f"eval   {name}: {len(sets[name])} unique goal hashes")
    for spec in args.eval_jsonl:
        name, pth = spec.split(":", 1)
        sets[name] = load_train_jsonl(Path(pth))
        print(f"eval-j {name}: {len(sets[name])} unique goal hashes")

    overlaps: dict[str, dict] = {}
    names = list(sets.keys())
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            inter = sets[a] & sets[b]
            union = sets[a] | sets[b]
            overlaps[f"{a}__vs__{b}"] = {
                "size_a": len(sets[a]),
                "size_b": len(sets[b]),
                "intersection": len(inter),
                "union": len(union),
                "jaccard": (len(inter) / len(union)) if union else 0.0,
            }
            print(f"{a} ∩ {b}: {len(inter)} (jaccard {overlaps[f'{a}__vs__{b}']['jaccard']:.4f})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "sizes": {k: len(v) for k, v in sets.items()},
        "overlaps": overlaps,
    }, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
