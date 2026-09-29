#!/usr/bin/env python3
"""Run LeanPolish on the Goedel-Workbook source corpus.

The runner copies downloaded Goedel-Workbook proofs into a working tree,
processes them in parallel, and aggregates per-file reports. Existing reports
are reused by default, so interrupted runs can be resumed.

Usage:
    python3 download_goedel.py
    python3 run_goedel.py --limit 50 --workers 4
    python3 run_goedel.py --workers 16 --threads 4 --chunk-size 5 --timeout 600
    python3 run_goedel.py --collect-only
    python3 run_goedel.py --elab-stats
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    parse_optimizer_output,
    split_multi_file_output,
    _print_batch_summary,
)

# ===================================
# Constants
# ===================================

LAKE_ROOT = Path(__file__).resolve().parent  # repository root
DEFAULT_GOEDEL_DIR = LAKE_ROOT / "goedel_workbook"
GOEDEL_OUTPUT_DIR = LAKE_ROOT / "goedel_optimization"


def discover_goedel_files(
    source_dir: Path,
    limit: Optional[int] = None,
    min_tactic_lines: int = 1,
) -> List[Path]:
    """Find Goedel .lean files to optimize.

    Unlike Mathlib, we keep a low tactic threshold — even proofs with
    a single `nlinarith` hint list are worth optimizing (the comments and
    dead <;> chains often dwarf the tactic).
    """
    tactic_re = re.compile(
        r'\b(by$|:= by\b|simp|ring|omega|linarith|norm_num|decide|exact|rfl|'
        r'apply|intro|have |obtain|rw |calc|induction|cases|nlinarith|'
        r'field_simp|positivity|constructor)',
        re.MULTILINE
    )

    candidates = []
    for f in sorted(source_dir.glob("*.lean")):
        if f.name.startswith('_'):
            continue
        try:
            text = f.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        tactic_count = len(tactic_re.findall(text))
        if tactic_count >= min_tactic_lines:
            candidates.append(f)

    if limit:
        candidates = candidates[:limit]

    return candidates


def prepare_working_directory(
    source_files: List[Path],
    source_dir: Path,
    work_dir: Path,
    force: bool = False,
) -> List[Path]:
    """Copy Goedel files to a working directory (flat structure).

    Copies into goedel_optimization/ so that _shortened.lean and
    _report.json outputs go there, not in the source download dir.
    """
    work_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    skipped = 0
    for src_file in source_files:
        dst = work_dir / src_file.name
        report = dst.with_name(dst.stem + "_report.json")

        if not force and report.exists():
            skipped += 1
            continue

        if not dst.exists() or force:
            import shutil
            shutil.copy2(src_file, dst)
        copied.append(dst)

    if skipped:
        print(f"Skipping {skipped} already-processed files.")

    return copied


def _build_result_from_section(
    lean_file: Path, section_output: str, lake_root: Path
) -> OptimizationResult:
    """Build an OptimizationResult from optimizer output."""
    lean_file = lean_file.resolve()
    if not lean_file.exists():
        return OptimizationResult(source_file=str(lean_file), error="File not found")

    original_text = lean_file.read_text(encoding='utf-8')
    original_lines = len(original_text.splitlines())
    result = OptimizationResult(source_file=str(lean_file), original_lines=original_lines)

    if not section_output or ("[DONE]" not in section_output and "[JSON]" not in section_output):
        if section_output:
            # Check if it's an elaboration failure (Phase 0 filter)
            if any(marker in section_output for marker in
                   ["[FILE_ERROR]", "elaboration failed", "unknown identifier",
                    "typeclass instance", "application type mismatch"]):
                result.error = f"Elaboration failed (incompatible with v4.21)"
            else:
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
        result.optimized_lines = len(opt_file.read_text(encoding='utf-8').splitlines())
        result.output_file = str(opt_file)
    else:
        result.optimized_lines = original_lines

    result.bytes_original = info.get("bytes_original", len(original_text.encode()))
    result.bytes_shortened = (
        len(opt_file.read_text(encoding='utf-8').encode()) if opt_file.exists()
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
        "problem_id": lean_file.stem,
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


def _run_goedel_chunk(
    lake_root: Path,
    chunk_files: List[Path],
    threads: int = 4,
    timeout_per_file: int = 600,
    worker_id: int = 0,
) -> List[OptimizationResult]:
    """Run optimizer on a chunk of Goedel files."""
    rel_paths = []
    for f in chunk_files:
        try:
            rel = str(f.resolve().relative_to(lake_root.resolve()))
        except ValueError:
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

    # Generous timeout: import loading (180s) + per-file budget
    timeout_total = timeout_per_file * len(chunk_files) + 180

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
        r = _build_result_from_section(f, section, lake_root)
        results.append(r)
    return results


def _worker_fn(args_tuple):
    """Top-level picklable worker function for ProcessPoolExecutor."""
    lake_root, chunk_files, threads, timeout_per_file, worker_id = args_tuple
    lake_root = Path(lake_root)
    chunk_files = [Path(f) for f in chunk_files]
    results = _run_goedel_chunk(lake_root, chunk_files, threads, timeout_per_file, worker_id)
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


def run_goedel_batch(
    work_files: List[Path],
    workers: int = 8,
    threads: int = 4,
    chunk_size: int = 5,
    timeout_per_file: int = 600,
) -> List[OptimizationResult]:
    """Run optimizer on Goedel files with parallel workers."""
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
    # All Goedel files share `import Mathlib` → chunking is safe and efficient.
    # The first file in each chunk pays the import cost; subsequent files reuse
    # the loaded environment. chunk_size=5 is a good balance.
    chunks = [work_files[i:i + chunk_size] for i in range(0, len(work_files), chunk_size)]
    n_chunks = len(chunks)
    effective_workers = min(workers, n_chunks)

    # Goedel proofs are typically simpler than Mathlib (single theorems),
    # so processing is faster — ~30-60s per file including verification
    est_time = (len(work_files) * 45) / effective_workers / 60

    print(f"\n{'='*60}")
    print(f"GOEDEL WORKBOOK OPTIMIZATION RUN")
    print(f"{'='*60}")
    print(f"Files to process:  {len(work_files)}")
    print(f"Chunks:            {n_chunks} (size {chunk_size})")
    print(f"Workers:           {effective_workers} parallel Lean processes")
    print(f"Threads per proc:  {threads}")
    print(f"Timeout per file:  {timeout_per_file}s")
    print(f"Estimated time:    ~{est_time:.0f} min")
    print(f"Output dir:        {GOEDEL_OUTPUT_DIR}")
    print(f"{'='*60}\n", flush=True)

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
        elab_fail = 0
        improved = 0
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

                # Progress display
                if r.error:
                    if "Elaboration failed" in (r.error or ""):
                        elab_fail += 1
                        if elab_fail <= 10 or elab_fail % 100 == 0:
                            print(f"[{done_count}/{len(work_files)}] ELAB  {Path(r.source_file).stem}", flush=True)
                    else:
                        print(f"[{done_count}/{len(work_files)}] ERR   {Path(r.source_file).stem}: {r.error[:80]}", flush=True)
                elif r.bytes_saved > 0:
                    improved += 1
                    pct = r.bytes_saved * 100 // max(r.bytes_original, 1)
                    print(f"[{done_count}/{len(work_files)}] {pct:3d}%  {Path(r.source_file).stem} "
                          f"({r.bytes_saved}B, {r.replacements_applied}r, {r.dead_code_blocks}d)", flush=True)
                else:
                    print(f"[{done_count}/{len(work_files)}] ---   {Path(r.source_file).stem}", flush=True)

    elapsed = time.monotonic() - start_time

    # Print extra Goedel-specific stats
    compiled = sum(1 for r in results if not r.error)
    improved_files = sum(1 for r in results if r.bytes_saved > 0)
    elab_failures = sum(1 for r in results if r.error and "Elaboration failed" in r.error)
    other_errors = sum(1 for r in results if r.error and "Elaboration failed" not in r.error)

    print(f"\n{'='*60}")
    print(f"GOEDEL-SPECIFIC STATS")
    print(f"{'='*60}")
    print(f"Total files:       {len(results)}")
    print(f"Compiled (v4.21):  {compiled} ({compiled*100//max(len(results),1)}%)")
    print(f"Elab failures:     {elab_failures} (incompatible with our Lean/Mathlib version)")
    if other_errors:
        print(f"Other errors:      {other_errors}")
    print(f"Improved:          {improved_files} ({improved_files*100//max(compiled,1)}% of compiled)")

    _print_batch_summary(results, GOEDEL_OUTPUT_DIR, elapsed)
    return results


def print_elab_stats(work_dir: Path):
    """Show elaboration success/failure breakdown from existing reports."""
    reports = sorted(work_dir.glob("*_report.json"))
    if not reports:
        print(f"No reports found in {work_dir}")
        return

    compiled = 0
    elab_fail = 0
    other_fail = 0
    improved = 0
    total_saved = 0

    for rf in reports:
        try:
            rpt = json.loads(rf.read_text())
            err = rpt.get("error") or ""
            if "Elaboration failed" in err:
                elab_fail += 1
            elif err:
                other_fail += 1
            else:
                compiled += 1
                saved = rpt.get("bytes_saved", 0)
                if saved > 0:
                    improved += 1
                total_saved += saved
        except (json.JSONDecodeError, OSError):
            pass

    total = compiled + elab_fail + other_fail
    print(f"\n{'='*50}")
    print(f"ELABORATION STATS ({total} reports)")
    print(f"{'='*50}")
    print(f"Compiled:      {compiled:5d} ({compiled*100//max(total,1)}%)")
    print(f"Elab failed:   {elab_fail:5d} ({elab_fail*100//max(total,1)}%)")
    print(f"Other errors:  {other_fail:5d}")
    print(f"Improved:      {improved:5d} ({improved*100//max(compiled,1)}% of compiled)")
    print(f"Total saved:   {total_saved:,} bytes")


def main():
    parser = argparse.ArgumentParser(
        description="Run LeanPolish on the Goedel-Workbook corpus"
    )
    parser.add_argument(
        "--source-dir", type=Path, default=DEFAULT_GOEDEL_DIR,
        help=f"Directory containing downloaded .lean files (default: {DEFAULT_GOEDEL_DIR})",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="Process at most N files.",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=16,
        help="Number of parallel Lean processes (default 16).",
    )
    parser.add_argument(
        "--threads", "-t", type=int, default=4,
        help="Lean threads per process (default 4). Total CPU = workers × threads.",
    )
    parser.add_argument(
        "--chunk-size", "-c", type=int, default=5,
        help="Files per Lean process (default 5). All Goedel files share "
             "`import Mathlib`, so chunking is safe. Higher = less import "
             "overhead but coarser error recovery.",
    )
    parser.add_argument(
        "--timeout", type=int, default=600,
        help="Timeout per file in seconds (default 600).",
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
        "--elab-stats", action="store_true",
        help="Show elaboration success/failure breakdown from existing reports.",
    )
    parser.add_argument(
        "--force-copy", action="store_true",
        help="Re-copy source files even if they already exist.",
    )
    args = parser.parse_args()

    # Elab stats mode
    if args.elab_stats:
        print_elab_stats(GOEDEL_OUTPUT_DIR)
        return

    # Collect-only mode
    if args.collect_only:
        if not GOEDEL_OUTPUT_DIR.exists():
            print(f"Error: output directory {GOEDEL_OUTPUT_DIR} does not exist", file=sys.stderr)
            sys.exit(1)
        dummy_results: List[OptimizationResult] = []
        for rf in sorted(GOEDEL_OUTPUT_DIR.rglob("*_report.json")):
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
        _print_batch_summary(dummy_results, GOEDEL_OUTPUT_DIR)
        return

    # Verify source dir
    if not args.source_dir.exists():
        print(f"Error: source directory {args.source_dir} does not exist", file=sys.stderr)
        print(f"Run download_goedel.py first.", file=sys.stderr)
        sys.exit(1)

    # Discover files
    print(f"Scanning {args.source_dir} ...")
    source_files = discover_goedel_files(
        source_dir=args.source_dir,
        limit=args.limit,
    )
    print(f"Found {len(source_files)} Goedel proof files.")

    if not source_files:
        print("No files to process.")
        sys.exit(0)

    if args.dry_run:
        # Quick stats
        total_bytes = sum(f.stat().st_size for f in source_files)
        print(f"Total size:    {total_bytes:,} bytes ({total_bytes/1024/1024:.1f} MB)")
        print(f"Avg size:      {total_bytes//len(source_files):,} bytes/file")
        print(f"Chunk count:   {(len(source_files)+args.chunk_size-1)//args.chunk_size}")
        print(f"Workers:       {args.workers}")
        est = (len(source_files) * 45) / min(args.workers, len(source_files)) / 60
        print(f"Est. time:     ~{est:.0f} min")
        print(f"\nDry run complete.")
        sys.exit(0)

    # Verify binary
    binary = LAKE_ROOT / ".lake" / "build" / "bin" / "LeanPolish"
    if not binary.exists():
        print(f"\nWarning: Compiled binary not found at {binary}")
        print("Running in interpreter mode (slower). Build with: lake build LeanPolish")
        resp = input("Continue anyway? [y/N] ").strip().lower()
        if resp != 'y':
            sys.exit(0)

    # Prepare working directory
    print(f"\nPreparing working directory at {GOEDEL_OUTPUT_DIR} ...")
    work_files = prepare_working_directory(
        source_files, args.source_dir, GOEDEL_OUTPUT_DIR,
        force=args.force_copy,
    )

    if not work_files:
        print("All files already processed. Use --collect-only to see results.")
        sys.exit(0)

    print(f"Files to optimize: {len(work_files)}")

    # Run
    results = run_goedel_batch(
        work_files,
        workers=args.workers,
        threads=args.threads,
        chunk_size=args.chunk_size,
        timeout_per_file=args.timeout,
    )


if __name__ == "__main__":
    main()
