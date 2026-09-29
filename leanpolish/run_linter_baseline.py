#!/usr/bin/env python3
"""Run the linter-based proof-shortening baseline.

The script invokes ``LinterBaseline`` on individual Lean files or directory
batches and aggregates reports into the same metric family used for LeanPolish
comparisons.

Usage:
    python run_linter_baseline.py <lean-file>
    python run_linter_baseline.py --batch <dir>
    python run_linter_baseline.py --batch --server <dir>
    python run_linter_baseline.py --batch --collect-only <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class LinterResult:
    source_file: str
    output_file: Optional[str] = None
    linter_removals: int = 0
    verified: bool = False
    error: Optional[str] = None
    bytes_original: int = 0
    bytes_shortened: int = 0
    tokens_original: int = 0
    tokens_shortened: int = 0
    lines_original: int = 0
    lines_shortened: int = 0
    time_ms: int = 0
    training_pairs: List[dict] = field(default_factory=list)

    @property
    def bytes_saved(self) -> int:
        return self.bytes_original - self.bytes_shortened

    @property
    def tokens_saved(self) -> int:
        return self.tokens_original - self.tokens_shortened

    def summary(self) -> str:
        if self.error:
            return f"FAIL {self.source_file}: {self.error}"
        if self.bytes_saved > 0:
            return (
                f"OK   {self.source_file}: "
                f"{self.linter_removals} removals, "
                f"{self.bytes_saved} bytes saved "
                f"({self.bytes_original}→{self.bytes_shortened}), "
                f"{self.tokens_saved} tokens saved"
            )
        return f"--   {self.source_file}: no changes"


def _find_lake_root(search_dir: Path) -> Path:
    p = search_dir.resolve()
    while p != p.parent:
        if (p / "lakefile.lean").exists():
            return p
        p = p.parent
    raise FileNotFoundError(f"No lakefile.lean found at or above {search_dir}")


def parse_linter_output(output: str) -> dict:
    info = {"linter_removals": 0, "training_pairs": []}
    for line in output.splitlines():
        if line.startswith("[TRAINING_PAIR]"):
            try:
                pair = json.loads(line[len("[TRAINING_PAIR]"):].strip())
                info["training_pairs"].append(pair)
            except json.JSONDecodeError:
                pass
        elif line.startswith("[JSON]"):
            try:
                j = json.loads(line[6:].strip())
                info.update(j)
            except json.JSONDecodeError:
                pass
    return info


def split_multi_file_output(output: str) -> dict:
    sections = {}
    current_path = None
    current_lines = []
    for line in output.splitlines():
        if line.startswith("[FILE] "):
            if current_path is not None:
                sections[current_path] = "\n".join(current_lines)
            current_path = line[7:].strip()
            current_lines = []
        elif current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        sections[current_path] = "\n".join(current_lines)
    return sections


def _build_result(lean_file: Path, section_output: str, workspace_dir: Path) -> LinterResult:
    lean_file = lean_file.resolve()
    if not lean_file.exists():
        return LinterResult(source_file=str(lean_file), error="File not found")

    result = LinterResult(source_file=str(lean_file))

    if not section_output or "[DONE]" not in section_output:
        if section_output:
            result.error = f"No completion marker: {section_output[:300]}"
        else:
            result.error = "No output from linter"
        return result

    info = parse_linter_output(section_output)
    result.linter_removals = info.get("linter_removals", 0)
    result.verified = info.get("verified", False)
    result.bytes_original = info.get("bytes_original", 0)
    result.bytes_shortened = info.get("bytes_shortened", result.bytes_original)
    result.tokens_original = info.get("tokens_original", 0)
    result.tokens_shortened = info.get("tokens_shortened", result.tokens_original)
    result.lines_original = info.get("lines_original", 0)
    result.lines_shortened = info.get("lines_shortened", result.lines_original)
    result.time_ms = info.get("time_ms", 0)
    result.training_pairs = info.get("training_pairs", [])

    out_path = info.get("output")
    if out_path:
        result.output_file = out_path

    # Write per-file report
    report = {
        "file": str(lean_file),
        "linter_removals": result.linter_removals,
        "verified": result.verified,
        "bytes_original": result.bytes_original,
        "bytes_shortened": result.bytes_shortened,
        "bytes_saved": result.bytes_saved,
        "tokens_original": result.tokens_original,
        "tokens_shortened": result.tokens_shortened,
        "tokens_saved": result.tokens_saved,
        "lines_original": result.lines_original,
        "lines_shortened": result.lines_shortened,
        "time_ms": result.time_ms,
    }
    report_file = lean_file.with_name(lean_file.stem + "_linter_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)

    return result


def _run_file_group(workspace_dir: Path, group_files: List[Path],
                    timeout_per_file: int = 300) -> List[LinterResult]:
    lake_root = _find_lake_root(workspace_dir)
    rel_paths = [str(f.resolve().relative_to(lake_root.resolve())) for f in group_files]
    binary = lake_root / ".lake" / "build" / "bin" / "LinterBaseline"
    if binary.exists():
        cmd = ["stdbuf", "-oL", "lake", "env", str(binary)] + rel_paths
    else:
        cmd = ["stdbuf", "-oL", "lake", "env", "lean",
               "--run", "LinterBaseline.lean"] + rel_paths
    timeout_total = timeout_per_file * len(group_files) + 120

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
                   line.startswith("[DONE]") or line.startswith("[FILE_ERROR]"):
                    print(f"  [linter] {line}", flush=True)
        finally:
            timer.cancel()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            print("  [linter] Process hung on shutdown, killing", flush=True)
            _kill_group()
            proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        return [LinterResult(source_file=str(f), error="Group timeout") for f in group_files]
    except Exception as e:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return [LinterResult(source_file=str(f), error=str(e)) for f in group_files]

    output = "\n".join(output_lines)
    sections = split_multi_file_output(output)
    results = []
    for f in group_files:
        rel = str(f.resolve().relative_to(lake_root.resolve()))
        section = sections.get(rel, "")
        r = _build_result(f, section, lake_root)
        results.append(r)
    return results


def run_batch(target_dir: Path, workers: int = 4, chunk_size: int = 10,
              timeout: int = 300, collect_only: bool = False):
    lake_root = _find_lake_root(target_dir)
    target_dir = target_dir.resolve()

    # Collect .lean files recursively (skip artifact suffixes and hidden files)
    all_files = sorted([
        f for f in target_dir.rglob("*.lean")
        if not f.name.endswith("_shortened.lean")
        and not f.name.endswith("_linter.lean")
        and not f.name.startswith(".")
    ])
    total = len(all_files)
    print(f"Found {total} .lean files in {target_dir}")

    if collect_only:
        _collect_and_report(target_dir, all_files)
        return

    # Skip files that already have linter reports
    pending = []
    for f in all_files:
        report_file = f.with_name(f.stem + "_linter_report.json")
        if not report_file.exists():
            pending.append(f)
    print(f"  {len(pending)} files need processing ({total - len(pending)} already done)")

    if not pending:
        _collect_and_report(target_dir, all_files)
        return

    # Chunk files for shared-env processing
    chunks = [pending[i:i+chunk_size] for i in range(0, len(pending), chunk_size)]
    print(f"  {len(chunks)} chunks of ≤{chunk_size} files, {workers} worker(s)")

    results: List[LinterResult] = []
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_file_group, target_dir, chunk, timeout): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk_results = future.result()
            results.extend(chunk_results)
            done += len(chunk_results)
            improved = sum(1 for r in chunk_results if r.bytes_saved > 0)
            print(f"  [{done}/{len(pending)}] chunk done: {improved}/{len(chunk_results)} improved",
                  flush=True)

    # Append training pairs to JSONL
    jsonl_path = target_dir / "linter_training_data.jsonl"
    pair_count = 0
    with open(jsonl_path, "a") as jf:
        for r in results:
            for pair in r.training_pairs:
                jf.write(json.dumps(pair) + "\n")
                pair_count += 1
    if pair_count:
        print(f"  Wrote {pair_count} training pairs to {jsonl_path}")

    _collect_and_report(target_dir, all_files)


def _collect_and_report(target_dir: Path, all_files: List[Path]):
    """Aggregate all per-file reports into a summary."""
    total_files = len(all_files)
    reports = []
    for f in all_files:
        report_file = f.with_name(f.stem + "_linter_report.json")
        if report_file.exists():
            with open(report_file) as rf:
                reports.append(json.load(rf))

    if not reports:
        print("No linter reports found.")
        return

    improved = [r for r in reports if r.get("bytes_saved", 0) > 0]
    total_bytes_saved = sum(r.get("bytes_saved", 0) for r in reports)
    total_tokens_saved = sum(r.get("tokens_saved", 0) for r in reports)
    total_removals = sum(r.get("linter_removals", 0) for r in reports)

    # Compute means over improved files only
    if improved:
        mean_byte_pct = sum(
            r["bytes_saved"] / max(r["bytes_original"], 1) * 100
            for r in improved
        ) / len(improved)
        mean_token_pct = sum(
            r["tokens_saved"] / max(r["tokens_original"], 1) * 100
            for r in improved
        ) / len(improved)
    else:
        mean_byte_pct = 0
        mean_token_pct = 0

    print(f"\n{'='*60}")
    print("LINTER BASELINE SUMMARY")
    print(f"{'='*60}")
    print(f"  Total files:          {total_files}")
    print(f"  Reports collected:    {len(reports)}")
    print(f"  Files improved:       {len(improved)} ({len(improved)/max(len(reports),1)*100:.1f}%)")
    print(f"  Files unchanged:      {len(reports) - len(improved)}")
    print(f"  Total removals:       {total_removals}")
    print(f"  Total bytes saved:    {total_bytes_saved}")
    print(f"  Total tokens saved:   {total_tokens_saved}")
    if improved:
        print(f"  Mean byte reduction:  {mean_byte_pct:.1f}% (improved files only)")
        print(f"  Mean token reduction: {mean_token_pct:.1f}% (improved files only)")
    print(f"{'='*60}")

    # Write aggregate report
    aggregate = {
        "tool": "LinterBaseline",
        "total_files": total_files,
        "reports_collected": len(reports),
        "files_improved": len(improved),
        "files_unchanged": len(reports) - len(improved),
        "total_removals": total_removals,
        "total_bytes_saved": total_bytes_saved,
        "total_tokens_saved": total_tokens_saved,
        "mean_byte_reduction_pct": round(mean_byte_pct, 2),
        "mean_token_reduction_pct": round(mean_token_pct, 2),
    }
    agg_path = target_dir / "linter_baseline_report.json"
    with open(agg_path, "w") as f:
        json.dump(aggregate, f, indent=2)
    print(f"  Aggregate report: {agg_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Run the linter-based proof-shortening baseline on Lean files"
    )
    parser.add_argument("target", type=Path, help="Lean file or directory")
    parser.add_argument("--batch", action="store_true", help="Process all .lean files in directory")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default: 4)")
    parser.add_argument("--chunk-size", type=int, default=10, help="Files per Lean process (default: 10)")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per file in seconds (default: 300)")
    parser.add_argument("--server", action="store_true", help="Medium parallel preset (8 workers)")
    parser.add_argument("--laptop", action="store_true", help="Local preset (1 worker, chunk=5)")
    parser.add_argument("--collect-only", action="store_true", help="Aggregate existing reports without running the baseline")

    args = parser.parse_args()

    if args.server:
        args.workers = 8
        args.chunk_size = 20
    elif args.laptop:
        args.workers = 1
        args.chunk_size = 5

    if args.batch:
        if not args.target.is_dir():
            print(f"Error: {args.target} is not a directory", file=sys.stderr)
            sys.exit(1)
        run_batch(args.target, args.workers, args.chunk_size, args.timeout, args.collect_only)
    else:
        if not args.target.is_file():
            print(f"Error: {args.target} is not a file", file=sys.stderr)
            sys.exit(1)
        lake_root = _find_lake_root(args.target.parent)
        results = _run_file_group(args.target.parent, [args.target], args.timeout)
        for r in results:
            print(r.summary())


if __name__ == "__main__":
    main()
