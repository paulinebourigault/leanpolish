#!/usr/bin/env python3
"""Run LeanPolish on selected Mathlib files.

The runner copies Mathlib sources into a working directory, selects files by
subdirectory, explicit path, or limit, then processes them with LeanPolish.
Existing reports are reused unless ``--force-copy`` is set.

Usage:
    lake build LeanPolish
    python3 run_mathlib.py --dry-run
    python3 run_mathlib.py --workers 16 --threads 4 --chunk-size 1 --timeout 600
    python3 run_mathlib.py --collect-only
    python3 run_mathlib.py --subdir Algebra --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Import shared infrastructure from leanpolish.py in same directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from leanpolish import (
    OptimizationResult,
    _find_lake_root,
    parse_optimizer_output,
    split_multi_file_output,
    _print_batch_summary,
)

# ===================================
# Constants
# ===================================

LAKE_ROOT = Path(__file__).resolve().parent  # repository root
MATHLIB_SRC = LAKE_ROOT / ".lake" / "packages" / "mathlib" / "Mathlib"
MATHLIB_WORK_DIR = LAKE_ROOT / "mathlib_optimization"

# Files to skip (infrastructure, not proofs)
SKIP_PATTERNS = {
    "Init.lean",
    "Tactic.lean",
    "Lean.lean",
}

# Subdirectories that are mostly tactic infrastructure, not proofs
SKIP_DIRS = {
    "Tactic",   # tactic definitions, not proofs to optimize
    "Lean",     # lean extensions
    "Init",     # initialization
    "Control",  # monad infrastructure
    "Testing",  # test infrastructure
}


def discover_mathlib_files(
    subdir: Optional[str] = None,
    limit: Optional[int] = None,
    min_tactic_lines: int = 3,
) -> List[Path]:
    """Find Mathlib .lean files worth optimizing.

    Filters for files that contain tactic proofs (at least
    `min_tactic_lines` lines with tactic keywords).
    """
    search_root = MATHLIB_SRC
    if subdir:
        search_root = MATHLIB_SRC / subdir
        if not search_root.exists():
            print(f"Error: {search_root} does not exist", file=sys.stderr)
            print(f"Available subdirs: {sorted(d.name for d in MATHLIB_SRC.iterdir() if d.is_dir())}")
            sys.exit(1)

    tactic_re = re.compile(
        r'\b(by$|:= by\b|simp|ring|omega|linarith|norm_num|decide|exact|rfl|'
        r'apply|intro|have |obtain|rw |calc|induction|cases)',
        re.MULTILINE
    )

    candidates = []
    for f in sorted(search_root.rglob("*.lean")):
        # Skip non-proof files
        if f.name in SKIP_PATTERNS:
            continue
        rel = f.relative_to(MATHLIB_SRC)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue

        # Quick check: does this file have enough tactic content?
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        tactic_count = len(tactic_re.findall(text))
        if tactic_count >= min_tactic_lines:
            candidates.append(f)

    if limit:
        candidates = candidates[:limit]

    return candidates


def prepare_working_directory(
    mathlib_files: List[Path],
    work_dir: Path,
    force: bool = False,
) -> List[Path]:
    """Copy Mathlib files to a working directory, preserving directory structure.

    Returns list of copied file paths in the working directory.
    We copy (not symlink) so that:
    - _shortened.lean and _report.json outputs go to work_dir, not Mathlib source
    - We can modify files without touching the Mathlib package
    - The relative path from lake root is preserved for import resolution
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = 0
    for src_file in mathlib_files:
        # Preserve path relative to Mathlib root
        # e.g., Mathlib/Algebra/Order/Ring/Abs.lean
        rel = src_file.relative_to(MATHLIB_SRC)
        # Final path: mathlib_optimization/Mathlib/Algebra/Order/Ring/Abs.lean
        dst = work_dir / "Mathlib" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Skip if already copied and not forcing
        if dst.exists() and not force:
            # Check if already processed
            report = dst.with_name(dst.stem + "_report.json")
            if report.exists():
                skipped += 1
                continue

        shutil.copy2(src_file, dst)
        copied.append(dst)

    if skipped:
        print(f"Skipping {skipped} already-processed files.")

    return copied


def _build_result_from_section_mathlib(
    lean_file: Path, section_output: str, lake_root: Path
) -> OptimizationResult:
    """Build an OptimizationResult from optimizer output for a Mathlib file."""
    lean_file = lean_file.resolve()
    if not lean_file.exists():
        return OptimizationResult(source_file=str(lean_file), error="File not found")

    original_text = lean_file.read_text()
    original_lines = len(original_text.splitlines())
    result = OptimizationResult(source_file=str(lean_file), original_lines=original_lines)

    if not section_output or ("[DONE]" not in section_output and "[JSON]" not in section_output):
        if section_output:
            result.error = f"No completion marker: {section_output[:300]}"
        else:
            result.error = "No output from optimizer"
        return result

    info = parse_optimizer_output(section_output)
    result.replacements_applied = info.get("applied", 0)
    result.dead_code_blocks = info.get("dead_code_removed", 0)
    result.verified = info.get("verified", False) or info.get("output") is not None

    opt_file = lean_file.with_name(lean_file.stem + "_shortened.lean")
    if opt_file.exists():
        result.optimized_lines = len(opt_file.read_text().splitlines())
        result.output_file = str(opt_file)
    else:
        result.optimized_lines = original_lines

    result.bytes_original = info.get("bytes_original", len(original_text.encode()))
    result.bytes_shortened = (
        len(opt_file.read_text().encode()) if opt_file.exists()
        else info.get("bytes_shortened", result.bytes_original)
    )
    result.tokens_original = info.get("tokens_original", 0)
    result.tokens_shortened = info.get("tokens_shortened", result.tokens_original)
    result.lines_original = info.get("lines_original", 0)
    result.lines_shortened = info.get("lines_shortened", result.lines_original)

    training_pairs = info.get("training_pairs", [])
    result.training_pairs = training_pairs

    # Write per-file report
    report = {
        "file": str(lean_file),
        "bytes_original": result.bytes_original,
        "bytes_shortened": result.bytes_shortened,
        "bytes_saved": result.bytes_saved,
        "tokens_original": result.tokens_original,
        "tokens_shortened": result.tokens_shortened,
        "tokens_saved": result.tokens_saved,
        "lines_original": result.lines_original,
        "lines_shortened": result.lines_shortened,
        "lines_saved": result.lines_saved,
        "tactic_replacements": info.get("tactic_replacements", result.replacements_applied),
        "dead_code_detected": info.get("dead_code_detected", 0),
        "dead_code_removed": result.dead_code_blocks,
        "verified": result.verified,
        "rounds": info.get("rounds", "?"),
        "training_pairs": training_pairs,
    }
    report_file = lean_file.with_name(lean_file.stem + "_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    return result


def _run_mathlib_chunk(
    lake_root: Path,
    chunk_files: List[Path],
    threads: int = 4,
    timeout_per_file: int = 300,
    worker_id: int = 0,
) -> List[OptimizationResult]:
    """Run optimizer on a chunk of Mathlib files (one Lean process, shared imports)."""
    # Paths must be relative to lake root
    rel_paths = []
    for f in chunk_files:
        try:
            rel = str(f.resolve().relative_to(lake_root.resolve()))
        except ValueError:
            # File not under lake root
            print(f"  [W{worker_id}] SKIP {f} (not under lake root)", flush=True)
            continue
        rel_paths.append(rel)

    if not rel_paths:
        return []

    binary = lake_root / ".lake" / "build" / "bin" / "LeanPolish"
    if binary.exists():
        cmd = ["stdbuf", "-oL", "lake", "env", str(binary)] + rel_paths
    else:
        cmd = ["stdbuf", "-oL", "lake", "env", "lean",
               f"--threads={threads}", "--run", "LeanPolish.lean"] + rel_paths

    timeout_total = timeout_per_file * len(chunk_files) + 180  # +180s for Mathlib load

    output_lines: List[str] = []
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(lake_root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            start_new_session=True,
        )
        assert proc.stdout is not None

        def _kill_group():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

        timer = threading.Timer(timeout_total, _kill_group)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)
                if line.startswith("[FILE] ") or line.startswith("[IMPORTS LOADED]") or \
                   line.startswith("[DONE]") or line.startswith("[FILE_ERROR]") or \
                   line.startswith("[TIMEOUT]"):
                    print(f"  [W{worker_id}] {line}", flush=True)
        finally:
            timer.cancel()

        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            print(f"  [W{worker_id}] Process hung on shutdown, killing", flush=True)
            _kill_group()
            proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        return [OptimizationResult(source_file=str(f), error="Group timeout")
                for f in chunk_files]
    except Exception as e:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return [OptimizationResult(source_file=str(f), error=str(e))
                for f in chunk_files]

    output = "\n".join(output_lines)
    sections = split_multi_file_output(output)

    results = []
    for f in chunk_files:
        rel = str(f.resolve().relative_to(lake_root.resolve()))
        section = sections.get(rel, "")
        r = _build_result_from_section_mathlib(f, section, lake_root)
        results.append(r)
    return results


def _worker_fn(args_tuple):
    """Top-level picklable worker function for ProcessPoolExecutor."""
    lake_root, chunk_files, threads, timeout_per_file, worker_id = args_tuple
    lake_root = Path(lake_root)
    chunk_files = [Path(f) for f in chunk_files]
    results = _run_mathlib_chunk(lake_root, chunk_files, threads, timeout_per_file, worker_id)
    # Serialize for cross-process transfer
    return [{
        "source_file": r.source_file,
        "output_file": r.output_file,
        "original_lines": r.original_lines,
        "optimized_lines": r.optimized_lines,
        "replacements_applied": r.replacements_applied,
        "dead_code_blocks": r.dead_code_blocks,
        "verified": r.verified,
        "error": r.error,
        "bytes_original": r.bytes_original,
        "bytes_shortened": r.bytes_shortened,
        "tokens_original": r.tokens_original,
        "tokens_shortened": r.tokens_shortened,
        "lines_original": r.lines_original,
        "lines_shortened": r.lines_shortened,
        "training_pairs": r.training_pairs,
    } for r in results]


def run_mathlib_batch(
    work_files: List[Path],
    workers: int = 8,
    threads: int = 4,
    chunk_size: int = 5,
    timeout_per_file: int = 300,
) -> List[OptimizationResult]:
    """Run optimizer on Mathlib files with parallel workers."""
    lake_root = LAKE_ROOT

    # Filter out already-processed files
    remaining = []
    skipped = 0
    for f in work_files:
        report = f.with_name(f.stem + "_report.json")
        if report.exists():
            skipped += 1
        else:
            remaining.append(f)

    if skipped:
        print(f"Skipping {skipped} already-processed files.")
    work_files = remaining

    if not work_files:
        print("All files already processed.")
        return []

    # Split into chunks
    chunks = [work_files[i:i + chunk_size] for i in range(0, len(work_files), chunk_size)]
    n_chunks = len(chunks)
    effective_workers = min(workers, n_chunks)

    est_time = (len(work_files) * 60) / effective_workers / 60  # ~60s/file estimate for Mathlib

    # Individual Mathlib files have selective imports (unlike corpora that all
    # `import Mathlib`). With chunk_size=1, each Lean process loads only the
    # imports needed for its single file, avoiding import mismatches.
    print(f"\n{'='*60}")
    print(f"MATHLIB OPTIMIZATION RUN")
    print(f"{'='*60}")
    print(f"Files to process:  {len(work_files)}")
    print(f"Chunks:            {n_chunks} (size {chunk_size})")
    print(f"Workers:           {effective_workers} parallel Lean processes")
    print(f"Threads per proc:  {threads}")
    print(f"Timeout per file:  {timeout_per_file}s")
    print(f"Estimated time:    ~{est_time:.0f} min")
    print(f"Output dir:        {MATHLIB_WORK_DIR}")
    print(f"{'='*60}\n", flush=True)

    # Build worker arguments
    worker_args = [
        (str(lake_root), [str(f) for f in chunk], threads, timeout_per_file,
         i % effective_workers)
        for i, chunk in enumerate(chunks)
    ]

    results: List[OptimizationResult] = []
    start_time = time.monotonic()

    with ProcessPoolExecutor(max_workers=effective_workers) as executor:
        futures = {executor.submit(_worker_fn, args): args for args in worker_args}
        done_count = 0
        for future in as_completed(futures):
            try:
                chunk_results = future.result()
            except Exception as e:
                args = futures[future]
                chunk_results = [{"source_file": f, "error": str(e)} for f in args[1]]

            for rd in chunk_results:
                done_count += 1
                r = OptimizationResult(
                    source_file=rd["source_file"],
                    output_file=rd.get("output_file"),
                    original_lines=int(rd.get("original_lines", 0)),
                    optimized_lines=int(rd.get("optimized_lines", 0)),
                    replacements_applied=int(rd.get("replacements_applied", 0)),
                    dead_code_blocks=int(rd.get("dead_code_blocks", 0)),
                    verified=bool(rd.get("verified", False)),
                    error=rd.get("error"),
                    bytes_original=int(rd.get("bytes_original", 0)),
                    bytes_shortened=int(rd.get("bytes_shortened", 0)),
                    tokens_original=int(rd.get("tokens_original", 0)),
                    tokens_shortened=int(rd.get("tokens_shortened", 0)),
                    lines_original=int(rd.get("lines_original", 0)),
                    lines_shortened=int(rd.get("lines_shortened", 0)),
                    training_pairs=rd.get("training_pairs") or [],  # type: ignore[arg-type]
                )
                results.append(r)
                # Compact progress: only show shortened or error
                if r.error:
                    print(f"[{done_count}/{len(work_files)}] ERR  {Path(r.source_file).name}: {r.error[:80]}", flush=True)
                elif r.bytes_saved > 0:
                    pct = r.bytes_saved * 100 // max(r.bytes_original, 1)
                    print(f"[{done_count}/{len(work_files)}] {pct:3d}% {Path(r.source_file).name} "
                          f"({r.bytes_saved}B, {r.replacements_applied}r, {r.dead_code_blocks}d)", flush=True)
                else:
                    print(f"[{done_count}/{len(work_files)}] ---  {Path(r.source_file).name}", flush=True)

    elapsed = time.monotonic() - start_time
    _print_batch_summary(results, MATHLIB_WORK_DIR, elapsed)
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run LeanPolish on selected Mathlib files"
    )
    parser.add_argument(
        "--subdir",
        help="Only process a specific Mathlib subdirectory (e.g., Algebra, Analysis, Topology)",
    )
    parser.add_argument(
        "--files", nargs="+", metavar="PATH",
        help="Process specific files by relative path from Mathlib root "
             "(e.g. Data/Ordmap/Ordnode.lean). Overrides --subdir and --limit.",
    )
    parser.add_argument(
        "--limit", type=int,
        help="Process at most N files.",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=16,
        help="Number of parallel Lean processes (default 16). Each loads imports "
             "independently. With chunk_size=1, this is the degree of parallelism.",
    )
    parser.add_argument(
        "--threads", "-t", type=int, default=4,
        help="Lean threads per process (default 4). Total CPU = workers × threads.",
    )
    parser.add_argument(
        "--chunk-size", "-c", type=int, default=1,
        help="Files per Lean process (default 1). Unlike Putnam files that all "
             "'import Mathlib', individual Mathlib files have different imports, "
             "so chunk_size=1 is the safe default. Use >1 only if you know all "
             "files in each chunk share a common import superset.",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Timeout per file in seconds (default 600). Mathlib files are more "
             "complex than Putnam proofs; 600s avoids premature timeouts.",
    )
    parser.add_argument(
        "--min-tactics", type=int, default=3,
        help="Minimum tactic lines to consider a file worth optimizing (default 3).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show the planned work without running LeanPolish.",
    )
    parser.add_argument(
        "--collect-only", action="store_true",
        help="Collect existing reports without running LeanPolish.",
    )
    parser.add_argument(
        "--force-copy", action="store_true",
        help="Re-copy source files even if they already exist in the working directory.",
    )
    args = parser.parse_args()

    # Verify Mathlib exists
    if not MATHLIB_SRC.exists():
        print(f"Error: Mathlib not found at {MATHLIB_SRC}", file=sys.stderr)
        print("Run 'lake build' first to download Mathlib.", file=sys.stderr)
        sys.exit(1)

    # Collect-only mode
    if args.collect_only:
        if not MATHLIB_WORK_DIR.exists():
            print(f"Error: working directory {MATHLIB_WORK_DIR} does not exist", file=sys.stderr)
            sys.exit(1)
        dummy_results: List[OptimizationResult] = []
        for rf in sorted(MATHLIB_WORK_DIR.rglob("*_report.json")):
            try:
                rpt = json.loads(rf.read_text())
                dummy_results.append(OptimizationResult(
                    source_file=rpt.get("file", str(rf)),
                    bytes_original=rpt.get("bytes_original", 0),
                    bytes_shortened=rpt.get("bytes_shortened", 0),
                    tokens_original=rpt.get("tokens_original", 0),
                    tokens_shortened=rpt.get("tokens_shortened", 0),
                    lines_original=rpt.get("lines_original", 0),
                    lines_shortened=rpt.get("lines_shortened", 0),
                    replacements_applied=rpt.get("tactic_replacements", 0),
                    dead_code_blocks=rpt.get("dead_code_removed", 0),
                    verified=rpt.get("verified", False),
                    training_pairs=rpt.get("training_pairs", []),
                ))
            except (json.JSONDecodeError, OSError):
                pass
        _print_batch_summary(dummy_results, MATHLIB_WORK_DIR)
        sys.exit(0)

    # Discover files
    if args.files:
        # Explicit file list — bypass discovery
        mathlib_files = []
        for rel_path in args.files:
            p = MATHLIB_SRC / rel_path
            if not p.exists():
                print(f"Warning: {p} not found, skipping", file=sys.stderr)
            else:
                mathlib_files.append(p)
        print(f"Processing {len(mathlib_files)} explicitly specified file(s).")
    else:
        print(f"Scanning Mathlib at {MATHLIB_SRC} ...")
        mathlib_files = discover_mathlib_files(
            subdir=args.subdir,
            limit=args.limit,
            min_tactic_lines=args.min_tactics,
        )
        print(f"Found {len(mathlib_files)} files with ≥{args.min_tactics} tactic lines.")

    if not mathlib_files:
        print("No files to process.")
        sys.exit(0)

    # Show distribution by subdirectory
    subdir_counts: dict[str, int] = {}
    for f in mathlib_files:
        rel = f.relative_to(MATHLIB_SRC)
        top = rel.parts[0] if len(rel.parts) > 1 else "root"
        subdir_counts[top] = subdir_counts.get(top, 0) + 1
    print("\nFiles by subdirectory:")
    for sd, cnt in sorted(subdir_counts.items(), key=lambda x: -x[1])[:20]:
        print(f"  {sd:30s} {cnt:5d}")
    if len(subdir_counts) > 20:
        print(f"  ... and {len(subdir_counts) - 20} more")

    if args.dry_run:
        print(f"\nDry run complete. Would process {len(mathlib_files)} files.")
        print(f"Working directory: {MATHLIB_WORK_DIR}")
        sys.exit(0)

    # Verify binary exists
    binary = LAKE_ROOT / ".lake" / "build" / "bin" / "LeanPolish"
    if not binary.exists():
        print(f"\nWarning: Compiled binary not found at {binary}")
        print("Running in interpreter mode (slower). Build with: lake build LeanPolish")
        resp = input("Continue anyway? [y/N] ").strip().lower()
        if resp != 'y':
            sys.exit(0)

    # Prepare working directory
    print(f"\nPreparing working directory at {MATHLIB_WORK_DIR} ...")
    work_files = prepare_working_directory(
        mathlib_files, MATHLIB_WORK_DIR, force=args.force_copy,
    )
    print(f"Copied {len(work_files)} files to working directory.")

    if not work_files:
        print("No new files to process (all have reports).")
        # Still run collect to aggregate
        print("Run with --collect-only to aggregate existing reports.")
        sys.exit(0)

    # Run optimization
    run_mathlib_batch(
        work_files,
        workers=args.workers,
        threads=args.threads,
        chunk_size=args.chunk_size,
        timeout_per_file=args.timeout,
    )


if __name__ == "__main__":
    main()
