#!/usr/bin/env python3
"""Compute per-corpus statistics from released shard layouts.

The script handles both data layouts produced by the LeanPolish pipeline:

  Layout A (per-file): <corpus_dir>/<basename>_report.json
      Produced by leanpolish.py one report per source file.
      Mathlib, putnam_bench, the per-file Putnam2025 runs use this.

  Layout B (orchestrator pool): _<corpus>/summary.json
                                 _<corpus>/training_pairs.jsonl
                                 _<corpus>/training_pairs.clean.jsonl   (optional)
                                 _<corpus>/rejected_pairs.jsonl
      Produced by run_worker_pool.py for batch runs.
      Goedel-Workbook, _minif2f_verified, _putnam_verified and
      _putnam2025_axiomprover use this.

Output: a JSON dictionary keyed by corpus name and an optional Markdown summary
table for reporting.

CLI:
  python experiments/metrics/corpus/corpus_stats_v2.py \\
      --layoutA name:dir [--layoutA name:dir ...] \\
      --layoutB name:dir [--layoutB name:dir ...] \\
      --out path.json --markdown path.md
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics
import sys
from pathlib import Path


def _percentile(values, q):
    if not values:
        return 0
    s = sorted(values)
    k = (len(s) - 1) * q
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def _scan_layout_a(corpus_dir: Path) -> dict:
    """Aggregate per-file *_report.json files (excluding *_linter_report.json)."""
    files_total = 0
    files_accepted = 0
    files_verified = 0
    bytes_saved = []
    pairs_total = 0
    l2_groups = 0
    l2_applied = 0
    l2_g3_rejected = 0
    warning_cleanups = 0
    bytes_orig_sum = 0
    bytes_short_sum = 0
    for p in corpus_dir.rglob("*_report.json"):
        # skip the dedicated linter baseline reports
        if p.name.endswith("_linter_report.json"):
            continue
        try:
            r = json.loads(p.read_text())
        except Exception:
            continue
        files_total += 1
        if r.get("verified"):
            files_verified += 1
        if r.get("accepted"):
            # explicit accept flag (preferred when present)
            pass  # counted via bytes_saved>0 below to keep semantics consistent
        bs = r.get("bytes_saved", 0) or 0
        if bs > 0:
            bytes_saved.append(bs)
            files_accepted += 1
        tp = r.get("training_pairs", 0)
        if isinstance(tp, list):
            tp = len(tp)
        pairs_total += int(tp or 0)
        l2_groups += int(r.get("l2_groups", 0) or 0)
        l2_applied += int(r.get("l2_antiun_applied", 0) or 0)
        l2_g3_rejected += int(r.get("l2_g3_rejected", 0) or 0)
        warning_cleanups += int(r.get("warning_cleanups", 0) or 0)
        bytes_orig_sum += int(r.get("bytes_original", 0) or 0)
        bytes_short_sum += int(r.get("bytes_shortened", 0) or 0)
    return _summarise(
        layout="A (per-file _report.json)",
        files_total=files_total,
        files_verified=files_verified,
        files_accepted=files_accepted,
        bytes_saved=bytes_saved,
        bytes_orig_sum=bytes_orig_sum,
        bytes_short_sum=bytes_short_sum,
        pairs=pairs_total,
        rejected=0,
        l2_groups=l2_groups,
        l2_applied=l2_applied,
        l2_g3_rejected=l2_g3_rejected,
        warning_cleanups=warning_cleanups,
    )


def _scan_layout_b(pool_dir: Path) -> dict:
    """Aggregate orchestrator-pool outputs."""
    summary_path = pool_dir / "summary.json"
    files_total = 0
    files_done = 0
    files_failed = 0
    if summary_path.exists():
        try:
            s = json.loads(summary_path.read_text())
            files_total = int(s.get("files_total", 0) or 0)
            files_done = int(s.get("files_done", 0) or 0)
            files_failed = int(s.get("files_failed", 0) or 0)
        except Exception:
            pass

    def _count_lines(p: Path) -> int:
        if not p.exists():
            return 0
        n = 0
        with p.open() as fh:
            for _ in fh:
                n += 1
        return n

    pairs_clean = _count_lines(pool_dir / "training_pairs.clean.jsonl")
    pairs_raw = _count_lines(pool_dir / "training_pairs.jsonl")
    pairs_rejected = _count_lines(pool_dir / "rejected_pairs.jsonl")
    pairs_style_reg = _count_lines(pool_dir / "training_pairs.style_regressions.jsonl")
    pairs = pairs_clean if pairs_clean > 0 else pairs_raw

    # try to recover bytes_saved + l2 stats from per-file logs (if any sidecar reports exist)
    bytes_saved = []
    bytes_orig_sum = 0
    bytes_short_sum = 0
    files_accepted = 0
    files_verified = files_done
    l2_groups = 0
    l2_applied = 0
    l2_g3_rejected = 0
    warning_cleanups = 0

    # parse training_pairs.jsonl rows for per-row savings (if schema_v2)
    if (pool_dir / "training_pairs.jsonl").exists():
        seen_files = set()
        with (pool_dir / "training_pairs.jsonl").open() as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                original = row.get("original")
                replacement = row.get("replacement")
                if isinstance(original, str) and isinstance(replacement, str):
                    row_savings = len(original.encode("utf-8")) - len(replacement.encode("utf-8"))
                    if row_savings > 0:
                        bytes_saved.append(row_savings)
                if "bytes_original" in row:
                    bytes_orig_sum += int(row.get("bytes_original", 0) or 0)
                if "bytes_shortened" in row:
                    bytes_short_sum += int(row.get("bytes_shortened", 0) or 0)
                f = row.get("file") or row.get("source_file")
                if f:
                    seen_files.add(f)
        files_accepted = len(seen_files)

    return _summarise(
        layout="B (orchestrator pool)",
        files_total=files_total,
        files_verified=files_verified,
        files_accepted=files_accepted,
        bytes_saved=bytes_saved,
        bytes_orig_sum=bytes_orig_sum,
        bytes_short_sum=bytes_short_sum,
        pairs=pairs,
        rejected=pairs_rejected,
        l2_groups=l2_groups,
        l2_applied=l2_applied,
        l2_g3_rejected=l2_g3_rejected,
        warning_cleanups=warning_cleanups,
        extra={
            "pairs_clean_jsonl": pairs_clean,
            "pairs_raw_jsonl": pairs_raw,
            "pairs_style_regressions_jsonl": pairs_style_reg,
            "files_done": files_done,
            "files_failed": files_failed,
        },
    )


def _summarise(*, layout, files_total, files_verified, files_accepted,
               bytes_saved, bytes_orig_sum, bytes_short_sum, pairs, rejected,
               l2_groups, l2_applied, l2_g3_rejected, warning_cleanups,
               extra=None):
    return {
        "layout": layout,
        "files_total": files_total,
        "files_verified": files_verified,
        "files_accepted": files_accepted,
        "accept_rate": (files_accepted / files_total) if files_total else 0.0,
        "verify_rate": (files_verified / files_total) if files_total else 0.0,
        "training_pairs": pairs,
        "rejected_pairs": rejected,
        "bytes_saved_sum": sum(bytes_saved),
        "bytes_saved_mean": (statistics.mean(bytes_saved) if bytes_saved else 0),
        "bytes_saved_median": (statistics.median(bytes_saved) if bytes_saved else 0),
        "bytes_saved_p90": _percentile(bytes_saved, 0.90),
        "bytes_saved_p99": _percentile(bytes_saved, 0.99),
        "bytes_saved_max": (max(bytes_saved) if bytes_saved else 0),
        "bytes_original_sum": bytes_orig_sum,
        "bytes_shortened_sum": bytes_short_sum,
        "byte_reduction_pct": (
            (bytes_orig_sum - bytes_short_sum) / bytes_orig_sum
            if bytes_orig_sum else 0.0
        ),
        "l2_groups": l2_groups,
        "l2_antiun_applied": l2_applied,
        "l2_g3_rejected": l2_g3_rejected,
        "g3_veto_rate": (l2_g3_rejected / l2_groups) if l2_groups else 0.0,
        "warning_cleanups": warning_cleanups,
        **(extra or {}),
    }


def _format_markdown(stats: dict) -> str:
    cols = [
        "Corpus", "Layout", "Files", "Verified",
        "Accepted (files)", "Train pairs", "Rejected",
        "Bytes saved (Σ)", "Median save (B)", "p90 (B)", "Max (B)",
    ]
    show_l2 = any(
        s.get("l2_groups", 0) or s.get("l2_antiun_applied", 0) or s.get("l2_g3_rejected", 0)
        for s in stats.values()
    )
    if show_l2:
        cols += ["L2 groups", "L2 applied", "G3 vetoes", "G3 veto %"]
    rows = []
    for name, s in stats.items():
        row = [
            f"`{name}`",
            s["layout"].split(" ")[0],
            f"{s['files_total']:,}",
            f"{s['files_verified']:,}",
            f"{s['files_accepted']:,} ({s['accept_rate']*100:.1f}%)",
            f"{s['training_pairs']:,}",
            f"{s['rejected_pairs']:,}",
            f"{s['bytes_saved_sum']:,}",
            f"{s['bytes_saved_median']:.0f}",
            f"{s['bytes_saved_p90']:.0f}",
            f"{s['bytes_saved_max']:,}",
        ]
        if show_l2:
            row += [
                f"{s['l2_groups']:,}",
                f"{s['l2_antiun_applied']:,}",
                f"{s['l2_g3_rejected']:,}",
                f"{s['g3_veto_rate']*100:.1f}%",
            ]
        rows.append(row)
    out = [
           "Generated from `corpus_stats_v2.json`. L2/G3 aggregate columns are omitted when all values are zero; sample-level G3 statistics are in `g3_sample.json`.",
           "",
           "| " + " | ".join(cols) + " |",
           "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layoutA", action="append", default=[],
                    help="name:dir for per-file _report.json directories")
    ap.add_argument("--layoutB", action="append", default=[],
                    help="name:dir for orchestrator-pool directories")
    ap.add_argument("--out", required=True)
    ap.add_argument("--markdown", required=True)
    args = ap.parse_args(argv)

    stats: dict = {}
    for spec in args.layoutA:
        name, _, d = spec.partition(":")
        p = Path(d)
        if not p.is_dir():
            print(f"warning: {d} is not a directory", file=sys.stderr)
            continue
        stats[name] = _scan_layout_a(p)
        s = stats[name]
        print(f"[A] {name}: files={s['files_total']:,} accepted={s['files_accepted']:,} "
              f"pairs={s['training_pairs']:,} bytes={s['bytes_saved_sum']:,}",
              file=sys.stderr)
    for spec in args.layoutB:
        name, _, d = spec.partition(":")
        p = Path(d)
        if not p.is_dir():
            print(f"warning: {d} is not a directory", file=sys.stderr)
            continue
        stats[name] = _scan_layout_b(p)
        s = stats[name]
        print(f"[B] {name}: files={s['files_total']:,} done={s.get('files_done',0):,} "
              f"pairs={s['training_pairs']:,} rejected={s['rejected_pairs']:,}",
              file=sys.stderr)

    Path(args.out).write_text(json.dumps(stats, indent=2) + "\n")
    Path(args.markdown).write_text(_format_markdown(stats))
    print(f"wrote {args.out} and {args.markdown}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
