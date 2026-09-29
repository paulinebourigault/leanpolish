#!/usr/bin/env python3
"""Run LeanPolish through persistent worker processes.

Each worker loads a bootstrap Lean file once, then receives compatible source
files over stdin. The pool records per-file logs, enforces time and memory
limits, and writes a summary JSON for downstream aggregation. Files whose import
prefix is not covered by the bootstrap file are skipped before dispatch.

Usage:
    python3 run_worker_pool.py --bootstrap _mathlib_bootstrap.lean \
        --umbrella Mathlib --umbrella Batteries --outdir OUT_DIR FILE.lean ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ── header utilities (no regex) ──────────────────────────────────────────
def extract_imports(path: Path) -> frozenset[str]:
    """Return the set of `import X` modules at the head of `path`.

    We stop at the first non-blank, non-comment, non-import line — that's
    where Lean's header ends.  Pure str ops, no regex.
    """
    imports: set[str] = set()
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("--"):
                    continue
                if line.startswith("/-"):
                    # naive block-comment skip; orchestrator-level only
                    continue
                if line.startswith("import "):
                    mod = line[len("import "):].strip().split()[0]
                    imports.add(mod)
                    continue
                # any other token => header is over
                break
    except OSError as e:
        print(f"[ORCH][WARN] cannot read header of {path}: {e}", file=sys.stderr)
    return frozenset(imports)


# ── worker state ─────────────────────────────────────────────────────────
@dataclass
class Worker:
    wid: int
    proc: subprocess.Popen
    bootstrap: Path
    log_dir: Path
    files_done: int = 0
    rss_kb_peak: int = 0
    current: str | None = None
    current_t0: float = 0.0
    output_buf: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


def spawn_worker(wid: int, bootstrap: Path, log_dir: Path,
                 lake_cmd: list[str], extra_flags: list[str],
                 cwd: Path) -> Worker:
    cmd = lake_cmd + ["--worker", str(bootstrap), *extra_flags]
    log_dir.mkdir(parents=True, exist_ok=True)
    # start_new_session=True puts the worker (and any grandchildren that
    # `lake env` spawns, e.g. the actual LeanPolish binary) into a fresh
    # process group so the watchdog can SIGKILL the whole tree with
    # os.killpg.  Without this, killing only `lake env` leaves the
    # long-running Lean process orphaned and still consuming a CPU core.
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(cwd),
        text=True,
        bufsize=1,  # line-buffered
        start_new_session=True,
    )
    w = Worker(wid=wid, proc=proc, bootstrap=bootstrap, log_dir=log_dir)
    return w


def wait_until_ready(w: Worker, timeout_s: float) -> bool:
    """Block until the worker prints `[WORKER_READY]` or dies/timeouts."""
    t0 = time.time()
    assert w.proc.stdout is not None
    while time.time() - t0 < timeout_s:
        line = w.proc.stdout.readline()
        if not line:
            return False  # EOF / death
        w.output_buf.append(line)
        if line.startswith("[WORKER_READY]"):
            return True
    return False


def flush_per_file_log(w: Worker, path: str, dt_ms: int) -> Path:
    """Write the buffered per-file output to ``<log_dir>/<basename>__<hash>.log``.

    The unique key is derived from the full input path so that
    distinct input files with colliding basenames (e.g. mathlib's many
    `Basic.lean` / `Defs.lean`, or every Putnam folder's `solution.lean`)
    get distinct log files. Format:

        ``<stem>__<8-char SHA1 of full path>.log``

    Keeps the human-readable basename as a prefix so ``ls logs/Basic*``
    still works, and the 8-hex-char tail guarantees one-to-one
    input-file-to-log-file mapping (collision probability ~10^-9 across
    a corpus of 10^5 files).
    """
    p = Path(path)
    base = p.stem
    # SHA1 over the absolute path string, first 8 hex chars: stable
    # across runs, unique per input, short. This is only a filename
    # disambiguator, not a security boundary.
    digest = hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:8]
    log_path = w.log_dir / f"{base}__{digest}.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write("".join(w.output_buf))
        f.write(f"\n[ORCH] wall_ms={dt_ms} worker={w.wid}\n")
    w.output_buf.clear()
    return log_path


def read_until_done(w: Worker, expected_path: str) -> tuple[bool, int]:
    """Read worker stdout until a `[WORKER_DONE] "<path>" <ms>` line.

    Returns (success, wall_ms).  success=False on EOF (worker died).
    """
    assert w.proc.stdout is not None
    while True:
        line = w.proc.stdout.readline()
        if not line:
            return False, 0
        w.output_buf.append(line)
        if line.startswith("[WORKER_DONE]"):
            # Format: [WORKER_DONE] "escaped/path" 12345
            try:
                rest = line[len("[WORKER_DONE]"):].strip()
                # rest = "..." 12345 ; split from the right on the last space
                end_quote = rest.rfind('"')
                if end_quote <= 0:
                    return True, 0
                ms_str = rest[end_quote + 1:].strip()
                return True, int(ms_str) if ms_str.isdigit() else 0
            except (ValueError, IndexError):
                return True, 0


# ── RSS watchdog (Linux /proc) ───────────────────────────────────────────
def _killpg(pid: int) -> None:
    """SIGKILL the entire process group led by `pid`.

    The worker is spawned via `lake env <bin>`, which means `pid` is the
    `lake` shim and the actual long-running Lean process is its child.
    Sending SIGKILL to the shim alone leaves the Lean child orphaned
    (re-parented to init) and still hot on a CPU core.  We therefore
    spawn workers with `start_new_session=True` so they form their own
    process group, and kill the whole group here.
    """
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def read_rss_kb(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1])
    except (OSError, ValueError):
        pass
    return 0


def watchdog(workers: dict[int, Worker], rss_limit_kb: int,
             per_file_timeout_s: float,
             stop_evt: threading.Event, kill_log: list[str]) -> None:
    while not stop_evt.is_set():
        for w in list(workers.values()):
            if w.proc.poll() is not None:
                continue
            # ── RSS guard
            rss = read_rss_kb(w.proc.pid)
            if rss > w.rss_kb_peak:
                w.rss_kb_peak = rss
            if rss_limit_kb > 0 and rss > rss_limit_kb:
                kill_log.append(
                    f"[ORCH][WATCHDOG] worker {w.wid} pid={w.proc.pid} "
                    f"RSS={rss//1024}MB > limit={rss_limit_kb//1024}MB; "
                    f"killing (current_file={w.current})"
                )
                _killpg(w.proc.pid)
                continue
            # ── Per-file wall-time guard.  A worker stuck inside Lean
            # elaboration cannot be interrupted from the Lean side
            # (no yield point in many tactic loops), so the only safe
            # remedy is SIGKILL + respawn.  Long-tail files are dropped
            # from the output with status="timeout" so the corpus pass
            # always completes.
            if (per_file_timeout_s > 0 and w.current is not None
                    and time.time() - w.current_t0 > per_file_timeout_s):
                kill_log.append(
                    f"[ORCH][WATCHDOG] worker {w.wid} pid={w.proc.pid} "
                    f"file={w.current} ran for "
                    f"{time.time() - w.current_t0:.0f}s > "
                    f"limit={per_file_timeout_s:.0f}s; killing"
                )
                _killpg(w.proc.pid)
        stop_evt.wait(2.0)


# ── orchestrator ─────────────────────────────────────────────────────────
def orchestrate(args: argparse.Namespace) -> int:
    files = [Path(p) for p in args.files]
    files = [p for p in files if p.is_file()]
    # Built-in safety: previous tool outputs sitting next to inputs
    # would otherwise be re-processed.  Always exclude `_shortened.lean`
    # (the canonical output suffix produced by LeanPolish).
    excludes = list(args.exclude_glob) + ["_shortened.lean"]
    before = len(files)
    files = [p for p in files if not any(s in p.name for s in excludes)]
    if before != len(files):
        print(f"[ORCH] excluded {before - len(files)} file(s) matching "
              f"{excludes}", file=sys.stderr)
    if not files:
        print("[ORCH] no input files", file=sys.stderr)
        return 1

    bootstrap = Path(args.bootstrap).resolve()
    if not bootstrap.is_file():
        print(f"[ORCH] bootstrap file not found: {bootstrap}", file=sys.stderr)
        return 1

    boot_imports = extract_imports(bootstrap)
    print(f"[ORCH] bootstrap imports ({len(boot_imports)}): "
          f"{sorted(boot_imports)[:5]}{'…' if len(boot_imports) > 5 else ''}",
          file=sys.stderr)

    # Umbrella imports: a bootstrap module U covers any candidate import
    # whose name starts with '<U>.' iff U is both declared in the bootstrap
    # AND named on --umbrella. Both conditions matter:
    #   * "declared in bootstrap" guarantees the worker actually loaded U
    #     (and hence, by Lean's transitive-import semantics, every
    #     submodule of U).
    #   * "named on --umbrella" is the explicit operator opt-in: it asserts
    #     that U is genuinely an umbrella file (e.g. mathlib's `Mathlib.lean`
    #     which does `import Mathlib.<every submodule>`). Without this opt-in
    #     we conservatively treat all imports as opaque names.
    declared_umbrellas: frozenset[str] = frozenset(
        u for u in args.umbrella if u in boot_imports
    )
    declared_umbrella_dot_prefixes: tuple[str, ...] = tuple(
        u + "." for u in declared_umbrellas
    )
    if args.umbrella:
        ignored = sorted(set(args.umbrella) - declared_umbrellas)
        if ignored:
            print(f"[ORCH][WARN] --umbrella names not declared in bootstrap, "
                  f"ignored: {ignored}", file=sys.stderr)
        if declared_umbrellas:
            print(f"[ORCH] umbrella imports active: "
                  f"{sorted(declared_umbrellas)}", file=sys.stderr)

    def _covered(mod: str) -> bool:
        """True iff `mod` is in the bootstrap's transitive import closure.
        Pure str ops (no regex), matches Lean's actual umbrella semantics:
        `import U` re-exports every `U.<sub>` declared in U's source."""
        if mod in boot_imports:
            return True
        if declared_umbrella_dot_prefixes:
            return any(mod.startswith(p) for p in declared_umbrella_dot_prefixes)
        return False

    # Soundness pre-filter: drop files whose imports aren't ⊆ bootstrap.
    accepted: list[Path] = []
    rejected: list[tuple[Path, set[str]]] = []
    for p in files:
        imps = extract_imports(p)
        missing = {m for m in imps if not _covered(m)}
        if missing:
            rejected.append((p, missing))
        else:
            accepted.append(p)
    if rejected:
        print(f"[ORCH][WARN] {len(rejected)} file(s) skipped "
              f"(imports not subset of bootstrap)", file=sys.stderr)
        for p, miss in rejected[:5]:
            print(f"  {p.name}: missing {sorted(miss)[:3]}", file=sys.stderr)
    if not accepted:
        print("[ORCH] no files survived header check", file=sys.stderr)
        return 1

    out_dir = Path(args.outdir).resolve()
    log_dir = out_dir / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    lake_cmd = args.lake_cmd.split()
    extra_flags = args.extra_flags.split() if args.extra_flags else []
    rss_limit_kb = int(args.rss_limit_gb * 1024 * 1024)

    # ── spawn workers ───────────────────────────────────────────────────
    workers: dict[int, Worker] = {}
    for wid in range(args.workers):
        print(f"[ORCH] spawning worker {wid} …", file=sys.stderr)
        w = spawn_worker(wid, bootstrap, log_dir, lake_cmd, extra_flags,
                         cwd=Path(args.cwd).resolve())
        if not wait_until_ready(w, timeout_s=args.bootstrap_timeout_s):
            print(f"[ORCH][ERR] worker {wid} failed to bootstrap", file=sys.stderr)
            sys.stderr.write("".join(w.output_buf[-30:]))
            for ww in workers.values():
                _killpg(ww.proc.pid)
            return 2
        # Drop bootstrap chatter; per-file logs start from the next [FILE].
        w.output_buf.clear()
        workers[wid] = w
        print(f"[ORCH] worker {wid} ready (pid={w.proc.pid})", file=sys.stderr)

    # ── job queue + dispatcher ──────────────────────────────────────────
    job_q: queue.Queue[Path | None] = queue.Queue()
    for p in accepted:
        job_q.put(p)
    for _ in range(args.workers):
        job_q.put(None)  # poison pill per worker

    summary_lock = threading.Lock()
    summary: dict[str, dict] = {}
    stop_evt = threading.Event()
    kill_log: list[str] = []

    wd_thread = threading.Thread(
        target=watchdog,
        args=(workers, rss_limit_kb, args.per_file_timeout_s,
              stop_evt, kill_log),
        daemon=True)
    wd_thread.start()

    def worker_loop(w: Worker) -> None:
        while True:
            job = job_q.get()
            if job is None:
                # poison pill — close stdin to let worker exit cleanly
                try:
                    if w.proc.stdin is not None and not w.proc.stdin.closed:
                        w.proc.stdin.close()
                except OSError:
                    pass
                return
            # Recycle worker if it has handled enough files (RSS drift control)
            if (args.max_files_per_worker > 0
                    and w.files_done >= args.max_files_per_worker):
                print(f"[ORCH] recycling worker {w.wid} after "
                      f"{w.files_done} files", file=sys.stderr)
                try:
                    if w.proc.stdin is not None and not w.proc.stdin.closed:
                        w.proc.stdin.close()
                    w.proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    _killpg(w.proc.pid)
                new_w = spawn_worker(w.wid, bootstrap, log_dir,
                                     lake_cmd, extra_flags,
                                     cwd=Path(args.cwd).resolve())
                if not wait_until_ready(new_w, timeout_s=args.bootstrap_timeout_s):
                    print(f"[ORCH][ERR] recycle of worker {w.wid} failed",
                          file=sys.stderr)
                    _killpg(new_w.proc.pid)
                    job_q.put(job)  # requeue
                    return
                new_w.output_buf.clear()
                workers[w.wid] = new_w
                w = new_w

            # Dispatch one file
            w.current = str(job)
            w.current_t0 = time.time()
            try:
                assert w.proc.stdin is not None
                w.proc.stdin.write(str(job.resolve()) + "\n")
                w.proc.stdin.flush()
            except OSError as e:
                print(f"[ORCH][ERR] worker {w.wid} stdin write failed: {e}",
                      file=sys.stderr)
                job_q.put(job)
                return

            ok, dt_ms = read_until_done(w, str(job))
            if not ok:
                # Worker died mid-file.  Distinguish three cases:
                #   * watchdog SIGKILL on per-file timeout    -> drop (status=timeout)
                #   * watchdog SIGKILL on RSS limit           -> drop (status=rss_killed)
                #   * any other death (bug, OOM-killer, ...)  -> requeue once
                # Identifying the cause: look up the last kill_log entry
                # mentioning this exact file.  Cheap and unambiguous
                # because kill_log only grows from the watchdog thread.
                cause = None
                file_str = str(job)
                for entry in reversed(kill_log):
                    if file_str in entry or job.name in entry:
                        if "ran for" in entry:
                            cause = "timeout"
                        elif "RSS=" in entry:
                            cause = "rss_killed"
                        break
                wall_ms = int((time.time() - w.current_t0) * 1000)
                if cause in ("timeout", "rss_killed"):
                    print(f"[ORCH][DROP] worker {w.wid} {job.name} : "
                          f"{cause} after {wall_ms}ms", file=sys.stderr)
                    with summary_lock:
                        summary[file_str] = {
                            "status": cause,
                            "wall_ms": wall_ms,
                            "worker": w.wid,
                        }
                else:
                    print(f"[ORCH][WARN] worker {w.wid} died on {job.name}; "
                          f"requeueing", file=sys.stderr)
                    with summary_lock:
                        summary[file_str] = {
                            "status": "worker_died_requeued",
                            "wall_ms": wall_ms,
                            "worker": w.wid,
                        }
                    job_q.put(job)
                # respawn for next iteration
                new_w = spawn_worker(w.wid, bootstrap, log_dir,
                                     lake_cmd, extra_flags,
                                     cwd=Path(args.cwd).resolve())
                if wait_until_ready(new_w, timeout_s=args.bootstrap_timeout_s):
                    new_w.output_buf.clear()
                    workers[w.wid] = new_w
                    w = new_w
                    w.current = None
                else:
                    _killpg(new_w.proc.pid)
                    return
                continue

            log_path = flush_per_file_log(w, str(job), dt_ms)
            w.files_done += 1
            with summary_lock:
                summary[str(job)] = {
                    "status": "ok",
                    "wall_ms": dt_ms,
                    "worker": w.wid,
                    "log": str(log_path),
                }
            w.current = None
            print(f"[ORCH] [{w.wid}] {job.name} : {dt_ms}ms "
                  f"({len(summary)}/{len(accepted)})", file=sys.stderr)

    threads = []
    for w in list(workers.values()):
        t = threading.Thread(target=worker_loop, args=(w,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()

    stop_evt.set()
    wd_thread.join(timeout=5)

    # ── summary report ─────────────────────────────────────────────────
    summary_path = out_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump({
            "bootstrap": str(bootstrap),
            "workers": args.workers,
            "files_total": len(accepted),
            "files_done": sum(1 for v in summary.values() if v.get("status") == "ok"),
            "files_failed": sum(1 for v in summary.values() if v.get("status") != "ok"),
            "skipped_header_mismatch": [str(p) for p, _ in rejected],
            "watchdog_kills": kill_log,
            "per_file": summary,
        }, f, indent=2)
    print(f"[ORCH] summary: {summary_path}", file=sys.stderr)

    failed = sum(1 for v in summary.values() if v.get("status") != "ok")
    return 0 if failed == 0 else 3


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bootstrap", required=True,
                    help="Lean file whose imports are loaded once per worker. "
                         "Must be a SUPERSET of imports in every dispatched file.")
    ap.add_argument("--outdir", required=True,
                    help="Directory for per-file logs and summary.json.")
    ap.add_argument("--workers", type=int, default=8,
                    help="Number of persistent worker processes.")
    ap.add_argument("--lake-cmd", default="lake env .lake/build/bin/LeanPolish",
                    help="Command prefix that launches LeanPolish.")
    ap.add_argument("--cwd", default=".",
                    help="Working directory for workers (must contain .lake/).")
    ap.add_argument("--extra-flags", default="",
                    help="Extra flags forwarded to LeanPolish "
                         "(e.g. '--block-local --skip-cleanup').")
    ap.add_argument("--rss-limit-gb", type=float, default=12.0,
                    help="Per-worker RSS cap; exceeding workers are killed "
                         "and respawned. 0 disables the watchdog.")
    ap.add_argument("--max-files-per-worker", type=int, default=50,
                    help="Recycle a worker after this many files (RSS drift). "
                         "0 disables recycling.")
    ap.add_argument("--bootstrap-timeout-s", type=float, default=300.0,
                    help="Max seconds to wait for [WORKER_READY] after spawn.")
    ap.add_argument("--per-file-timeout-s", type=float, default=180.0,
                    help="Per-file wall-time limit.  Workers exceeding this are "
                         "SIGKILLed and respawned; the offending file is recorded "
                         "as status='timeout' in summary.json and dropped from the "
                         "queue (no requeue: it would just hang the next worker too). "
                         "0 disables the per-file watchdog (NOT recommended for "
                         "long-tail corpora).")
    ap.add_argument("--exclude-glob", action="append", default=[],
                    help="File-name substrings to exclude from inputs (repeatable). "
                         "Default applied: '_shortened.lean' to skip prior tool "
                         "outputs that may have leaked into the input directory.")
    ap.add_argument("--umbrella", action="append", default=[],
                    help="Module name(s) declared in the bootstrap that act as "
                         "umbrella imports — i.e. importing them transitively "
                         "imports every submodule below them. When a candidate "
                         "file imports M and M starts with '<U>.' for some "
                         "umbrella U declared on the bootstrap, the import is "
                         "considered satisfied even though M is not literally "
                         "in the bootstrap's import set. Repeatable. Standard "
                         "use: '--umbrella Mathlib' for a bootstrap that does "
                         "`import Mathlib` (the canonical mathlib4 umbrella "
                         "file `Mathlib.lean` recursively re-exports every "
                         "submodule, so any `import Mathlib.X.Y` in a candidate "
                         "file is already in the worker's environment).")
    ap.add_argument("files", nargs="+", help="Lean files to process.")
    return ap.parse_args()


if __name__ == "__main__":
    sys.exit(orchestrate(parse_args()))
