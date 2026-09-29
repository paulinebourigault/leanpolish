#!/usr/bin/env python3
"""Fresh-process compile check (`lake env lean`) of every file whose fixed-point state after a
given round differs from the original.

usage: fp_compile.py <corpus> <round> <parallelism>
Input:  $LEAN_PROJECT/logs/fp_<corpus>_inputs_after_r<round>.json (written by fixpoint.py)
Output: $LEAN_PROJECT/logs/fpcheck_<corpus>_r<round>.json (checked / ok / failed with first errors)
Environment: LEAN_PROJECT (default <repo>/leanpolish), LEAN_PATH_PREFIX (default ~/.elan/bin).
"""
import json, os, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
REPO = Path(os.environ.get("LEANPOLISH_ROOT", Path(__file__).resolve().parents[2]))
corpus, rnd, par = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
root = Path(os.environ.get("LEAN_PROJECT", REPO / "leanpolish")).resolve()
st = json.load(open(root / "logs" / f"fp_{corpus}_inputs_after_r{rnd}.json"))
env = dict(os.environ, PATH=os.environ.get("LEAN_PATH_PREFIX", str(Path.home() / ".elan" / "bin")) + ":" + os.environ["PATH"])
pending = {f: p for f, p in st.items() if not p.startswith("corpora/") and not p.startswith(str(root / "corpora"))}
def chk(item):
    f, p = item
    src = Path(p) if Path(p).is_absolute() else root / p
    tmp = root / "fpcheck" / corpus / f"r{rnd}" / f
    tmp.parent.mkdir(parents=True, exist_ok=True); tmp.write_bytes(src.read_bytes())
    try:
        r = subprocess.run(["lake", "env", "lean", str(tmp.relative_to(root))], cwd=root, env=env,
                           capture_output=True, text=True, timeout=3600)
        ok = r.returncode == 0
        errs = [l for l in (r.stdout + r.stderr).splitlines() if ": error" in l][:3]
        return f, ok and not errs, errs
    except subprocess.TimeoutExpired:
        return f, False, ["timeout"]
res = list(ThreadPoolExecutor(par).map(chk, pending.items()))
out = {"corpus": corpus, "round": rnd, "checked": len(res), "ok": sum(1 for _, o, _ in res if o),
       "failed": {f: e for f, o, e in res if not o}}
json.dump(out, open(root / "logs" / f"fpcheck_{corpus}_r{rnd}.json", "w"), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "failed"}), len(out["failed"]))
