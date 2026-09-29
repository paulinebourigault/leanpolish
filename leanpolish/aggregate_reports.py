#!/usr/bin/env python3
"""Aggregate per-file LeanPolish reports into corpus-level summaries.

The script scans a workspace for ``*_report.json`` files, checks whether the
corresponding ``*_shortened.lean`` file was emitted, and writes optional CSV and
JSON summaries. Reports without a shortened sibling are retained as unsuccessful
or unchanged runs rather than discarded.

Usage:
    python aggregate_reports.py [WORKSPACE_ROOT] [--csv OUT.csv] [--json OUT.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


# Top-level directories that contain optimization corpora. Anything else is
# bucketed as "other".
KNOWN_ROOTS = {
    "goedel_optimization",
    "goedel_workbook",
    "mathlib_optimization",
    "mathlib_optimization_skipped",
    "putnam_bench_proofs",
    "Putnam2025_AxiomProver",
}


def corpus_root(report_path: Path, workspace: Path) -> str:
    try:
        rel = report_path.relative_to(workspace)
    except ValueError:
        return "other"
    parts = rel.parts
    if parts and parts[0] in KNOWN_ROOTS:
        return parts[0]
    return "other"


def find_reports(workspace: Path, include_quarantine: bool = False,
                 include_skipped: bool = False) -> list[Path]:
    """Discover ``*_report.json`` files under ``workspace``.
    """
    skip_dirs = {".lake", ".git", ".venv", "__pycache__"}
    out: list[Path] = []
    for p in workspace.rglob("*_report.json"):
        parts = p.parts
        if any(part in skip_dirs for part in parts):
            continue
        if not include_quarantine and any(part.startswith("_quarantine") for part in parts):
            continue
        if not include_skipped and "mathlib_optimization_skipped" in parts:
            continue
        out.append(p)
    return out


def load_report(p: Path) -> dict[str, Any] | None:
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def safe_int(d: dict, k: str) -> int:
    v = d.get(k, 0)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def percent(num: int, den: int) -> float:
    return (100.0 * num / den) if den > 0 else 0.0


class Bucket:
    __slots__ = (
        "name",
        "total_reports", "with_shortened", "without_shortened",
        "improved",  # files where bytes_saved > 0
        "bytes_orig", "bytes_short", "bytes_saved",
        "tokens_orig", "tokens_short", "tokens_saved",
        "lines_orig", "lines_short", "lines_saved",
        "tactic_replacements", "dead_code_detected", "dead_code_removed",
        "bisect_dropped", "files_with_bisect_drops",
        "training_pairs",
        "per_file_byte_pct", "per_file_token_pct", "per_file_line_pct",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.total_reports = 0
        self.with_shortened = 0
        self.without_shortened = 0
        self.improved = 0
        self.bytes_orig = 0
        self.bytes_short = 0
        self.bytes_saved = 0
        self.tokens_orig = 0
        self.tokens_short = 0
        self.tokens_saved = 0
        self.lines_orig = 0
        self.lines_short = 0
        self.lines_saved = 0
        self.tactic_replacements = 0
        self.dead_code_detected = 0
        self.dead_code_removed = 0
        self.bisect_dropped = 0
        self.files_with_bisect_drops = 0
        self.training_pairs = 0
        self.per_file_byte_pct: list[float] = []
        self.per_file_token_pct: list[float] = []
        self.per_file_line_pct: list[float] = []

    def absorb(self, rpt: dict[str, Any], has_shortened: bool) -> None:
        self.total_reports += 1
        if has_shortened:
            self.with_shortened += 1
        else:
            self.without_shortened += 1

        bo = safe_int(rpt, "bytes_original")
        bs = safe_int(rpt, "bytes_shortened")
        bsav = safe_int(rpt, "bytes_saved")
        to = safe_int(rpt, "tokens_original")
        ts = safe_int(rpt, "tokens_shortened")
        tsav = safe_int(rpt, "tokens_saved")
        lo = safe_int(rpt, "lines_original")
        ls_ = safe_int(rpt, "lines_shortened")
        lsav = safe_int(rpt, "lines_saved")

        self.bytes_orig += bo
        self.bytes_short += bs
        self.bytes_saved += bsav
        self.tokens_orig += to
        self.tokens_short += ts
        self.tokens_saved += tsav
        self.lines_orig += lo
        self.lines_short += ls_
        self.lines_saved += lsav

        self.tactic_replacements += safe_int(rpt, "tactic_replacements")
        self.dead_code_detected += safe_int(rpt, "dead_code_detected")
        self.dead_code_removed += safe_int(rpt, "dead_code_removed")
        bd = safe_int(rpt, "bisect_dropped")
        self.bisect_dropped += bd
        if bd > 0:
            self.files_with_bisect_drops += 1
        tp = rpt.get("training_pairs")
        if isinstance(tp, list):
            self.training_pairs += len(tp)

        if bsav > 0:
            self.improved += 1
        if bo > 0:
            self.per_file_byte_pct.append(percent(bsav, bo))
        if to > 0:
            self.per_file_token_pct.append(percent(tsav, to))
        if lo > 0:
            self.per_file_line_pct.append(percent(lsav, lo))

    def summary(self) -> dict[str, Any]:
        def stats(xs: list[float]) -> dict[str, float]:
            if not xs:
                return {"mean": 0.0, "median": 0.0, "p90": 0.0, "max": 0.0}
            xs_sorted = sorted(xs)
            n = len(xs_sorted)
            p90_idx = max(0, min(n - 1, int(round(0.9 * (n - 1)))))
            return {
                "mean": statistics.fmean(xs_sorted),
                "median": statistics.median(xs_sorted),
                "p90": xs_sorted[p90_idx],
                "max": xs_sorted[-1],
            }

        return {
            "corpus": self.name,
            "files_total": self.total_reports,
            "files_with_shortened": self.with_shortened,
            "files_without_shortened": self.without_shortened,
            "files_improved_bytes": self.improved,
            "pct_files_improved": percent(self.improved, self.total_reports),
            "bytes_original_total": self.bytes_orig,
            "bytes_shortened_total": self.bytes_short,
            "bytes_saved_total": self.bytes_saved,
            "bytes_pct_saved": percent(self.bytes_saved, self.bytes_orig),
            "tokens_original_total": self.tokens_orig,
            "tokens_shortened_total": self.tokens_short,
            "tokens_saved_total": self.tokens_saved,
            "tokens_pct_saved": percent(self.tokens_saved, self.tokens_orig),
            "lines_original_total": self.lines_orig,
            "lines_shortened_total": self.lines_short,
            "lines_saved_total": self.lines_saved,
            "lines_pct_saved": percent(self.lines_saved, self.lines_orig),
            "tactic_replacements_total": self.tactic_replacements,
            "dead_code_detected_total": self.dead_code_detected,
            "dead_code_removed_total": self.dead_code_removed,
            "bisect_dropped_total": self.bisect_dropped,
            "files_with_bisect_drops": self.files_with_bisect_drops,
            "training_pairs_total": self.training_pairs,
            "per_file_byte_pct": stats(self.per_file_byte_pct),
            "per_file_token_pct": stats(self.per_file_token_pct),
            "per_file_line_pct": stats(self.per_file_line_pct),
        }


def fmt_int(n: int) -> str:
    return f"{n:>14,}"


def fmt_pct(p: float) -> str:
    return f"{p:6.2f}%"


def print_table(buckets: list[Bucket]) -> None:
    rows = [b.summary() for b in buckets]
    rows.sort(key=lambda r: (r["corpus"] != "TOTAL", r["corpus"]))

    print()
    print("=" * 110)
    print(" Headline numbers (soundness: every counted file has a fresh-verified _shortened.lean adjacent)")
    print("=" * 110)
    hdr = f"{'corpus':<32}{'files':>8}{'shrt':>7}{'imp':>7}{'%imp':>8}{'bytes_saved':>16}{'%B':>8}{'tokens_saved':>16}{'%T':>8}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['corpus']:<32}"
            f"{r['files_total']:>8,}"
            f"{r['files_with_shortened']:>7,}"
            f"{r['files_improved_bytes']:>7,}"
            f"{fmt_pct(r['pct_files_improved']):>8}"
            f"{r['bytes_saved_total']:>16,}"
            f"{fmt_pct(r['bytes_pct_saved']):>8}"
            f"{r['tokens_saved_total']:>16,}"
            f"{fmt_pct(r['tokens_pct_saved']):>8}"
        )
    print()

    print("=" * 110)
    print(" Per-file reduction distribution (computed only over files with a non-zero original size)")
    print("=" * 110)
    hdr2 = f"{'corpus':<32}{'mean%B':>9}{'med%B':>9}{'p90%B':>9}{'max%B':>9}{'mean%T':>9}{'med%T':>9}{'mean%L':>9}{'med%L':>9}"
    print(hdr2)
    print("-" * len(hdr2))
    for r in rows:
        b = r["per_file_byte_pct"]; t = r["per_file_token_pct"]; l = r["per_file_line_pct"]
        print(
            f"{r['corpus']:<32}"
            f"{b['mean']:>8.2f}%"
            f"{b['median']:>8.2f}%"
            f"{b['p90']:>8.2f}%"
            f"{b['max']:>8.2f}%"
            f"{t['mean']:>8.2f}%"
            f"{t['median']:>8.2f}%"
            f"{l['mean']:>8.2f}%"
            f"{l['median']:>8.2f}%"
        )
    print()

    print("=" * 110)
    print(" Operational counters (tactic replacements / dead code / bisect transparency / training pairs)")
    print("=" * 110)
    hdr3 = f"{'corpus':<32}{'replacements':>14}{'dead_det':>10}{'dead_rem':>10}{'bisect_drop':>13}{'files_w_drop':>14}{'train_pairs':>14}"
    print(hdr3)
    print("-" * len(hdr3))
    for r in rows:
        print(
            f"{r['corpus']:<32}"
            f"{r['tactic_replacements_total']:>14,}"
            f"{r['dead_code_detected_total']:>10,}"
            f"{r['dead_code_removed_total']:>10,}"
            f"{r['bisect_dropped_total']:>13,}"
            f"{r['files_with_bisect_drops']:>14,}"
            f"{r['training_pairs_total']:>14,}"
        )
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace", nargs="?", default=".",
                    help="Workspace root containing the corpora (default: cwd)")
    ap.add_argument("--csv", default=None, help="Write per-corpus summary CSV here")
    ap.add_argument("--json", default=None, help="Write full summary JSON here")
    ap.add_argument("--per-file-csv", default=None,
                    help="Optional: also dump a row per individual report")
    ap.add_argument("--require-shortened", action="store_true",
                    help="Skip reports that lack a sibling _shortened.lean")
    ap.add_argument("--include-quarantine", action="store_true",
                    help="Also include reports under any _quarantine* directory")
    ap.add_argument("--include-skipped", action="store_true",
                    help="Also include reports under mathlib_optimization_skipped/")
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    if not workspace.is_dir():
        print(f"ERROR: workspace not a directory: {workspace}", file=sys.stderr)
        return 2

    reports = find_reports(workspace,
                           include_quarantine=args.include_quarantine,
                           include_skipped=args.include_skipped)
    print(f"Scanning {workspace}", file=sys.stderr)
    print(f"Found {len(reports):,} *_report.json files", file=sys.stderr)

    buckets: dict[str, Bucket] = defaultdict(lambda: Bucket(""))
    total = Bucket("TOTAL")

    skipped_invalid = 0
    skipped_no_shortened = 0
    per_file_rows: list[dict[str, Any]] = []

    for rp in reports:
        rpt = load_report(rp)
        if rpt is None:
            skipped_invalid += 1
            continue
        # Find matching _shortened.lean: report path = <stem>_report.json,
        # source stem = <stem>; shortened = <stem>_shortened.lean.
        # Note: report's "stem" already ends in "_report" → strip suffix.
        rep_stem = rp.stem  # e.g. "Foo_report"
        if rep_stem.endswith("_report"):
            base_stem = rep_stem[: -len("_report")]
        else:
            base_stem = rep_stem
        shortened = rp.with_name(base_stem + "_shortened.lean")
        has_short = shortened.is_file()
        if args.require_shortened and not has_short:
            skipped_no_shortened += 1
            continue

        root = corpus_root(rp, workspace)
        if not buckets[root].name:
            buckets[root].name = root
        buckets[root].absorb(rpt, has_short)
        total.absorb(rpt, has_short)

        if args.per_file_csv:
            per_file_rows.append({
                "corpus": root,
                "report": str(rp.relative_to(workspace)),
                "has_shortened": has_short,
                "bytes_original": safe_int(rpt, "bytes_original"),
                "bytes_shortened": safe_int(rpt, "bytes_shortened"),
                "bytes_saved": safe_int(rpt, "bytes_saved"),
                "tokens_original": safe_int(rpt, "tokens_original"),
                "tokens_shortened": safe_int(rpt, "tokens_shortened"),
                "tokens_saved": safe_int(rpt, "tokens_saved"),
                "lines_original": safe_int(rpt, "lines_original"),
                "lines_shortened": safe_int(rpt, "lines_shortened"),
                "lines_saved": safe_int(rpt, "lines_saved"),
                "tactic_replacements": safe_int(rpt, "tactic_replacements"),
                "dead_code_detected": safe_int(rpt, "dead_code_detected"),
                "dead_code_removed": safe_int(rpt, "dead_code_removed"),
                "bisect_dropped": safe_int(rpt, "bisect_dropped"),
            })

    if skipped_invalid:
        print(f"WARN: {skipped_invalid} reports were not valid JSON (skipped)", file=sys.stderr)
    if skipped_no_shortened:
        print(f"INFO: {skipped_no_shortened} reports had no sibling _shortened.lean (skipped, --require-shortened)", file=sys.stderr)

    print_table(list(buckets.values()) + [total])

    summary = {
        "workspace": str(workspace),
        "total_reports_scanned": len(reports),
        "skipped_invalid_json": skipped_invalid,
        "skipped_no_shortened": skipped_no_shortened,
        "per_corpus": [b.summary() for b in buckets.values()],
        "total": total.summary(),
    }

    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))
        print(f"Wrote JSON summary -> {args.json}", file=sys.stderr)

    if args.csv:
        rows = [b.summary() for b in list(buckets.values()) + [total]]
        # Flatten nested per_file_*_pct dicts for CSV.
        fieldnames: list[str] = []
        flat_rows: list[dict[str, Any]] = []
        for r in rows:
            flat: dict[str, Any] = {}
            for k, v in r.items():
                if isinstance(v, dict):
                    for kk, vv in v.items():
                        flat[f"{k}__{kk}"] = vv
                else:
                    flat[k] = v
            for k in flat:
                if k not in fieldnames:
                    fieldnames.append(k)
            flat_rows.append(flat)
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in flat_rows:
                w.writerow(r)
        print(f"Wrote per-corpus CSV -> {args.csv}", file=sys.stderr)

    if args.per_file_csv:
        if per_file_rows:
            fns = list(per_file_rows[0].keys())
            with open(args.per_file_csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fns)
                w.writeheader()
                for r in per_file_rows:
                    w.writerow(r)
            print(f"Wrote per-file CSV -> {args.per_file_csv} ({len(per_file_rows)} rows)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
