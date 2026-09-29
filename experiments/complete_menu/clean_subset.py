#!/usr/bin/env python3
"""Budget-clean subset: files where BOTH modes (first-success, complete-menu) produced a report,
neither hit the wall-clock fold budget, and neither timed out. Lean-aware counter.

Inputs: as final_metrics.py ($DATA_DIR). Output: $OUT_DIR/clean_subset.json (default ./results).
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_metrics import corpora, file_result, cA, D, OUT
out = {}
for cn, spec in corpora().items():
    n = sA_fs = sA_cm = den = ndiff = 0
    for key in spec["items"]:
        t = (D / "corpora" / key[0] / key[1]).read_text(); a0 = cA(t)
        r = {}
        for m in ["fs", "cm"]:
            rep, sh, w, txt = file_result(m, *key)
            r[m] = (rep, sh, w, txt)
        if any(r[m][0] is None or r[m][3] is None or "[FOLD] Time budget exceeded" in r[m][3] or (r[m][2] or 0) > 1800 for m in r):
            continue
        n += 1; den += a0
        s = {m: (a0 - cA(r[m][1])) if r[m][1] else 0 for m in r}
        sA_fs += s["fs"]; sA_cm += s["cm"]; ndiff += s["fs"] != s["cm"]
    out[cn] = {"files": n, "A_tokens": den, "fs_saved": sA_fs, "cm_saved": sA_cm, "files_differing": ndiff,
               "fs_pct": 100*sA_fs/den if den else None, "cm_pct": 100*sA_cm/den if den else None}
    print(cn, out[cn])
OUT.mkdir(parents=True, exist_ok=True)
json.dump(out, open(OUT / "clean_subset.json", "w"), indent=1)
