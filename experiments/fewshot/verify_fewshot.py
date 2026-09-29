#!/usr/bin/env python3
"""Exact per-candidate verification driver for the few-shot baseline.

Every candidate that could count as a success (i.e. strictly shorter than the
original span under retokenize_appendixL.count_appL, not a no-op, no literal
`sorry`) is spliced into its source file and re-elaborated by a FRESH
`lake env lean` process, using verify_pair.verify_row from leanpolish/
unchanged (same verdict semantics as the paper's exact lane: pass iff the
spliced file elaborates with exit 0 and no errors, the unmodified baseline
elaborates cleanly, span bytes match exactly, no new sorry).

Candidates that cannot count as success are classified without Lean:
  noop                 replacement == original
  not_shorter          count_appL(replacement) >= count_appL(original)
  literal_sorry        replacement contains `sorry`
They contribute zero under the paper policy (failures/non-improvements = 0).

content_sha256 is dropped for --strip-sha corpora (minif2f, putnam_verified;
see experiments/sft/README.md); byte-exact span equality
is still enforced by verify_row.

Parallel (thread pool over subprocesses, --workers), baselines cached once
per source file (shared, locked), resumable: verdicts are appended + flushed
to --out and keys already present are skipped on restart.

Inputs : candidate files from gen_fewshot.py; --root = directory holding the eval sources;
         --project-root = the Lean project (default layout: <archive>/leanpolish).
Output : --out verdicts jsonl (one row per candidate key).

Usage:
  python3 verify_fewshot.py --cands cands_fewshot_*.jsonl \
      --root "$EVAL_ROOT" --project-root "$LEAN_PROJECT" \
      --workers 24 --out verdicts_fewshot.jsonl
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import threading
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("LEANPOLISH_ROOT", HERE.parents[1]))
sys.path.insert(0, str(ROOT / "leanpolish"))
import verify_pair as vp  # noqa: E402
from retokenize_appendixL import count_appL  # noqa: E402

SORRY_RE = re.compile(r"\b(sorry|sorryAx|admit)\b")


def ckey(c) -> str:
    return hashlib.sha256(
        f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}"
        .encode()).hexdigest()


class LockedBaseline(vp.BaselineCache):
    """BaselineCache shared across threads: one elaboration per file."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._locks: dict = {}
        self._glock = threading.Lock()

    def get(self, src):
        with self._glock:
            lk = self._locks.setdefault(src, threading.Lock())
        with lk:
            return super().get(src)


def precheck(c) -> str | None:
    rep, orig = c["replacement"], c["original"]
    if rep == orig:
        return "noop"
    if count_appL(rep) >= count_appL(orig):
        return "not_shorter"
    if SORRY_RE.search(rep):
        return "literal_sorry"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("--root", action="append", required=True)
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--timeout-sec", type=float, default=300.0)
    ap.add_argument("--strip-sha", nargs="*", default=["minif2f", "putnam_verified"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    roots = [Path(r).resolve() for r in args.root]
    project_root = Path(args.project_root).resolve()

    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass

    # unique candidates (same splice from two models is verified once)
    uniq, order = {}, []
    for p in args.cands:
        with open(p) as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                k = ckey(c)
                if k not in uniq:
                    uniq[k] = c
                    order.append(k)
    pending = [k for k in order if k not in done]
    if args.limit:
        pending = pending[:args.limit]
    print(f"[verify] {len(uniq)} unique candidates, {len(done)} already done, "
          f"{len(pending)} to process", flush=True)

    baseline = LockedBaseline(project_root, args.timeout_sec)
    wlock = threading.Lock()
    fout = open(args.out, "a")
    counts: Counter = Counter()
    t0 = time.monotonic()

    def record(k, c, verdict_fields):
        row = {"key": k, "corpus": c["corpus"], "file": c["file"],
               "start_byte": c["start_byte"], "end_byte": c["end_byte"],
               "type": c["type"], "replacement": c["replacement"],
               "tok_original": count_appL(c["original"]),
               "tok_replacement": count_appL(c["replacement"])}
        row.update(verdict_fields)
        with wlock:
            fout.write(json.dumps(row, ensure_ascii=False) + "\n")
            fout.flush()
            counts[row["kernel_verdict"]] += 1

    lean_jobs = []
    for k in pending:
        c = uniq[k]
        pre = precheck(c)
        if pre:
            record(k, c, {"kernel_verdict": pre, "lane": "precheck"})
        else:
            lean_jobs.append(k)
    print(f"[verify] prechecked {len(pending) - len(lean_jobs)}; "
          f"{len(lean_jobs)} need Lean  {dict(counts)}", flush=True)

    # interleave files (round-robin by rank within file) so concurrent
    # workers hit different files and per-file baselines build in parallel
    # instead of serializing on one file's baseline lock
    lean_jobs.sort(key=lambda k: (uniq[k]["file"], uniq[k]["start_byte"], k))
    rank, seen_f = {}, Counter()
    for k in lean_jobs:
        f = uniq[k]["file"]
        rank[k] = seen_f[f]
        seen_f[f] += 1
    lean_jobs.sort(key=lambda k: (rank[k], uniq[k]["file"]))

    def work(k):
        c = dict(uniq[k])
        if c["corpus"] in args.strip_sha:
            c.pop("content_sha256", None)
        try:
            v = vp.verify_row(c, roots, project_root, baseline,
                              args.timeout_sec, vp.SKIP_TYPES_DEFAULT)
        except Exception as e:  # harness crash -> recorded, counts as fail
            v = {"kernel_verdict": "verifier_error", "kernel_first_error": repr(e)}
        v["lane"] = "exact_verify_pair"
        record(k, c, v)
        return v["kernel_verdict"]

    n = 0
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for _ in ex.map(work, lean_jobs):
            n += 1
            if n % 25 == 0 or n == len(lean_jobs):
                el = time.monotonic() - t0
                print(f"  {n}/{len(lean_jobs)} ({el:.0f}s, "
                      f"{el / n:.1f}s/cand wall) {dict(counts)}", flush=True)
    fout.close()
    print(f"[verify] done {dict(counts)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
