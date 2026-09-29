#!/usr/bin/env python3
"""Re-verify LeanPolish training pairs with the Lean kernel.

For each JSONL row, the verifier checks the source span, splices the proposed
replacement into a temporary file, runs ``lake env lean``, and records whether
the replacement introduces new elaboration errors relative to the original file.
The source tree is never modified.

For each input ``path/foo.jsonl``, the script writes:
    - ``path/foo.kernel_verified.jsonl`` with one verdict per row
    - ``path/foo.kernel_summary.json`` with aggregate counts

Verdict values:
  pass                : elaborated cleanly, no NEW errors vs baseline
  fail                : candidate elaboration fails, baseline elaborates
  baseline_broken     : the unmodified file already fails to elaborate
                        (cannot blame this candidate)
  source_missing      : couldn't locate source on disk (--root issue)
  splice_mismatch     : original text in JSONL != source bytes at [start,end)
  introduces_sorry    : NEW `sorry`/`sorryAx` introduced
  timeout             : exceeded --timeout-sec
  verifier_error      : harness itself crashed

Usage:
    python3 verify_pair.py ROWS.jsonl --project-root . [--root DIR] [--jobs N]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

VERIFIER_VERSION = "v0.1.0"

# Lake produces lines like:
#   ./Foo.lean:12:5: error: ...
#   ./Foo.lean:12:5: warning: ...
ERROR_LINE_RE = re.compile(r"^[^:]+:\d+:\d+:\s*error:\s*(.+)$", re.MULTILINE)
SORRY_RE = re.compile(r"\b(sorry|sorryAx)\b")

# Kinds we never re-elaborate (warning-cleanup targets are line-based and
# don't carry meaningful byte offsets, plus l2_detection has empty edits).
SKIP_TYPES_DEFAULT = {"warning_cleanup", "l2_detection"}


# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def find_source(file_field: str, roots: list[Path]) -> Path | None:
    """Locate the source file under one of the candidate roots."""
    p = Path(file_field)
    if p.is_absolute() and p.exists():
        return p
    for root in roots:
        cand = root / file_field
        if cand.exists():
            return cand
    # try just the basename in case the prefix differs
    base = p.name
    for root in roots:
        for hit in root.rglob(base):
            return hit
    return None


def splice(src_bytes: bytes, start: int, end: int, replacement: str) -> bytes:
    return src_bytes[:start] + replacement.encode("utf-8") + src_bytes[end:]


def run_lake_lean(file_path: Path, project_root: Path,
                  timeout_sec: float) -> dict:
    """Run `lake env lean <relative-path>` from project_root and capture
    a structured outcome.  Times out cleanly."""
    rel = os.path.relpath(file_path, project_root)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", rel],
            cwd=project_root, capture_output=True,
            timeout=timeout_sec, text=True)
    except subprocess.TimeoutExpired:
        return {"timeout": True, "wall_ms": int(1000 * (time.monotonic() - t0))}
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    errors = ERROR_LINE_RE.findall(out)
    return {
        "timeout": False,
        "exit_code": proc.returncode,
        "wall_ms": int(1000 * (time.monotonic() - t0)),
        "errors": errors,
        "has_sorry": bool(SORRY_RE.search(out)),
        "raw_tail": out[-2000:] if out else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Baseline cache (per source file)
# ─────────────────────────────────────────────────────────────────────────────

class BaselineCache:
    """Caches `lake env lean` results for unmodified source files so we
    only build each baseline once across all candidates touching it."""
    def __init__(self, project_root: Path, timeout_sec: float):
        self.project_root = project_root
        self.timeout_sec = timeout_sec
        self._cache: dict[Path, dict] = {}

    def get(self, src: Path) -> dict:
        if src not in self._cache:
            self._cache[src] = run_lake_lean(src, self.project_root,
                                             self.timeout_sec)
        return self._cache[src]


# ─────────────────────────────────────────────────────────────────────────────
# Per-row verification
# ─────────────────────────────────────────────────────────────────────────────

def verify_row(rec: dict, roots: list[Path], project_root: Path,
               baseline: BaselineCache, timeout_sec: float,
               skip_types: set[str]) -> dict:
    rtype = rec.get("type", "")
    out: dict = {
        "kernel_verifier_version": VERIFIER_VERSION,
        "kernel_verdict": None,
        "kernel_wall_ms": None,
        "kernel_exit_code": None,
        "kernel_error_count": None,
        "kernel_first_error": None,
        "kernel_baseline_errors": None,
    }

    if rtype in skip_types:
        out["kernel_verdict"] = "skipped_type"
        return out

    src = find_source(rec.get("file", ""), roots)
    if src is None:
        out["kernel_verdict"] = "source_missing"
        return out

    start = rec.get("start_byte"); end = rec.get("end_byte")
    if not (isinstance(start, int) and isinstance(end, int) and 0 <= start <= end):
        out["kernel_verdict"] = "splice_mismatch"
        return out

    try:
        src_bytes = src.read_bytes()
    except Exception as e:
        out["kernel_verdict"] = "verifier_error"
        out["kernel_first_error"] = f"read_bytes: {e!r}"
        return out

    # Provenance gate: if the JSONL row recorded a content_sha256 of the source
    # file at optimizer-emit time and it disagrees with the file we are about
    # to verify, the file has drifted. Mark deterministically rather than
    # trying (and failing) to splice into a different file's bytes.
    expected_sha = rec.get("content_sha256")
    if expected_sha:
        import hashlib as _hashlib
        actual_sha = _hashlib.sha256(src_bytes).hexdigest()
        if actual_sha != expected_sha:
            out["kernel_verdict"] = "stale_provenance"
            out["kernel_first_error"] = (
                f"content_sha256 drift: jsonl={expected_sha[:12]} disk={actual_sha[:12]}"
            )
            return out

    if end > len(src_bytes):
        out["kernel_verdict"] = "splice_mismatch"
        out["kernel_first_error"] = f"end={end} file_len={len(src_bytes)}"
        return out

    actual_orig = src_bytes[start:end].decode("utf-8", errors="replace")
    expected_orig = rec.get("original", "")
    if actual_orig != expected_orig:
        out["kernel_verdict"] = "splice_mismatch"
        out["kernel_first_error"] = (
            f"expected={expected_orig[:80]!r} actual={actual_orig[:80]!r}")
        return out

    # baseline (cached per file)
    base_res = baseline.get(src)
    if base_res.get("timeout"):
        out["kernel_verdict"] = "baseline_broken"
        out["kernel_first_error"] = "baseline timeout"
        return out
    base_errors = base_res.get("errors", [])
    base_has_sorry = base_res.get("has_sorry", False)
    out["kernel_baseline_errors"] = len(base_errors)
    if base_res.get("exit_code", 1) != 0 or base_errors:
        out["kernel_verdict"] = "baseline_broken"
        out["kernel_first_error"] = (base_errors[:1] or [""])[0][:200]
        return out

    # splice + run
    spliced = splice(src_bytes, start, end, rec.get("replacement", ""))
    # write next to original so relative imports resolve identically
    suffix = hashlib.sha1(
        f"{rec.get('file')}:{start}:{end}:{rec.get('replacement','')}".encode()
    ).hexdigest()[:10]
    tmp = src.with_name(f".verify_{suffix}_{src.name}")
    try:
        tmp.write_bytes(spliced)
        res = run_lake_lean(tmp, project_root, timeout_sec)
    finally:
        try: tmp.unlink()
        except FileNotFoundError: pass

    out["kernel_wall_ms"] = res.get("wall_ms")
    if res.get("timeout"):
        out["kernel_verdict"] = "timeout"
        return out

    out["kernel_exit_code"] = res.get("exit_code")
    cand_errors = res.get("errors", [])
    out["kernel_error_count"] = len(cand_errors)
    out["kernel_first_error"] = (cand_errors[:1] or [""])[0][:200]
    cand_has_sorry = res.get("has_sorry", False)

    if cand_has_sorry and not base_has_sorry:
        out["kernel_verdict"] = "introduces_sorry"
        return out
    if res.get("exit_code") != 0 or cand_errors:
        out["kernel_verdict"] = "fail"
        return out
    out["kernel_verdict"] = "pass"
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"_parse_error": True, "_raw": line[:500]})
    return rows


def process_file(input_path: Path, roots: list[Path], project_root: Path,
                 jobs: int, timeout_sec: float, skip_types: set[str],
                 limit: int | None) -> dict:
    rows = load_jsonl(input_path)
    if limit is not None:
        rows = rows[:limit]
    print(f"[{input_path.name}] {len(rows)} rows", flush=True)

    baseline = BaselineCache(project_root, timeout_sec)
    out_path = input_path.with_suffix(".kernel_verified.jsonl")
    sum_path = input_path.with_suffix(".kernel_summary.json")
    verdicts: Counter = Counter()

    # We can't easily share BaselineCache across processes; use threads
    # because the heavy work is `lake env lean`, an external subprocess
    # that releases the GIL.
    results: list[dict] = [None] * len(rows)  # type: ignore

    def worker(i_rec):
        i, rec = i_rec
        if rec.get("_parse_error"):
            return i, {"kernel_verdict": "parse_error",
                       "kernel_verifier_version": VERIFIER_VERSION}
        try:
            return i, verify_row(rec, roots, project_root, baseline,
                                  timeout_sec, skip_types)
        except Exception as e:
            return i, {"kernel_verdict": "verifier_error",
                       "kernel_first_error": repr(e),
                       "kernel_verifier_version": VERIFIER_VERSION}

    t0 = time.monotonic()
    done = 0
    with cf.ThreadPoolExecutor(max_workers=jobs) as ex:
        for i, vres in ex.map(worker, list(enumerate(rows))):
            results[i] = vres
            verdicts[vres["kernel_verdict"]] += 1
            done += 1
            if done % 50 == 0 or done == len(rows):
                elapsed = time.monotonic() - t0
                print(f"  {done}/{len(rows)}  ({elapsed:.0f}s)  "
                      f"{dict(verdicts)}", flush=True)

    with out_path.open("w") as f:
        for rec, vres in zip(rows, results):
            merged = dict(rec)
            merged.update(vres)
            f.write(json.dumps(merged, ensure_ascii=False) + "\n")

    summary = {
        "input": str(input_path),
        "output": str(out_path),
        "verifier_version": VERIFIER_VERSION,
        "total_rows": len(rows),
        "verdicts": dict(verdicts),
        "elapsed_sec": int(time.monotonic() - t0),
    }
    sum_path.write_text(json.dumps(summary, indent=2))
    print(f"  -> {out_path}")
    return summary


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+",
                   help="JSONL files to verify (e.g. *.audited.jsonl)")
    p.add_argument("--root", action="append", default=[],
                   help="root directory containing source files; may repeat")
    p.add_argument("--project-root", required=True,
                   help="lake project root (where to run `lake env lean`)")
    p.add_argument("--jobs", type=int, default=8,
                   help="parallel `lake env lean` invocations (default 8)")
    p.add_argument("--timeout-sec", type=float, default=300.0,
                   help="per-elaboration timeout (default 300s)")
    p.add_argument("--limit", type=int, default=None,
                   help="verify only the first N rows (smoke test)")
    p.add_argument("--skip-type", action="append", default=[],
                   help=f"skip records of this type (default: "
                        f"{sorted(SKIP_TYPES_DEFAULT)})")
    args = p.parse_args(list(argv))

    roots = [Path(r).resolve() for r in args.root] or [Path.cwd().resolve()]
    project_root = Path(args.project_root).resolve()
    if not (project_root / "lakefile.lean").exists() and \
       not (project_root / "lakefile.toml").exists():
        print(f"warning: {project_root} has no lakefile.lean or lakefile.toml",
              file=sys.stderr)
    skip_types = set(args.skip_type) if args.skip_type else set(SKIP_TYPES_DEFAULT)

    # Pre-flight: ensure `lake` is callable, otherwise every row would fail
    # with an opaque verifier_error.  Fail fast and loudly.
    if shutil.which("lake") is None:
        print("error: `lake` not found on PATH. "
              "Add elan to PATH (e.g. `export PATH=$HOME/.elan/bin:$PATH`).",
              file=sys.stderr)
        return 2

    grand: Counter = Counter()
    grand_total = 0
    for inp in args.inputs:
        s = process_file(Path(inp), roots, project_root,
                         args.jobs, args.timeout_sec, skip_types, args.limit)
        for k, v in s["verdicts"].items():
            grand[k] += v
        grand_total += s["total_rows"]

    print()
    print("=" * 60)
    print(f"GRAND TOTAL: {grand_total} rows")
    print("=" * 60)
    for verdict in ("pass", "fail", "introduces_sorry", "splice_mismatch",
                    "stale_provenance", "baseline_broken", "timeout",
                    "source_missing", "skipped_type", "parse_error",
                    "verifier_error"):
        if grand.get(verdict):
            print(f"  {verdict:>20}: {grand[verdict]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
