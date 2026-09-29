#!/usr/bin/env python3
"""Collect G3 generalization-gate statistics on sampled source files.

The script samples files from each requested corpus, runs the LeanPolish binary,
and aggregates L2 group counts, G3 veto counts, byte savings, and veto reasons.
It writes a JSON summary for release tables or audits.

Usage:
  LEAN_PROJECT=<release>/leanpolish python3 experiments/metrics/corpus/g3_sample.py \\
      --corpus goedel:goedel_workbook:2000 \\
      --corpus mathlib:.lake/packages/mathlib/Mathlib:300 \\
      --workers 16 --timeout 600 \\
      --seed 42 \\
      --out g3_sample.json

Corpus paths are relative to LEAN_PROJECT (the built Lake project; default <release>/leanpolish).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
from pathlib import Path

REPO_ROOT = Path(os.environ.get("LEAN_PROJECT", Path(__file__).resolve().parents[3] / "leanpolish"))
BINARY = REPO_ROOT / ".lake" / "build" / "bin" / "LeanPolish"

JSON_RE = re.compile(r"^\[JSON\] (.+)$", re.MULTILINE)
G3_RE = re.compile(r"^\[L2_G3\].*— (g3_no_generalization_\d+ge\d+)\b", re.MULTILINE)


def run_one(file_rel: str, timeout_s: int) -> dict:
    cmd = ["lake", "env", str(BINARY), file_rel]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO_ROOT),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"file": file_rel, "_failed": "timeout", "elapsed": time.time() - t0}
    elapsed = time.time() - t0
    out = proc.stdout
    js = JSON_RE.findall(out)
    g3_lines = G3_RE.findall(out)
    if not js:
        return {
            "file": file_rel, "_failed": "no_json", "elapsed": elapsed,
            "stderr_tail": proc.stderr[-400:],
        }
    j = json.loads(js[-1])
    j["file"] = file_rel
    j["elapsed"] = elapsed
    j["g3_reasons"] = g3_lines
    return j


def pick(root: Path, n: int, seed: int) -> list[str]:
    files = sorted(p for p in root.rglob("*.lean") if "_shortened" not in p.name
                                                  and "_quarantine" not in str(p))
    rng = random.Random(seed)
    rng.shuffle(files)
    return [str(f.relative_to(REPO_ROOT)) for f in files[:n]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True,
                    help="name:dir:N triples")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    summary: dict[str, dict] = {}
    for spec in args.corpus:
        name, dirpath, n_str = spec.split(":")
        n = int(n_str)
        files = pick(REPO_ROOT / dirpath, n, args.seed)
        print(f"[{name}] sampling {len(files)} files from {dirpath}")
        results: list[dict] = []
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(run_one, f, args.timeout): f for f in files}
            for i, fut in enumerate(as_completed(futs), 1):
                r = fut.result()
                results.append(r)
                if i % 50 == 0 or i == len(files):
                    print(f"  [{name}] {i}/{len(files)}", flush=True)
        l2_groups = sum(int(r.get("l2_groups", 0)) for r in results)
        l2_applied = sum(int(r.get("l2_antiun_applied", 0)) for r in results)
        l2_g3 = sum(int(r.get("l2_g3_rejected", 0)) for r in results)
        bytes_orig = sum(int(r.get("bytes_original", 0)) for r in results)
        bytes_short = sum(int(r.get("bytes_shortened", 0)) for r in results)
        reasons: dict[str, int] = {}
        for r in results:
            for g in r.get("g3_reasons", []):
                reasons[g] = reasons.get(g, 0) + 1
        n_failed = sum(1 for r in results if r.get("_failed"))
        n_with_l2 = sum(1 for r in results if int(r.get("l2_groups", 0)) > 0)
        s = {
            "files_sampled": len(results),
            "files_failed": n_failed,
            "files_with_l2_group": n_with_l2,
            "bytes_original_sum": bytes_orig,
            "bytes_shortened_sum": bytes_short,
            "bytes_saved_sum": bytes_orig - bytes_short,
            "savings_pct": ((bytes_orig - bytes_short) / bytes_orig) if bytes_orig else 0.0,
            "l2_groups_total": l2_groups,
            "l2_antiun_applied_total": l2_applied,
            "l2_g3_rejected_total": l2_g3,
            "g3_veto_rate": (l2_g3 / l2_groups) if l2_groups else 0.0,
            "g3_reason_examples_top10": dict(sorted(reasons.items(),
                                                     key=lambda x: -x[1])[:10]),
        }
        summary[name] = s
        print(f"[{name}] DONE: groups={l2_groups} applied={l2_applied} "
              f"g3_veto={l2_g3} ({s['g3_veto_rate']:.1%}) "
              f"savings={s['savings_pct']:.1%}")
        # also dump per-file results for later inspection
        per_file = args.out.with_name(f"{args.out.stem}_{name}_per_file.jsonl")
        per_file.parent.mkdir(parents=True, exist_ok=True)
        with open(per_file, "w") as f:
            for r in results:
                f.write(json.dumps(r) + "\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
