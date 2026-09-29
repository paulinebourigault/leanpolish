#!/usr/bin/env python3
"""Download the Goedel-LM Lean-workbook proofs as Lean source files.

The script reads ``Goedel-LM/Lean-workbook-proofs`` from Hugging Face and writes
one standalone ``.lean`` file per proof. It can also summarize an existing local
download without contacting the dataset service.

Usage:
    python3 download_goedel.py
    python3 download_goedel.py --limit 100
    python3 download_goedel.py --output-dir my_goedel_proofs
    python3 download_goedel.py --stats-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional


LAKE_ROOT = Path(__file__).resolve().parent  # repository root
DEFAULT_OUTPUT_DIR = LAKE_ROOT / "goedel_workbook"
DATASET_NAME = "Goedel-LM/Lean-workbook-proofs"


def sanitize_filename(problem_id: str) -> str:
    """Convert problem_id to a safe filename."""
    # problem_id format: "lean_workbook_10009"
    # Keep it as-is, just ensure no path separators
    return re.sub(r'[^\w\-.]', '_', problem_id)


def preprocess_proof(full_proof: str) -> str:
    """Light cleanup of a proof before optimization.

    We do not modify `set_option maxHeartbeats 0` — LeanPolish has its
    own wall-clock timeouts (5s/tactic, 30s/goal, fold budget) that prevent
    hangs, and capping heartbeats could break proofs that legitimately need
    extended elaboration.
    """
    text = full_proof
    # Normalize line endings
    text = text.replace('\r\n', '\n')
    # Strip trailing whitespace per line
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    # Ensure trailing newline
    if not text.endswith('\n'):
        text += '\n'
    return text


def analyze_proof(text: str) -> dict:
    """Quick static analysis of a proof for statistics."""
    lines = text.split('\n')
    tactic_re = re.compile(
        r'\b(by$|:= by\b|simp|ring|omega|linarith|norm_num|decide|exact|rfl|'
        r'apply|intro|have |obtain|rw |calc|induction|cases|nlinarith|'
        r'field_simp|positivity|constructor|rcases|aesop)',
        re.MULTILINE
    )
    tactic_count = len(tactic_re.findall(text))

    # Count dead-looking <;> chains
    dead_chain_re = re.compile(r'<;>\s*(rfl|ring|simp|norm_num|linarith|nlinarith|decide)')
    dead_chains = len(dead_chain_re.findall(text))

    # Count verbose comment blocks (/- ... -/)
    comment_re = re.compile(r'/\-[\s\S]*?\-/', re.MULTILINE)
    comments = comment_re.findall(text)
    comment_bytes = sum(len(c) for c in comments)

    return {
        "lines": len(lines),
        "bytes": len(text.encode()),
        "tactic_count": tactic_count,
        "dead_chains": dead_chains,
        "comment_bytes": comment_bytes,
        "comment_pct": comment_bytes * 100 // max(len(text.encode()), 1),
    }


def download_and_write(
    output_dir: Path,
    limit: Optional[int] = None,
    skip_existing: bool = True,
) -> dict:
    """Download dataset and write proofs as .lean files.

    Returns statistics dict.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: 'datasets' library not installed.", file=sys.stderr)
        print("Install with: pip install datasets", file=sys.stderr)
        sys.exit(1)

    print(f"Downloading {DATASET_NAME} from HuggingFace...")
    t0 = time.monotonic()
    ds = load_dataset(DATASET_NAME, split="train")
    elapsed = time.monotonic() - t0
    total = len(ds)
    print(f"Downloaded {total} proofs in {elapsed:.1f}s")

    if limit:
        ds = ds.select(range(min(limit, total)))
        print(f"Using first {len(ds)} proofs (--limit {limit})")

    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "total": len(ds),
        "written": 0,
        "skipped_existing": 0,
        "skipped_no_proof": 0,
        "total_bytes": 0,
        "total_tactic_count": 0,
        "total_dead_chains": 0,
        "total_comment_bytes": 0,
    }

    print(f"Writing .lean files to {output_dir} ...")
    for i, entry in enumerate(ds):
        problem_id = entry["problem_id"]
        full_proof = entry["full_proof"]

        if not full_proof or not full_proof.strip():
            stats["skipped_no_proof"] += 1
            continue

        filename = sanitize_filename(problem_id) + ".lean"
        filepath = output_dir / filename

        if skip_existing and filepath.exists():
            stats["skipped_existing"] += 1
            continue

        # Preprocess
        processed = preprocess_proof(full_proof)

        # Analyze
        analysis = analyze_proof(processed)
        stats["total_bytes"] += analysis["bytes"]
        stats["total_tactic_count"] += analysis["tactic_count"]
        stats["total_dead_chains"] += analysis["dead_chains"]
        stats["total_comment_bytes"] += analysis["comment_bytes"]

        # Write
        filepath.write_text(processed, encoding='utf-8')
        stats["written"] += 1

        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(ds)} written...")

    # Write metadata
    meta = {
        "dataset": DATASET_NAME,
        "total_proofs": stats["total"],
        "files_written": stats["written"],
        "skipped_existing": stats["skipped_existing"],
        "avg_bytes": stats["total_bytes"] // max(stats["written"], 1),
        "avg_tactics": stats["total_tactic_count"] // max(stats["written"], 1),
        "total_dead_chains": stats["total_dead_chains"],
        "avg_comment_pct": stats["total_comment_bytes"] * 100
                          // max(stats["total_bytes"], 1),
    }
    meta_path = output_dir / "_download_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return stats


def print_stats(output_dir: Path):
    """Print statistics about existing download."""
    lean_files = sorted(output_dir.glob("*.lean"))
    if not lean_files:
        print(f"No .lean files found in {output_dir}")
        return

    total_bytes = 0
    total_lines = 0
    total_tactics = 0
    total_dead = 0
    total_comments = 0

    for f in lean_files:
        text = f.read_text(encoding='utf-8')
        analysis = analyze_proof(text)
        total_bytes += analysis["bytes"]
        total_lines += analysis["lines"]
        total_tactics += analysis["tactic_count"]
        total_dead += analysis["dead_chains"]
        total_comments += analysis["comment_bytes"]

    n = len(lean_files)
    print(f"\n{'='*50}")
    print(f"GOEDEL WORKBOOK DOWNLOAD STATS")
    print(f"{'='*50}")
    print(f"Files:             {n}")
    print(f"Total bytes:       {total_bytes:,} ({total_bytes/1024/1024:.1f} MB)")
    print(f"Avg bytes/file:    {total_bytes//n:,}")
    print(f"Total lines:       {total_lines:,}")
    print(f"Avg lines/file:    {total_lines//n}")
    print(f"Total tactics:     {total_tactics:,}")
    print(f"Avg tactics/file:  {total_tactics//n}")
    print(f"Dead <;> chains:   {total_dead:,}")
    print(f"Comment bytes:     {total_comments:,} ({total_comments*100//total_bytes}% of total)")
    print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(
        description="Download Goedel-workbook proofs as standalone Lean files"
    )
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for .lean files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="Download only first N proofs (for testing)",
    )
    parser.add_argument(
        "--stats-only", action="store_true",
        help="Show statistics for an existing download without downloading data",
    )
    parser.add_argument(
        "--no-skip", action="store_true",
        help="Overwrite existing files instead of skipping",
    )
    args = parser.parse_args()

    if args.stats_only:
        print_stats(args.output_dir)
        return

    stats = download_and_write(
        output_dir=args.output_dir,
        limit=args.limit,
        skip_existing=not args.no_skip,
    )

    print(f"\n{'='*50}")
    print(f"DOWNLOAD COMPLETE")
    print(f"{'='*50}")
    print(f"Written:           {stats['written']}")
    if stats['skipped_existing']:
        print(f"Skipped (exist):   {stats['skipped_existing']}")
    if stats['skipped_no_proof']:
        print(f"Skipped (empty):   {stats['skipped_no_proof']}")
    print(f"Total bytes:       {stats['total_bytes']:,}")
    print(f"Avg bytes/file:    {stats['total_bytes']//max(stats['written'],1):,}")
    print(f"Dead <;> chains:   {stats['total_dead_chains']:,}")
    print(f"Comment density:   {stats['total_comment_bytes']*100//max(stats['total_bytes'],1)}%")
    print(f"\nOutput:            {args.output_dir}")
    print(f"\nNext step:")
    print(f"  python3 run_goedel.py --limit 50 --workers 4   # test run")
    print(f"  python3 run_goedel.py --workers 16             # full run")


if __name__ == "__main__":
    main()
