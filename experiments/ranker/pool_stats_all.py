#!/usr/bin/env python3
"""Pool statistics per source (all complete-menu pools): name=path pairs -> json."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import annotate, load_sites, goal_hash
from eval_metrics import pool_stats
out = {}
for spec in sys.argv[2:]:
    name, path = spec.split("=", 1)
    sites = [annotate(s) for p in path.split(",") for s in load_sites(p)]
    st = pool_stats(sites)
    st["outcome_counts"] = {}
    for s in sites:
        for c in s["candidates"]:
            st["outcome_counts"][c["outcome"]] = st["outcome_counts"].get(c["outcome"], 0) + 1
    out[name] = st
Path(sys.argv[1]).write_text(json.dumps(out, indent=2))
keys = ["sites", "files", "mean_valid_per_site", "pct_sites_ge1_valid", "pct_sites_ge2_valid", "pct_ge2_valid_given_ge1",
        "sites_ge1_acceptable", "mean_acceptable_given_ge1", "pct_ge2_acceptable_given_ge1",
        "pct_first_success_not_shortest", "first_success_savings_frac_of_oracle"]
print("| source | " + " | ".join(keys) + " |")
for n, st in out.items():
    print(f"| {n} | " + " | ".join(f"{st[k]:.2f}" if isinstance(st[k], float) else str(st[k]) for k in keys) + " |")
