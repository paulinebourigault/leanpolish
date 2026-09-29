#!/usr/bin/env python3
"""Fixed-point iteration metrics (LeanPolish first-success, iterated; paper Table 4).

Input:  $DATA_DIR/logs/fp_<corpus>_inputs_after_r<r>.json (state after round r, from fixpoint.py),
        $DATA_DIR/corpora/<corpus>/ (originals) and the per-round files the state points to.
        Absolute paths in the state files are re-rooted under $DATA_DIR (prefix $FP_WORKDIR_PREFIX).
        Input-file lists: $FILE_LISTS (default <repo>/experiments/metrics/file_lists) and
        minif2f_subsample100.txt (this folder).
Output: $OUT_DIR/fixedpoint_metrics.json and fixedpoint_table.md (default OUT_DIR: ./results).
Reports whole-corpus reduction vs the ORIGINAL files with the Lean-aware counter (primary) and the
comment-counting counter, plus the number of files changed per round.
Environment: DATA_DIR (default ./data), FILE_LISTS, OUT_DIR, LEANPOLISH_ROOT.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("LEANPOLISH_ROOT", HERE.parents[1]))
sys.path.insert(0, str(REPO / "leanpolish"))
from retokenize_appendixL import count_appL  # noqa: E402
from lean_counter import count_lean_tokens as cA  # noqa: E402

D = Path(os.environ.get("DATA_DIR", HERE / "data"))
FL = Path(os.environ.get("FILE_LISTS", REPO / "experiments" / "metrics" / "file_lists"))
OUT = Path(os.environ.get("OUT_DIR", HERE / "results"))
WORKDIR_PREFIX = os.environ.get("FP_WORKDIR_PREFIX", "/")
SETS = {
    "putnam_verified": [("PB-verified (19)", [Path(x).name for x in (FL / "putnam_verified.txt").read_text().split()])],
    "minif2f": [("miniF2F-100 (fixed subsample)", [x.strip() + ".lean" for x in (HERE / "minif2f_subsample100.txt").read_text().split()]),
                ("miniF2F (351)", [Path(x).name for x in (FL / "minif2f.txt").read_text().split()])],
    "axiom_r2": [("Putnam 2025 AxiomProver (12)", ["/".join(Path(x).parts[-2:]) for x in (FL / "putnam2025.txt").read_text().split()])],
}


def local(p):
    p = Path(p)
    return D / (p.relative_to(WORKDIR_PREFIX) if p.is_absolute() else p)


def main():
    res = {}
    lines = ["| corpus | round | files changed this round / re-run | saved A (% of original) | saved appL (%) | files differing from original |",
             "|---|---|---|---|---|---|"]
    for corpus, sets in SETS.items():
        states = {}
        r = 1
        while (D / "logs" / f"fp_{corpus}_inputs_after_r{r}.json").exists():
            states[r] = json.loads((D / "logs" / f"fp_{corpus}_inputs_after_r{r}.json").read_text())
            r += 1
        if not states:
            continue
        for name, flist in sets:
            origs = {f: (D / "corpora" / corpus / f).read_text() for f in flist}
            oA = {f: cA(t) for f, t in origs.items()}
            oB = {f: count_appL(t) for f, t in origs.items()}
            denA, denB = sum(oA.values()), sum(oB.values())
            rows = []
            prev = {f: str(D / "corpora" / corpus / f) for f in flist}
            for rr, st in sorted(states.items()):
                cur = {f: local(st[f]) for f in flist}
                sA = sB = 0
                diff = 0
                for f in flist:
                    t = Path(cur[f]).read_text()
                    if t != origs[f]:
                        diff += 1
                    sA += oA[f] - cA(t)
                    sB += oB[f] - count_appL(t)
                ch = sum(1 for f in flist if str(cur[f]) != str(prev[f]) and Path(cur[f]).read_bytes() != Path(prev[f]).read_bytes())
                prev = {f: str(cur[f]) for f in flist}
                rows.append({"round": rr, "changed": ch, "saved_A": sA, "pct_A": 100 * sA / denA,
                             "saved_appL": sB, "pct_appL": 100 * sB / denB, "files_differing": diff})
                lines.append(f"| {name} | {rr} | {ch} | {sA} ({100*sA/denA:.2f}%) | {sB} ({100*sB/denB:.2f}%) | {diff} |")
            res[name] = {"n_files": len(flist), "A_total": denA, "appL_total": denB, "rounds": rows}
    (OUT / "fixedpoint_metrics.json").write_text(json.dumps(res, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fixedpoint_table.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
