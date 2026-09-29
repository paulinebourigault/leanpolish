#!/usr/bin/env python3
"""High-throughput REPL screening of generated proof-edit candidates.

Uses a pool of persistent leanprover-community/repl workers (Mathlib imported
once per worker, env 0 reused) to elaborate the full spliced file body of every
unique candidate. This is a SCREENING stage in the two-lane design: final
reported verdicts for screen-passing candidates come from
leanpolish/verify_pair.py under the pinned project checkout.

Cheap short-circuits (no REPL call):
  splice_mismatch   original text != source bytes at [start,end)
  noop              replacement identical to original span (valid, zero savings)
  matches_reference replacement == the dataset's kernel-verified reference
  introduces_sorry  replacement adds sorry/admit not present in the original

Baseline handling: each source file's unmodified body is elaborated once; if
the baseline fails in the REPL environment, its candidates get
screen_baseline_broken and are deferred entirely to verify_pair.py.

Resumable: completed unique keys are appended to --out as they finish; rerun
skips them.

Requires a leanprover-community/repl client module importable as `repl_client`
(directory given by REPL_CLIENT_DIR; not shipped) exposing
ReplWorker(project_dir, check_timeout_s) and parse_repl_response(resp).
LEAN_PROJECT = Lean project with Mathlib v4.21.0 (default: <archive>/leanpolish).
Output: --out screen jsonl (+ <out>.summary.json).

Usage:
  REPL_CLIENT_DIR=/path/to/repl_client_parent LEAN_PROJECT=/path/to/leanpolish \
  python screen_candidates.py --cands cands_frozen.jsonl cands_sft.jsonl \
      --root $EVAL_ROOT --workers 6 --out screen_results.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path

IMPORT_RE = re.compile(r"^import\s+(\S+)\s*$")
SORRY_RE = re.compile(r"\b(sorry|admit|sorryAx)\b")


def find_source(file_field: str, roots) -> Path | None:
    p = Path(file_field)
    if p.is_absolute() and p.exists():
        return p
    for root in roots:
        cand = root / file_field
        if cand.exists():
            return cand
    base = p.name
    for root in roots:
        for hit in root.rglob(base):
            return hit
    return None


def strip_imports(text: str) -> tuple[str, list[str]]:
    """Remove leading import lines (they are provided by the pooled env)."""
    lines = text.split("\n")
    body_start = 0
    imports = []
    for i, line in enumerate(lines):
        m = IMPORT_RE.match(line.strip())
        if m:
            imports.append(m.group(1))
            body_start = i + 1
        elif line.strip() == "" and body_start == i:
            body_start = i + 1
        else:
            break
    return "\n".join(lines[body_start:]), imports


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("--root", action="append", default=[], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--check-timeout", type=float, default=120.0)
    args = ap.parse_args()

    sys.path.insert(0, os.path.expanduser(os.environ.get("REPL_CLIENT_DIR", ".")))
    from repl_client.repl import ReplWorker
    from repl_client.parse import parse_repl_response

    roots = [Path(r).expanduser().resolve() for r in args.root]

    # ── load candidates, resolve sources, short-circuit ──────────────────────
    cands = []
    for path in args.cands:
        with open(path) as f:
            for line in f:
                cands.append(json.loads(line))
    print(f"[screen] {len(cands)} candidate rows")

    def ckey(c) -> str:
        return hashlib.sha256(
            f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}"
            .encode()).hexdigest()

    done_keys: dict[str, dict] = {}
    out_path = Path(args.out)
    if out_path.exists():
        with out_path.open() as f:
            for line in f:
                r = json.loads(line)
                done_keys[r["key"]] = r
        print(f"[screen] resuming: {len(done_keys)} unique keys already done")
    out_f = out_path.open("a")
    out_lock = threading.Lock()

    src_cache: dict[str, bytes] = {}
    def source_bytes(file_field: str) -> bytes | None:
        if file_field not in src_cache:
            p = find_source(file_field, roots)
            src_cache[file_field] = p.read_bytes() if p else None
        return src_cache[file_field]

    jobs: dict[str, dict] = {}          # key -> job (unique REPL work)
    trivial: dict[str, dict] = {}       # key -> short-circuit result
    baseline_files: set[str] = set()
    stats = Counter()

    for c in cands:
        key = ckey(c)
        if key in done_keys or key in jobs or key in trivial:
            stats["dedup"] += 1
            continue
        src = source_bytes(c["file"])
        if src is None:
            trivial[key] = {"key": key, "screen_verdict": "source_missing"}
            continue
        s, e = c["start_byte"], c["end_byte"]
        orig_span = src[s:e].decode("utf-8", "replace")
        if orig_span != c["original"]:
            trivial[key] = {"key": key, "screen_verdict": "splice_mismatch"}
            continue
        repl_txt = c["replacement"]
        if repl_txt.strip() == c["original"].strip():
            trivial[key] = {"key": key, "screen_verdict": "noop"}
            continue
        ref = c.get("reference_replacement")
        if ref is not None and repl_txt == ref:
            trivial[key] = {"key": key, "screen_verdict": "matches_reference"}
            continue
        if SORRY_RE.search(repl_txt) and not SORRY_RE.search(c["original"]):
            trivial[key] = {"key": key, "screen_verdict": "introduces_sorry"}
            continue
        spliced = (src[:s] + repl_txt.encode("utf-8") + src[e:]).decode("utf-8", "replace")
        body, imports = strip_imports(spliced)
        bad_imports = [i for i in imports if i not in ("Mathlib", "Aesop")]
        if bad_imports:
            trivial[key] = {"key": key, "screen_verdict": "unsupported_import",
                            "screen_error": ",".join(bad_imports)}
            continue
        jobs[key] = {"key": key, "file": c["file"], "body": body}
        baseline_files.add(c["file"])

    for r in trivial.values():
        stats[r["screen_verdict"]] += 1
        with out_lock:
            out_f.write(json.dumps(r) + "\n")
    out_f.flush()
    print(f"[screen] short-circuit: {dict(stats)}")
    print(f"[screen] {len(jobs)} unique REPL jobs over {len(baseline_files)} files")

    # ── REPL worker pool ─────────────────────────────────────────────────────
    project_dir = os.environ.get("LEAN_PROJECT", os.environ.get("LEAN_PROJECT_DIR",
                                 os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "leanpolish"))))
    print(f"[screen] starting {args.workers} REPL workers on {project_dir} "
          f"(Mathlib import can take minutes)…")
    workers = queue.Queue()
    def boot(i):
        w = ReplWorker(project_dir=project_dir,
                       check_timeout_s=args.check_timeout)
        w.start()
        workers.put(w)
        print(f"[screen] worker {i} ready", flush=True)
    boots = [threading.Thread(target=boot, args=(i,)) for i in range(args.workers)]
    for b in boots: b.start()
    for b in boots: b.join()

    def run_snippet(body: str) -> dict:
        w = workers.get()
        try:
            t0 = time.monotonic()
            if not w.alive():
                w.restart()
            resp = w._roundtrip({"cmd": body, "env": w.env_id}, args.check_timeout)
            elapsed = time.monotonic() - t0
            if resp is None:
                w.restart()
                return {"ok": False, "error": "timeout", "elapsed": elapsed}
            ok, err, log = parse_repl_response(resp)
            return {"ok": ok, "error": err, "elapsed": elapsed,
                    "log": (log or "")[:500]}
        finally:
            workers.put(w)

    # ── baselines first ──────────────────────────────────────────────────────
    baseline_ok: dict[str, bool] = {}
    bl_files = sorted(baseline_files)
    def do_baseline(ff):
        src = source_bytes(ff).decode("utf-8", "replace")
        body, _ = strip_imports(src)
        res = run_snippet(body)
        baseline_ok[ff] = res["ok"]
        if not res["ok"]:
            print(f"[screen] BASELINE FAIL {ff}: {res.get('error')}", flush=True)

    import concurrent.futures as cf
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(do_baseline, bl_files))
    n_bad = sum(1 for v in baseline_ok.values() if not v)
    print(f"[screen] baselines: {len(bl_files) - n_bad}/{len(bl_files)} pass "
          f"({time.monotonic()-t0:.0f}s)")

    # ── candidates ───────────────────────────────────────────────────────────
    job_list = sorted(jobs.values(), key=lambda j: j["key"])
    done = 0
    t0 = time.monotonic()
    def do_job(j):
        nonlocal done
        if not baseline_ok.get(j["file"], False):
            rec = {"key": j["key"], "screen_verdict": "screen_baseline_broken"}
        else:
            res = run_snippet(j["body"])
            rec = {"key": j["key"],
                   "screen_verdict": "pass" if res["ok"] else "fail",
                   "screen_error": res.get("error"),
                   "screen_elapsed_s": round(res["elapsed"], 2)}
        with out_lock:
            out_f.write(json.dumps(rec) + "\n")
            out_f.flush()
            done += 1
            if done % 50 == 0:
                rate = done / (time.monotonic() - t0)
                print(f"[screen] {done}/{len(job_list)} ({rate:.1f}/s)", flush=True)
        stats[rec["screen_verdict"]] += 1

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(do_job, job_list))
    out_f.close()

    summary = {"total_rows": len(cands), "unique_jobs": len(job_list),
               "baseline_fail_files": n_bad, "verdicts": dict(stats)}
    Path(args.out + ".summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))

    while not workers.empty():
        workers.get().close()


if __name__ == "__main__":
    main()
