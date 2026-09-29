#!/usr/bin/env python3
"""Parallel complete-menu LeanPolish driver (resumable).

Runs `lake env .lake/build/bin/LeanPolish --complete-menu --skip-l2 --skip-dead-code
--skip-cleanup <files...>` over chunks of files, one Lean process per chunk,
`--procs` processes in parallel.  Raw stdout (incl. [MENU_POOL] lines) is streamed
to <logdir>/<chunk_id>.log; a chunk is skipped on resume if its log ends with a
[CHUNK_EXIT] marker.  Only the tactic phase (Phase 1) matters for pools; the
other phases are skipped for speed (they run after pool emission anyway).

Usage (LEAN_PROJECT = the leanpolish/ Lake project, built with `lake build LeanPolish`):
  python3 run_pools.py --lake-root $LEAN_PROJECT --src-dir src/goedel \
      --file-list file_lists/train_files.txt --logdir $DATA_DIR/logs/goedel --procs 90
"""
import argparse
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


import queue
SLOTS = queue.Queue()


def run_chunk(args, cid, files):
    log = Path(args.logdir) / f"{cid}.log"
    if log.exists():
        try:
            tail = log.read_bytes()[-300:].decode("utf-8", "ignore")
            if "[CHUNK_EXIT]" in tail:
                return cid, "skip", 0.0
        except OSError:
            pass
    env = dict(os.environ)
    env["PATH"] = os.path.expanduser("~/.elan/bin") + ":" + env.get("PATH", "")
    cmd = ["timeout", "-k", "30", str(args.per_file_timeout * len(files) + 120),
           "lake", "env", ".lake/build/bin/LeanPolish", "--complete-menu",
           "--skip-l2", "--skip-dead-code", "--skip-cleanup", *files]
    slot = SLOTS.get()
    if slot is not None:
        cmd = ["taskset", "-c", slot] + cmd
    t0 = time.time()
    try:
      with log.open("w") as fh:
        fh.write(f"[CHUNK_FILES] {' '.join(files)}\n[CHUNK_CPUS] {slot}\n")
        fh.flush()
        rc = subprocess.call(cmd, cwd=args.lake_root, stdout=fh,
                             stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
        dt = time.time() - t0
        fh.write(f"\n[CHUNK_EXIT] rc={rc} wall_s={dt:.1f}\n")
    finally:
        SLOTS.put(slot)
    return cid, rc, dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lake-root", required=True)
    ap.add_argument("--src-dir", required=True, help="dir relative to lake root holding .lean files")
    ap.add_argument("--file-list", default=None, help="basenames, in run order (default: all)")
    ap.add_argument("--logdir", required=True)
    ap.add_argument("--procs", type=int, default=64)
    ap.add_argument("--chunk-size", type=int, default=4)
    ap.add_argument("--per-file-timeout", type=int, default=600)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cpus-per-proc", type=int, default=1,
                    help="pin each Lean process to its own disjoint CPU set (taskset); 0 = no pinning")
    ap.add_argument("--first-cpu", type=int, default=0)
    args = ap.parse_args()
    Path(args.logdir).mkdir(parents=True, exist_ok=True)
    src = Path(args.lake_root) / args.src_dir
    if args.file_list:
        names = [l.strip() for l in open(args.file_list) if l.strip()]
    else:
        names = sorted(p.relative_to(src).as_posix() for p in src.rglob("*.lean")
                       if not p.name.endswith(("_shortened.lean", "_report.lean")))
    if args.limit:
        names = names[: args.limit]
    rel = [f"{args.src_dir}/{n}" for n in names if (src / n).exists()]
    chunks = [rel[i:i + args.chunk_size] for i in range(0, len(rel), args.chunk_size)]
    print(f"{len(rel)} files, {len(chunks)} chunks, {args.procs} procs", flush=True)
    avail = sorted(os.sched_getaffinity(0))  # respects the container cpuset
    for k in range(args.procs):
        if args.cpus_per_proc > 0:
            a = args.first_cpu + k * args.cpus_per_proc
            ids = avail[a:a + args.cpus_per_proc]
            assert len(ids) == args.cpus_per_proc, "not enough CPUs in affinity mask"
            SLOTS.put(",".join(map(str, ids)))
        else:
            SLOTS.put(None)
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(args.procs) as ex:
        futs = [ex.submit(run_chunk, args, f"c{i:05d}", c) for i, c in enumerate(chunks)]
        for f in as_completed(futs):
            cid, rc, dt = f.result()
            done += 1
            print(f"[{time.time()-t0:7.0f}s] {done}/{len(chunks)} {cid} rc={rc} {dt:.0f}s", flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
