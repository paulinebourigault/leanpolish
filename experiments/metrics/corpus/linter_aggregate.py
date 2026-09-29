#!/usr/bin/env python3
"""Aggregate linter-baseline reports by corpus.

The script scans ``*_linter_report.json`` files, sums byte and token counts,
counts files with removals, and reports full-corpus reduction percentages. It
writes JSON and Markdown summaries for comparison with LeanPolish.

Usage:
  python3 experiments/metrics/corpus/linter_aggregate.py \\
    --corpus mathlib:mathlib_optimization \\
    --corpus goedel:goedel_workbook \\
    --corpus putnam_bench:putnam_bench_proofs \\
    --corpus putnam2025:Putnam2025_AxiomProver \\
    --out linter_baseline.json \\
    --markdown linter_baseline.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def scan(root: Path) -> dict:
    files = 0
    accepted = 0
    bytes_orig = bytes_short = 0
    tok_orig = tok_short = 0
    for rep in root.rglob("*_linter_report.json"):
        try:
            r = json.loads(rep.read_text(errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        files += 1
        bo = int(r.get("bytes_original", 0) or 0)
        bs = int(r.get("bytes_shortened", 0) or 0)
        to = int(r.get("tokens_original", 0) or 0)
        ts = int(r.get("tokens_shortened", 0) or 0)
        bytes_orig += bo
        bytes_short += bs
        tok_orig += to
        tok_short += ts
        if int(r.get("linter_removals", 0) or 0) > 0 and bs < bo:
            accepted += 1
    bytes_pct = (1 - bytes_short / bytes_orig) * 100 if bytes_orig else 0.0
    tok_pct = (1 - tok_short / tok_orig) * 100 if tok_orig else 0.0
    return {
        "files_with_linter_report": files,
        "files_linter_accepted": accepted,
        "bytes_original": bytes_orig,
        "bytes_shortened": bytes_short,
        "bytes_saved": bytes_orig - bytes_short,
        "bytes_reduction_pct": round(bytes_pct, 4),
        "tokens_original": tok_orig,
        "tokens_shortened": tok_short,
        "tokens_saved": tok_orig - tok_short,
        "tokens_reduction_pct": round(tok_pct, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", default=[], required=True,
                    help="name:dir (repeatable)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--markdown", type=Path)
    args = ap.parse_args()

    out = {"corpora": {}}
    rows = []
    for spec in args.corpus:
        name, pth = spec.split(":", 1)
        s = scan(Path(pth))
        out["corpora"][name] = {"source": pth, **s}
        print(f"{name}: {s['files_with_linter_report']} reports,"
              f" {s['files_linter_accepted']} accepted,"
              f" {s['tokens_reduction_pct']}% token reduction"
              f" ({s['bytes_reduction_pct']}% bytes)")
        rows.append((name, s))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"wrote {args.out}")

    if args.markdown:
        lines = ["# linter.unusedTactic baseline (per corpus)\n",
                 "| corpus | files | accepted | bytes orig | bytes short | bytes % | tokens orig | tokens short | tokens % |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, s in rows:
            lines.append(
                f"| {name} | {s['files_with_linter_report']:,} | {s['files_linter_accepted']:,} |"
                f" {s['bytes_original']:,} | {s['bytes_shortened']:,} | {s['bytes_reduction_pct']}% |"
                f" {s['tokens_original']:,} | {s['tokens_shortened']:,} | {s['tokens_reduction_pct']}% |"
            )
        args.markdown.write_text("\n".join(lines) + "\n")
        print(f"wrote {args.markdown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
