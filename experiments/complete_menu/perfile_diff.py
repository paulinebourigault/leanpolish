#!/usr/bin/env python3
"""Per-file token-savings differences between first-success (base) and complete-menu (cm) runs.

usage: perfile_diff.py <corpus>
Inputs: $DATA_DIR/{corpora,runs,raw}/... (as analyze_complete_menu.py).
Output: $OUT_DIR/perfile_<corpus>.json (default ./results) and a printed summary.
"""
import json, os, sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(os.environ.get("LEANPOLISH_ROOT", _HERE.parents[1])) / "leanpolish"))
from retokenize_appendixL import count_appL
D = Path(os.environ.get("DATA_DIR", _HERE / "data"))
OUT = Path(os.environ.get("OUT_DIR", _HERE / "results"))
corpus = sys.argv[1]
rows = []
for o in sorted((D / "corpora" / corpus).rglob("*.lean")):
    r = o.relative_to(D / "corpora" / corpus)
    t0 = count_appL(o.read_text())
    rec = {"file": str(r)}
    for m in ["base", "cm"]:
        rp = D / "runs" / m / corpus / r.with_name(r.stem + "_report.json")
        sp = D / "runs" / m / corpus / r.with_name(r.stem + "_shortened.lean")
        lg = D / "raw" / m / corpus / (f"runs__{m}__{corpus}__" + str(r).replace("/", "__") + ".log")
        rep = json.loads(rp.read_text()) if rp.exists() else None
        saved = t0 - count_appL(sp.read_text()) if (rep and rep.get("verified") and sp.exists()) else 0
        txt = lg.read_text(errors="replace") if lg.exists() else ""
        wall = next((float(l.split()[1]) for l in txt.splitlines() if l.startswith("[CHUNK_WALL_S]")), None)
        rec[m] = {"saved": saved, "wall": wall, "report": rep is not None,
                  "fold_budget": "[FOLD] Time budget exceeded" in txt,
                  "err": (rep or {}).get("error") if rep else None,
                  "verified": (rep or {}).get("verified")}
    rec["delta"] = rec["cm"]["saved"] - rec["base"]["saved"]
    rows.append(rec)
d = [x for x in rows if x["delta"] != 0]
print(f"{corpus}: files {len(rows)}, differing {len(d)}, sum delta {sum(x['delta'] for x in rows)}")
for x in sorted(d, key=lambda x: x["delta"])[:25] + sorted(d, key=lambda x: -x["delta"])[:10]:
    print(x["delta"], x["file"], "base", x["base"], "cm", x["cm"])
clean = [x for x in rows if x["base"]["report"] and x["cm"]["report"]
         and not x["base"]["fold_budget"] and not x["cm"]["fold_budget"]
         and (x["base"]["wall"] or 0) < 1800 and (x["cm"]["wall"] or 0) < 1800]
print(f"CLEAN (both reported, no fold-budget hit, no timeout): files {len(clean)}, "
      f"base saved {sum(x['base']['saved'] for x in clean)}, cm saved {sum(x['cm']['saved'] for x in clean)}, "
      f"differing {sum(1 for x in clean if x['delta'])}, sum delta {sum(x['delta'] for x in clean)}")
budget = [x for x in rows if x["base"]["fold_budget"] or x["cm"]["fold_budget"]]
print(f"fold-budget hit in >=1 mode: {len(budget)} files (base {sum(1 for x in rows if x['base']['fold_budget'])}, cm {sum(1 for x in rows if x['cm']['fold_budget'])}); sum delta there {sum(x['delta'] for x in budget)}")
OUT.mkdir(parents=True, exist_ok=True)
json.dump(rows, open(OUT / f"perfile_{corpus}.json", "w"), indent=1)
