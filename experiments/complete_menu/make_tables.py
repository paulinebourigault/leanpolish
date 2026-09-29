#!/usr/bin/env python3
"""Print markdown tables (reduction, accepted edits, runtime, menu-search cost, pool statistics,
ranking diagnostic) from results/metrics.json, as written by analyze_complete_menu.py.

usage: make_tables.py [metrics.json]    (prints to stdout)
"""
import json
import sys
from pathlib import Path

_src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "results" / "metrics.json"
m = {k: v for k, v in json.loads(_src.read_text()).items() if not k.startswith("_")}
NAMES = {"putnam_verified": "PutnamBench-verified", "axiom": "Putnam 2025 AxiomProver",
         "minif2f": "miniF2F-verified", "axiom_r2": "Putnam 2025 AxiomProver (rerun)"}


def f(x, d=2):
    return "n/a" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))


print("### Reduction (whole corpus, appL tokens; files not shortened = 0)\n")
print("| corpus | files run / in dir | orig tokens | first-success saved (%) | complete-menu saved (%) | Δ tokens | bytes FS % | bytes CM % |")
print("|---|---|---|---|---|---|---|---|")
for c, x in m.items():
    b, k = x["base"], x["cm"]
    print(f"| {NAMES.get(c,c)} | {x['n_files_done_both']} / {x['n_files_corpus']} | {x['tokens_original_total']} | "
          f"{b['tokens_saved']} ({f(b['token_reduction_pct'],3)}) | {k['tokens_saved']} ({f(k['token_reduction_pct'],3)}) | "
          f"{k['tokens_saved']-b['tokens_saved']:+d} | {f(b['byte_reduction_pct'],3)} | {f(k['byte_reduction_pct'],3)} |")
print("\n### Accepted edits and site-level differences\n")
print("| corpus | tactic repl. FS | tactic repl. CM | all accepted FS | all accepted CM | same site, same tactic | same site, CM different (shorter) | only FS | only CM | pool sites where CM pick ≠ FS pick |")
print("|---|---|---|---|---|---|---|---|---|---|")
for c, x in m.items():
    b, k, s, p = x["base"], x["cm"], x["site_comparison"], x["cm_pools"]
    print(f"| {NAMES.get(c,c)} | {b['accepted_tactic_replacements']} | {k['accepted_tactic_replacements']} | {b['accepted_edits_all']} | {k['accepted_edits_all']} | "
          f"{s['accepted_in_both_same_tactic']} | {s['accepted_in_both_different_tactic']} ({s['different_tactic_cm_shorter']}) | {s['only_base']} | {s['only_cm']} | {p['n_sites_cm_pick_differs_from_v1_pick']} / {p['n_sites_with_chosen']} |")
print("\n### Runtime per file (wall s, chunk-size 1, concurrent runs on a shared machine)\n")
print("| corpus | FS mean | CM mean | FS median | CM median | FS total | CM total | CM/FS total |")
print("|---|---|---|---|---|---|---|---|")
for c, x in m.items():
    b, k = x["base"], x["cm"]
    r = k["wall_s_total"] / b["wall_s_total"] if b["wall_s_total"] else None
    print(f"| {NAMES.get(c,c)} | {f(b['wall_s_mean_per_file'],1)} | {f(k['wall_s_mean_per_file'],1)} | {f(b['wall_s_median_per_file'],1)} | {f(k['wall_s_median_per_file'],1)} | {f(b['wall_s_total'],0)} | {f(k['wall_s_total'],0)} | {f(r,3)} |")
print("\n### Menu-search cost measured inside the complete-menu run (sum of per-attempt wall ms)\n")
print("| corpus | complete menu (s) | first-success, simulated on the same attempts (s) | ratio | extra s per file |")
print("|---|---|---|---|---|")
for c, x in m.items():
    k = x.get("menu_search_cost_ms")
    if k:
        print(f"| {NAMES.get(c,c)} | {k['complete_menu']/1000:.1f} | {k['first_success_simulated']/1000:.1f} | {f(k['ratio'])} | {f(k['extra_s_per_file'],1)} |")
print("\n### Candidate pools (complete-menu, detection-time sites)\n")
print("| corpus | sites | mean tried/site | sites ≥1 valid | mean valid/site (given ≥1) | frac ≥2 valid (given ≥1) | sites with a chosen edit | outcome labels |")
print("|---|---|---|---|---|---|---|---|")
for c, x in m.items():
    p = x["cm_pools"]
    labs = ", ".join(f"{a}:{b}" for a, b in sorted(p["outcome_label_counts"].items()))
    print(f"| {NAMES.get(c,c)} | {p['n_sites_menu_tried']} | {f(p['mean_candidates_tried_per_site'],1)} | {p['n_sites_with_>=1_valid']} | {f(p['mean_valid_per_site_given_>=1'])} | {f(p['frac_sites_>=2_valid_given_>=1'],3)} | {p['n_sites_with_chosen']} | {labs} |")
print("\n### Ranking diagnostic: top-1 accuracy (%) against the chosen candidate\n")
print("| corpus | pool | n | earliest-in-menu | latest-in-menu | shortest string | random |")
print("|---|---|---|---|---|---|---|")
for c, x in m.items():
    v1 = x["ranking_v1_pools_top1_pct"]
    if v1:
        print(f"| {NAMES.get(c,c)} | v1 released-style group (winner + failures tried before it; n≥2) | {x['ranking_v1_pools_n_groups_ge2']} | {f(v1['earliest_menu'],1)} | {f(v1['latest_menu'],1)} | {f(v1['shortest_string'],1)} | {f(v1['random'],1)} |")
    r, n = x["ranking_cm_pools_top1_pct"], x["ranking_cm_pools_n"]
    for pool, desc in [("all_siblings", "CM: all tried candidates"), ("valid_only", "CM: valid and shorter only"),
                       ("selectable", "CM: selectable (valid, shorter, passes gate)"),
                       ("selectable_ge2", "CM: selectable, sites with ≥2")]:
        if pool + ":random" in r:
            print(f"| {NAMES.get(c,c)} | {desc} | {n[pool+':random']} | {f(r[pool+':earliest_menu'],1)} | {f(r[pool+':latest_menu'],1)} | {f(r[pool+':shortest_string'],1)} | {f(r[pool+':random'],1)} |")
