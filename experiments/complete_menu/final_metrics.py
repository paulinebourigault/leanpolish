#!/usr/bin/env python3
"""Final first-success (fs) vs complete-menu (cm, cmt) metrics.

Primary token counter: A = Lean-aware comment-skipping port of LeanPolish countLeanTokens
(leanpolish/lean_counter.py). Secondary: count_appL (leanpolish/retokenize_appendixL.py).
Denominators: exact file lists from experiments/metrics/file_lists (PB-verified 19,
miniF2F 351, Putnam2025 12); Mathlib: fixed-seed 300-file sample (seed 0) of Mathlib rev 308445d.
Files not shortened / quarantined / crashed / no report count 0 saved.
Also: accepted edits, per-file runtime, menu-search cost, pool stats, ranking diagnostic.
Inputs ($DATA_DIR, default ./data): corpora/<corpus>/ originals; runs/{base,cm}/<corpus>/ and
raw/{base,cm}/<corpus>/ (first-success and complete-menu runs); cm2/{runs,raw}/cmt/ (complete-menu
with per-entry timeouts); pools/<corpus>_pools.jsonl (from analyze_complete_menu.py).
Writes $OUT_DIR/final_metrics.json and final_tables.md (default OUT_DIR: ./results).
Environment: DATA_DIR, FILE_LISTS (default <repo>/experiments/metrics/file_lists), OUT_DIR.
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("LEANPOLISH_ROOT", HERE.parents[1]))
sys.path.insert(0, str(REPO / "leanpolish"))
sys.path.insert(0, str(HERE))
from retokenize_appendixL import count_appL  # noqa: E402
from lean_counter import count_lean_tokens as cA  # noqa: E402
from analyze_complete_menu import rank_rules  # noqa: E402

D = Path(os.environ.get("DATA_DIR", HERE / "data"))
FL = Path(os.environ.get("FILE_LISTS", REPO / "experiments" / "metrics" / "file_lists"))
OUT = Path(os.environ.get("OUT_DIR", HERE / "results"))


def run_dirs(mode):
    """mode -> (runs root, raw root)"""
    if mode == "cmt":
        return D / "cm2" / "runs" / "cmt", D / "cm2" / "raw" / "cmt"
    m = {"fs": "base", "cm": "cm"}[mode]
    return D / "runs" / m, D / "raw" / m


def file_result(mode, sub, rel):
    runs, raw = run_dirs(mode)
    r = Path(rel)
    rp = runs / sub / r.with_name(r.stem + "_report.json")
    sp = runs / sub / r.with_name(r.stem + "_shortened.lean")
    m = {"fs": "base"}.get(mode, mode)
    lg = raw / sub / (f"runs__{m}__{sub}__" + str(r).replace("/", "__") + ".log")
    rep = json.loads(rp.read_text()) if rp.exists() else None
    short = sp.read_text() if (rep and rep.get("verified") and sp.exists()) else None
    txt = lg.read_text(errors="replace") if lg.exists() else None
    wall = None
    if txt:
        for line in txt.splitlines()[:3]:
            if line.startswith("[CHUNK_WALL_S]"):
                wall = float(line.split()[1])
    return rep, short, wall, txt


# corpus -> list of (subdir, relpath) and runs available
def corpora():
    out = {}
    pv = [Path(x).name for x in (FL / "putnam_verified.txt").read_text().split()]
    out["PutnamBench-verified (19)"] = {"items": [("putnam_verified", f) for f in pv], "modes": ["fs", "cm", "cmt"]}
    ax = ["/".join(Path(x).parts[-2:]) for x in (FL / "putnam2025.txt").read_text().split()]
    out["Putnam 2025 AxiomProver (12), rerun"] = {"items": [("axiom_r2", f) for f in ax], "modes": ["fs", "cm", "cmt"]}
    out["Putnam 2025 AxiomProver (12), first run"] = {"items": [("axiom", f) for f in ax], "modes": ["fs", "cm"]}
    mf = [Path(x).name for x in (FL / "minif2f.txt").read_text().split()]
    out["miniF2F-verified (351)"] = {"items": [("minif2f", f) for f in mf], "modes": ["fs", "cm"]}
    ml = []
    for b in range(1, 7):
        root = D / "corpora" / f"mathlib_b{b}"
        ml += [(f"mathlib_b{b}", str(p.relative_to(root))) for p in sorted(root.rglob("*.lean"))]
    out["Mathlib sample (300, seed 0)"] = {"items": ml, "modes": ["fs", "cm"]}
    return out


def main():
    res = {}
    for cname, spec in corpora().items():
        items = spec["items"]
        orig = {}
        for sub, rel in items:
            t = (D / "corpora" / sub / rel).read_text()
            orig[(sub, rel)] = (cA(t), count_appL(t), len(t.encode()))
        denA = sum(v[0] for v in orig.values())
        denB = sum(v[1] for v in orig.values())
        c = {"n_files": len(items), "tokens_A_total": denA, "tokens_appL_total": denB, "modes": {}}
        sites = {}
        for mode in spec["modes"]:
            sA = sB = 0
            nshort = nrep = nlog = ntac = nacc = 0
            walls, fold, missing = [], 0, []
            st = {}
            for key in items:
                rep, short, wall, txt = file_result(mode, *key)
                if txt is not None:
                    nlog += 1
                    if "[FOLD] Time budget exceeded" in txt:
                        fold += 1
                if wall is not None:
                    walls.append(wall)
                if rep is None:
                    missing.append(key[1])
                    continue
                nrep += 1
                if short is not None:
                    a = orig[key][0] - cA(short)
                    b = orig[key][1] - count_appL(short)
                    sA += max(a, 0)
                    sB += max(b, 0)
                    nshort += a > 0
                for pr in rep.get("training_pairs", []):
                    if pr.get("outcome") == "accepted":
                        nacc += 1
                        if pr.get("type") == "tactic_replacement":
                            ntac += 1
                            st[(key, pr["start_byte"], pr["end_byte"])] = pr["replacement"]
            sites[mode] = st
            c["modes"][mode] = {
                "files_with_log": nlog, "files_with_report": nrep, "files_without_report": missing,
                "saved_A": sA, "pct_A": 100 * sA / denA if denA else None,
                "saved_appL": sB, "pct_appL": 100 * sB / denB if denB else None,
                "files_shortened": nshort, "accepted_all": nacc, "accepted_tactic": ntac,
                "wall_mean": statistics.mean(walls) if walls else None,
                "wall_median": statistics.median(walls) if walls else None,
                "wall_total": sum(walls), "files_fold_budget_hit": fold,
            }
        b, k = sites["fs"], sites["cm"]
        diff = [s for s in b if s in k and b[s] != k[s]]
        c["sites_fs_vs_cm"] = {
            "same_tactic": sum(1 for s in b if s in k and b[s] == k[s]),
            "different_tactic": len(diff),
            "different_cm_shorter_chars": sum(1 for s in diff if len(k[s]) < len(b[s])),
            "different_A_token_delta": sum(cA(b[s]) - cA(k[s]) for s in diff),
            "different_byte_delta": sum(len(b[s].encode()) - len(k[s].encode()) for s in diff),
            "only_fs": sum(1 for s in b if s not in k), "only_cm": sum(1 for s in k if s not in b),
            "transitions": dict(Counter(f"{b[s]} -> {k[s]}" for s in diff).most_common(8)),
        }
        # pools (cm run) for the subdirs of this corpus
        subs = sorted({s for s, _ in items})
        keep = {(s, r) for s, r in items}
        pools = []
        for s in subs:
            pf = D / "pools" / f"{s}_pools.jsonl"
            if pf.exists():
                for line in pf.open():
                    p = json.loads(line)
                    if (s, p["file"]) in keep:
                        pools.append(p)
        nval, cost_cm, cost_fs = [], 0, 0
        rk = defaultdict(list)
        diffpick = 0
        for p in pools:
            cands = [x for x in p["candidates"] if not x["skipped"]]
            usable = [x for x in cands if x["valid"] and x["len"] < p["orig_span_bytes"]]
            sel = [x for x in cands if x["outcome"] in ("chosen", "valid_not_chosen")]
            nval.append(len(usable))
            for x in p["candidates"]:
                cost_cm += x["wall_ms"]
            for x in p["candidates"]:
                cost_fs += x["wall_ms"]
                if p["v1_pick_idx"] is not None and x["menu_idx"] == p["v1_pick_idx"]:
                    break
            if p["chosen_idx"] is not None:
                if p["v1_pick_idx"] != p["chosen_idx"]:
                    diffpick += 1
                oracle = next(x["final_tac"] for x in cands if x["menu_idx"] == p["chosen_idx"])
                for name, pool in [("all_tried", cands), ("valid_shorter", usable), ("selectable", sel)]:
                    pc = [(x["menu_idx"], x["final_tac"]) for x in pool]
                    for kk, v in rank_rules(pc, oracle, None).items():
                        rk[f"{name}:{kk}"].append(v)
                if len(sel) >= 2:
                    pc = [(x["menu_idx"], x["final_tac"]) for x in sel]
                    for kk, v in rank_rules(pc, oracle, None).items():
                        rk[f"selectable_ge2:{kk}"].append(v)
        v1 = [v for v in nval if v >= 1]
        c["pools_cm"] = {
            "sites": len(pools), "sites_ge1_valid": len(v1),
            "mean_valid_given_ge1": statistics.mean(v1) if v1 else None,
            "frac_ge2_valid_given_ge1": sum(1 for v in v1 if v >= 2) / len(v1) if v1 else None,
            "sites_with_chosen": sum(1 for p in pools if p["chosen_idx"] is not None),
            "sites_cm_pick_ne_fs_pick": diffpick,
            "menu_cost_s_cm": cost_cm / 1000, "menu_cost_s_fs_sim": cost_fs / 1000,
            "labels": dict(Counter(x["outcome"] for p in pools for x in p["candidates"])),
        }
        c["ranking_top1_pct"] = {kk: 100 * statistics.mean(v) for kk, v in sorted(rk.items())}
        c["ranking_n"] = {kk: len(v) for kk, v in sorted(rk.items()) if kk.endswith(":random")}
        # released-style (first-success) groups from the fs run
        groups = defaultdict(list)
        for key in items:
            rep, *_ = file_result("fs", *key)
            for pr in (rep or {}).get("training_pairs", []):
                if pr.get("type") in ("tactic_replacement", "rejected_attempt"):
                    groups[pr["attempt_id"]].append(pr)
        g1 = defaultdict(list)
        for rows in groups.values():
            acc = [x for x in rows if x.get("outcome") == "accepted"]
            if acc and len(rows) >= 2:
                pc = [(x.get("rank_in_attempt", 1) if x.get("outcome") != "accepted" else 10**6, x["replacement"]) for x in rows]
                for kk, v in rank_rules(pc, acc[0]["replacement"], None).items():
                    g1[kk].append(v)
        c["ranking_v1_groups_top1_pct"] = {kk: 100 * statistics.mean(v) for kk, v in g1.items()}
        c["ranking_v1_groups_n"] = len(g1.get("random", []))
        res[cname] = c
        print(cname, {m: (v["saved_A"], round(v["pct_A"] or 0, 3)) for m, v in c["modes"].items()}, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "final_metrics.json").write_text(json.dumps(res, indent=1))
    tables(res)


def f(x, d=2):
    return "n/a" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))


def tables(res):
    L = []
    L.append("### T1. Whole-corpus reduction. Counter A (Lean-aware, comment-skipping) is primary; appL is secondary\n")
    L.append("| corpus | files | A tokens | FS saved A (%) | CM saved A (%) | CM+timeout-all saved A (%) | FS appL % | CM appL % | files w/o report FS/CM |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for cn, c in res.items():
        m = c["modes"]
        t = m.get("cmt")
        L.append(f"| {cn} | {c['n_files']} | {c['tokens_A_total']} | {m['fs']['saved_A']} ({f(m['fs']['pct_A'],3)}) | {m['cm']['saved_A']} ({f(m['cm']['pct_A'],3)}) | "
                 f"{(str(t['saved_A'])+' ('+f(t['pct_A'],3)+')') if t else 'not run'} | {f(m['fs']['pct_appL'],3)} | {f(m['cm']['pct_appL'],3)} | "
                 f"{len(m['fs']['files_without_report'])}/{len(m['cm']['files_without_report'])} |")
    L.append("\n### T2. Accepted edits and same-site tactic changes (FS vs CM, after whole-file verification)\n")
    L.append("| corpus | accepted tactic FS | CM | accepted all FS | CM | same site same tactic | same site different tactic (CM shorter in chars) | A-token delta at those sites | byte delta | only FS | only CM | top transitions |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for cn, c in res.items():
        m, s = c["modes"], c["sites_fs_vs_cm"]
        tr = "; ".join(f"{a} ×{b}" for a, b in list(s["transitions"].items())[:4])
        L.append(f"| {cn} | {m['fs']['accepted_tactic']} | {m['cm']['accepted_tactic']} | {m['fs']['accepted_all']} | {m['cm']['accepted_all']} | {s['same_tactic']} | {s['different_tactic']} ({s['different_cm_shorter_chars']}) | {s['different_A_token_delta']} | {s['different_byte_delta']} | {s['only_fs']} | {s['only_cm']} | {tr} |")
    L.append("\n### T3. Runtime and cost\n")
    L.append("| corpus | wall mean FS / CM (s) | wall median FS / CM | wall total FS / CM (s) | files hitting fold budget FS / CM | menu search time in CM run: complete / first-success simulated (s) | ratio |")
    L.append("|---|---|---|---|---|---|---|")
    for cn, c in res.items():
        m, p = c["modes"], c["pools_cm"]
        r = p["menu_cost_s_cm"] / p["menu_cost_s_fs_sim"] if p["menu_cost_s_fs_sim"] else None
        L.append(f"| {cn} | {f(m['fs']['wall_mean'],1)} / {f(m['cm']['wall_mean'],1)} | {f(m['fs']['wall_median'],1)} / {f(m['cm']['wall_median'],1)} | {f(m['fs']['wall_total'],0)} / {f(m['cm']['wall_total'],0)} | {m['fs']['files_fold_budget_hit']} / {m['cm']['files_fold_budget_hit']} | {f(p['menu_cost_s_cm'],1)} / {f(p['menu_cost_s_fs_sim'],1)} | {f(r)} |")
    L.append("\n### T4. Candidate pools (CM run, detection-time sites)\n")
    L.append("| corpus | sites | sites with ≥1 valid+shorter | mean valid / site (given ≥1) | frac ≥2 valid (given ≥1) | sites with chosen edit | chosen ≠ first-success pick | label counts |")
    L.append("|---|---|---|---|---|---|---|---|")
    for cn, c in res.items():
        p = c["pools_cm"]
        lab = ", ".join(f"{a} {b}" for a, b in sorted(p["labels"].items()))
        L.append(f"| {cn} | {p['sites']} | {p['sites_ge1_valid']} | {f(p['mean_valid_given_ge1'])} | {f(p['frac_ge2_valid_given_ge1'],3)} | {p['sites_with_chosen']} | {p['sites_cm_pick_ne_fs_pick']} | {lab} |")
    L.append("\n### T5. Ranking diagnostic: top-1 accuracy (%) of simple rules at recovering the chosen candidate (ties give expected accuracy)\n")
    L.append("| corpus | pool | n | earliest in menu | latest in menu | shortest string | random |")
    L.append("|---|---|---|---|---|---|---|")
    for cn, c in res.items():
        g = c["ranking_v1_groups_top1_pct"]
        if g:
            L.append(f"| {cn} | **v1 released-style group** (winner + earlier failures, ≥2 rows) | {c['ranking_v1_groups_n']} | {f(g['earliest_menu'],1)} | **{f(g['latest_menu'],1)}** | {f(g['shortest_string'],1)} | {f(g['random'],1)} |")
        r = c["ranking_top1_pct"]
        for pool, desc in [("all_tried", "CM: all tried candidates"), ("valid_shorter", "CM: valid+shorter only"),
                           ("selectable", "CM: selectable (valid, shorter, gate)"), ("selectable_ge2", "CM: selectable, ≥2 options")]:
            if f"{pool}:random" in r:
                L.append(f"| {cn} | {desc} | {c['ranking_n'][pool+':random']} | {f(r[pool+':earliest_menu'],1)} | {f(r[pool+':latest_menu'],1)} | {f(r[pool+':shortest_string'],1)} | {f(r[pool+':random'],1)} |")
    (OUT / "final_tables.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
