#!/usr/bin/env python3
"""File-clustered bootstrap 95% CIs for top-1 best accuracy (per method) and for
paired differences (rk_full - X), over sites with >=1 acceptable candidate.
Usage: bootstrap_ci.py out.json --scores ... --eval-pools name=path ...
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import annotate, load_sites, site_key  # noqa: E402
from eval_metrics import pick_expect  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("--scores", nargs="+")
ap.add_argument("--eval-pools", nargs="+")
ap.add_argument("--methods", nargs="+", default=["rk_full_best", "rk_nogoal_best", "lp_qwen32b_sum",
                                                   "lp_dsp7b_sum", "lp_qwen7b_sum"])
ap.add_argument("--B", type=int, default=2000)
args = ap.parse_args()
scores = {}
for p in args.scores:
    for line in open(p):
        d = json.loads(line)
        scores.setdefault(d.pop("key"), {}).update(d)
rng = random.Random(0)
res = {}
groups = {}
for spec in args.eval_pools:
    n, p = spec.split("=", 1)
    groups[n] = [annotate(s) for s in load_sites(p)]
groups["pooled"] = [s for v in list(groups.values()) for s in v]
for name, sites in groups.items():
    per_file = defaultdict(lambda: defaultdict(list))
    for s in sites:
        if not s["has_best"]:
            continue
        for m in args.methods:
            sc = [scores.get(f"{site_key(s)}|{c['menu_idx']}", {}).get(m) for c in s["_cands"]]
            if any(x is None for x in sc):
                continue
            per_file[f"{s.get('corpus')}|{s['file']}"][m].append(pick_expect(s["_cands"], sc, lambda c: float(c["is_best"])))
    files = list(per_file)
    out = {}
    for m in args.methods:
        def stat(fs, m=m):
            v = [x for f in fs for x in per_file[f][m]]
            return sum(v) / len(v) if v else None
        point = stat(files)
        if point is None:
            continue
        bs = sorted(x for x in (stat([rng.choice(files) for _ in files]) for _ in range(args.B)) if x is not None)
        out[m] = {"top1": point, "ci95": [bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs)) - 1]]}
        if m != "rk_full_best":
            def dstat(fs, m=m):
                a = [x for f in fs for x in per_file[f]["rk_full_best"]]
                b = [x for f in fs for x in per_file[f][m]]
                return (sum(a) / len(a) - sum(b) / len(b)) if a and b and len(a) == len(b) else None
            ds = sorted(x for x in (dstat([rng.choice(files) for _ in files]) for _ in range(args.B)) if x is not None)
            if ds:
                out[f"rk_full_minus_{m}"] = {"diff": dstat(files),
                                             "ci95": [ds[int(0.025 * len(ds))], ds[int(0.975 * len(ds)) - 1]]}
    res[name] = {"files": len(files), **out}
Path(args.out).write_text(json.dumps(res, indent=2))
for k, v in res.items():
    print(k, json.dumps({a: b for a, b in v.items()}, default=lambda x: round(x, 3)))
