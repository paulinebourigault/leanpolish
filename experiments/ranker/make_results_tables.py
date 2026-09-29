#!/usr/bin/env python3
"""Render markdown tables from metrics.json (selection + pool stats)."""
import json
import sys

m = json.load(open(sys.argv[1]))
f = lambda x: "-" if x is None else f"{100*x:.1f}"  # noqa: E731
order = ["random", "menu_first", "menu_last", "shortest", "tactic_prior(train)",
         "lp_dsp7b", "lp_dsp7b_sum", "lp_qwen7b", "lp_qwen7b_sum", "lp_qwen32b", "lp_qwen32b_sum",
         "rk_nogoal", "rk_nogoal[valid-head,shortest-if-p>0.5]",
         "rk_full", "rk_full[valid-head,shortest-if-p>0.5]",
         "ref:first_success(verifier)", "oracle"]
for corpus, d in m["selection"].items():
    any_m = next(iter(d.values()))
    print(f"\n#### {corpus} ({any_m['sites']} sites; {any_m['sites_with_best']} with >=1 acceptable candidate)\n")
    print("| Method | Top-1 best | Top-1 best (>=2 acceptable) | Top-1 valid | Savings vs oracle | Validity AUROC (pooled) | Validity AUROC (within-site) |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for k in order + [k for k in d if k not in order]:
        if k in d:
            v = d[k]
            print(f"| {k} | {f(v.get('top1_best'))} | {f(v.get('top1_best_2p'))} | {f(v.get('top1_valid'))} "
                  f"| {f(v.get('savings_frac'))} | {f(v.get('auroc_valid'))} | {f(v.get('auroc_within'))} |")
print("\n#### Pool statistics\n")
keys = ["sites", "files", "mean_run_candidates_per_site", "mean_valid_per_site", "pct_sites_ge1_valid",
        "pct_sites_ge2_valid", "pct_ge2_valid_given_ge1", "sites_ge1_acceptable", "mean_acceptable_given_ge1",
        "pct_ge2_acceptable_given_ge1", "pct_first_success_not_shortest",
        "pct_first_success_no_edit_but_acceptable_exists", "first_success_savings_frac_of_oracle"]
stats = {}
for k, v in m.items():
    if k.startswith("pool_stats_train"):
        stats[k.replace("pool_stats_", "")] = v
for k, v in m.get("pool_stats_eval", {}).items():
    stats[k] = v
print("| stat | " + " | ".join(stats) + " |")
print("|---|" + "---:|" * len(stats))
for key in keys:
    row = []
    for v in stats.values():
        x = v.get(key)
        row.append("-" if x is None else (f"{x:.3f}" if isinstance(x, float) and x <= 1.5 and "frac" in key else
                                          f"{x:.2f}" if isinstance(x, float) else str(x)))
    print(f"| {key} | " + " | ".join(row) + " |")
