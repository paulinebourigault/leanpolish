"""Run the LeanPolish regression smoke test.

The runner reads ``regression_baseline.json``, executes LeanPolish on each
available source file, and checks that measured savings remain within the
configured tolerance. Missing source files are reported as skipped; failures and
errors produce a nonzero exit code.

Usage:
    python3 run_regression_smoke.py [--baseline regression_baseline.json]
                                    [--tolerance-pct 5]
                                    [--timeout 600]
                                    [--workers 4]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent


def leanpolish(file_rel: str, timeout_s: int) -> dict:
    binary = REPO_ROOT / ".lake" / "build" / "bin" / "LeanPolish"
    if binary.exists():
        cmd = ["lake", "env", str(binary), file_rel]
    else:
        cmd = ["lake", "env", "lean", "--run", "LeanPolish.lean", file_rel]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"_failed": True, "_reason": f"timeout after {timeout_s}s"}
    out = proc.stdout
    json_lines = [m.group(1) for m in re.finditer(r"^\[JSON\] (.+)$", out,
                                                   re.MULTILINE)]
    if not json_lines:
        return {
            "_failed": True,
            "_reason": "no [JSON] line",
            "_stderr_tail": proc.stderr[-1200:],
            "_stdout_tail": out[-1200:],
        }
    return json.loads(json_lines[-1])


def measured_savings(parsed: dict) -> int:
    return int(parsed.get("bytes_original", 0)) - int(
        parsed.get("bytes_shortened", parsed.get("bytes_original", 0))
    )


def check_one(entry: dict, tolerance_pct: float, timeout_s: int) -> dict:
    file_rel = entry["file"]
    baseline = int(entry["baseline_savings"])
    floor = baseline - int(round(baseline * tolerance_pct / 100.0))

    abs_path = REPO_ROOT / file_rel
    if not abs_path.is_file():
        return {"file": file_rel, "status": "SKIP",
                "reason": "file not present", "baseline": baseline}

    result = leanpolish(file_rel, timeout_s)
    if result.get("_failed"):
        return {"file": file_rel, "status": "ERROR",
                "reason": result.get("_reason", "unknown"),
                "baseline": baseline,
                "stderr_tail": result.get("_stderr_tail", ""),
                "stdout_tail": result.get("_stdout_tail", "")}

    measured = measured_savings(result)
    status = "PASS" if measured >= floor else "FAIL"
    return {"file": file_rel, "status": status, "baseline": baseline,
            "measured": measured, "floor": floor,
            "delta_pct": round(100.0 * (measured - baseline) / max(baseline, 1), 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=str(REPO_ROOT / "regression_baseline.json"))
    ap.add_argument("--tolerance-pct", type=float, default=5.0)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if not shutil.which("lake"):
        print("ERROR: lake not on PATH", file=sys.stderr)
        return 2
    baseline_path = Path(args.baseline)
    if not baseline_path.is_file():
        print(f"ERROR: baseline {baseline_path} not found", file=sys.stderr)
        return 2

    entries = json.loads(baseline_path.read_text())
    print(f"=== regression smoke: {len(entries)} files, "
          f"tolerance={args.tolerance_pct}%, workers={args.workers} ===")

    results = [None] * len(entries)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        fut_to_idx = {
            ex.submit(check_one, e, args.tolerance_pct, args.timeout): i
            for i, e in enumerate(entries)
        }
        for fut in concurrent.futures.as_completed(fut_to_idx):
            i = fut_to_idx[fut]
            results[i] = fut.result()
            r = results[i]
            if r["status"] == "PASS":
                print(f"  PASS  {r['file']:<70} "
                      f"{r['measured']:>6}/{r['baseline']:<6} ({r['delta_pct']:+.1f}%)")
            elif r["status"] == "SKIP":
                print(f"  SKIP  {r['file']:<70} ({r['reason']})")
            elif r["status"] == "FAIL":
                print(f"  FAIL  {r['file']:<70} "
                      f"{r['measured']}/{r['baseline']} (floor {r['floor']})")
            else:  # ERROR
                print(f"  ERROR {r['file']:<70} {r['reason']}")

    fails = [r for r in results if r["status"] == "FAIL"]
    errors = [r for r in results if r["status"] == "ERROR"]
    skips = [r for r in results if r["status"] == "SKIP"]
    passes = [r for r in results if r["status"] == "PASS"]

    print()
    print(f"=== summary: {len(passes)} pass, {len(fails)} fail, "
          f"{len(errors)} error, {len(skips)} skip ===")
    for r in fails + errors:
        print(json.dumps(r, indent=2))
    return 0 if not fails and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
