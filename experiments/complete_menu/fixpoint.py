#!/usr/bin/env python3
"""Iterate first-success LeanPolish to a fixed point (paper Sec. 3, "Fixed-point iteration").

usage: fixpoint.py <corpus> <round1_run_dir> <workers> <max_round> [<start_round> <state_json>]

Round 1 = an existing LeanPolish run directory (outputs on the original files).
Round r+1 input for a file = round r's verified *_shortened.lean if present, else the round-r input.
Only files whose input changed in round r are re-run in round r+1 (the others are fixed points).
Optional continuation: <start_round> and the state JSON written after the previous round.

Environment:
  LEAN_PROJECT  LeanPolish Lake project containing leanpolish.py (default: <repo>/leanpolish).
                Originals are read from $LEAN_PROJECT/corpora/<corpus>/; rounds are written to
                runs/fp<r>/<corpus>/, per-round state to logs/fp_<corpus>_inputs_after_r<r>.json,
                raw Lean logs to raw/fp<r>/<corpus>/ (all relative to $LEAN_PROJECT).
  LEAN_PATH_PREFIX  extra PATH entries for lake/lean (default: ~/.elan/bin).
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path
REPO = Path(os.environ.get("LEANPOLISH_ROOT", Path(__file__).resolve().parents[2]))
if len(sys.argv) < 5 or sys.argv[1] in ("-h", "--help"):
    print(__doc__)
    sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
corpus, r1, W, R = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
START = int(sys.argv[5]) if len(sys.argv) > 5 else 2
root = Path(os.environ.get("LEAN_PROJECT", REPO / "leanpolish")).resolve()
orig_root = root / "corpora" / corpus
files = sorted(str(p.relative_to(orig_root)) for p in orig_root.rglob("*.lean") if not p.name.endswith("_shortened.lean"))
env = dict(os.environ, PATH=os.environ.get("LEAN_PATH_PREFIX", str(Path.home() / ".elan" / "bin")) + ":" + os.environ["PATH"])
(root / "logs").mkdir(parents=True, exist_ok=True)
log = open(root / "logs" / f"fp_{corpus}.log", "a")
def P(*a):
    print(time.strftime("%H:%M:%S"), *a, file=log, flush=True)
def out_of(rundir, rel):
    r = Path(rel); rep = rundir / r.with_name(r.stem + "_report.json"); sh = rundir / r.with_name(r.stem + "_shortened.lean")
    if rep.exists() and sh.exists():
        try:
            if json.loads(rep.read_text()).get("verified"):
                return sh
        except Exception:
            pass
    return None
# state: current input text path per file
inp = {f: orig_root / f for f in files}
if len(sys.argv) > 6:
    st0 = json.load(open(sys.argv[6]))
    inp = {f: (Path(p) if Path(p).is_absolute() else root / p) for f, p in st0.items()}
prev = r1
active = files
for rnd in range(START, R + 1):
    changed = []
    for f in active:
        o = out_of(prev, f)
        if o is not None and o.read_bytes() != inp[f].read_bytes():
            inp[f] = o; changed.append(f)
    P(f"round {rnd-1} done: {len(changed)}/{len(active)} active files changed")
    json.dump({f: str(inp[f]) for f in files}, open(root / "logs" / f"fp_{corpus}_inputs_after_r{rnd-1}.json", "w"), indent=0)
    if not changed:
        P("fixed point reached"); break
    rd = root / "runs" / f"fp{rnd}" / corpus
    if rd.exists(): shutil.rmtree(rd)
    for f in changed:
        dst = rd / f; dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = inp[f].read_bytes()
        # keep a stable copy of this round's input
        dst.write_bytes(tmp)
        (root / "runs" / f"fp{rnd}_inputs" / corpus / f).parent.mkdir(parents=True, exist_ok=True)
        (root / "runs" / f"fp{rnd}_inputs" / corpus / f).write_bytes(tmp)
    for f in changed:
        inp[f] = root / "runs" / f"fp{rnd}_inputs" / corpus / f
    P(f"round {rnd} start on {len(changed)} files")
    subprocess.run(["python3", "leanpolish.py", "--batch", str(rd.relative_to(root)), "--workers", str(W),
                    "--threads", "4", "--chunk-size", "1", "--timeout", "1800"], cwd=root,
                   env=dict(env, LEANPOLISH_RAWLOG_DIR=str(root / "raw" / f"fp{rnd}" / corpus)),
                   stdout=open(root / "logs" / f"fp{rnd}_{corpus}.out", "w"), stderr=subprocess.STDOUT)
    prev = rd; active = changed
else:
    changed = [f for f in active if (o := out_of(prev, f)) is not None and o.read_bytes() != inp[f].read_bytes()]
    for f in changed: inp[f] = out_of(prev, f)
    P(f"round {R} done: {len(changed)}/{len(active)} active files changed (max rounds)")
    json.dump({f: str(inp[f]) for f in files}, open(root / "logs" / f"fp_{corpus}_inputs_after_r{R}.json", "w"), indent=0)
P("END")
