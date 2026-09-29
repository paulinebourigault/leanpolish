#!/usr/bin/env python3
"""Metrics for candidate selection on held-out COMPLETE-menu pools (+ menu-order rule on
the biased first-success ranking groups, --old-groups-dir, for contrast).  CPU only; model scores are read
from score_models.py outputs.

Per corpus and pooled:
  top1_best     expected top-1 accuracy of picking a best candidate (shortest
                acceptable = valid & shorter & quality gate), random tie-break,
                over sites with >=1 acceptable candidate
  top1_best_2p  same, restricted to sites with >=2 acceptable candidates
  top1_valid    P(picked candidate is valid) over the same sites
  savings_frac  sum(expected savings of pick) / sum(oracle savings); a pick that is
                not acceptable saves 0 (the original is kept)
  auroc_valid   pooled validity AUROC over all run candidates of all sites
  auroc_within  mean per-site validity AUROC over sites with mixed labels
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import MENU, annotate, load_sites, site_key  # noqa: E402

try:
    from sklearn.metrics import roc_auc_score
except ImportError:  # pragma: no cover
    roc_auc_score = None
roc_auc_score = None  # exact rank implementation everywhere (same value as sklearn)


def auroc(y, s):
    if len(set(y)) < 2:
        return None
    if roc_auc_score is not None:
        return float(roc_auc_score(y, s))
    # Mann-Whitney U with average ranks for ties, O(n log n)
    order = sorted(range(len(s)), key=lambda i: s[i])
    ranks = [0.0] * len(s)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and s[order[j + 1]] == s[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    npos = sum(1 for a in y if a); nneg = len(y) - npos
    rpos = sum(r for r, a in zip(ranks, y) if a)
    return (rpos - npos * (npos + 1) / 2) / (npos * nneg)


def pick_expect(cands, scores, fn):
    """Expected value of fn(candidate) under argmax with uniform tie-break."""
    m = max(scores)
    top = [c for c, s in zip(cands, scores) if s == m]
    return sum(fn(c) for c in top) / len(top)


def block(sites, sel, val):
    """sel/val: fn(site, cand) -> score for selection / validity ranking."""
    t1, t1b2, t1v, sv, orc = [], [], [], 0.0, 0.0
    ys, ss, within = [], [], []
    for s in sites:
        cands = s["_cands"]
        if not cands:
            continue
        vsc = [val(s, c) for c in cands]
        y = [int(c["is_valid"]) for c in cands]
        ys += y; ss += vsc
        a = auroc(y, vsc)
        if a is not None:
            within.append(a)
        if s["has_best"]:
            sc = [sel(s, c) for c in cands]
            b = pick_expect(cands, sc, lambda c: float(c["is_best"]))
            t1.append(b)
            if s["n_acceptable"] >= 2:
                t1b2.append(b)
            t1v.append(pick_expect(cands, sc, lambda c: float(c["is_valid"])))
            sv += pick_expect(cands, sc, lambda c: c["savings"])
            orc += s["oracle_savings"]
    avg = lambda x: (sum(x) / len(x)) if x else None  # noqa: E731
    return {"sites": len(sites), "sites_with_best": len(t1), "sites_2p_acceptable": len(t1b2),
            "top1_best": avg(t1), "top1_best_2p": avg(t1b2), "top1_valid": avg(t1v),
            "savings_frac": (sv / orc) if orc else None, "savings_chars": sv, "oracle_chars": orc,
            "auroc_valid": auroc(ys, ss), "auroc_within": avg(within), "within_sites": len(within)}


def random_block(sites):
    t1, t1b2, t1v, sv, orc = [], [], [], 0.0, 0.0
    for s in sites:
        c = s["_cands"]
        if not c or not s["has_best"]:
            continue
        n = len(c)
        b = sum(x["is_best"] for x in c) / n
        t1.append(b)
        if s["n_acceptable"] >= 2:
            t1b2.append(b)
        t1v.append(sum(x["is_valid"] for x in c) / n)
        sv += sum(x["savings"] for x in c) / n
        orc += s["oracle_savings"]
    avg = lambda x: (sum(x) / len(x)) if x else None  # noqa: E731
    return {"sites": len(sites), "sites_with_best": len(t1), "top1_best": avg(t1),
            "top1_best_2p": avg(t1b2), "top1_valid": avg(t1v),
            "savings_frac": (sv / orc) if orc else None, "auroc_valid": 0.5, "auroc_within": 0.5}


def pool_stats(sites):
    run = [s for s in sites if s["_cands"]]
    wv = [s for s in run if s["n_valid"] >= 1]
    wb = [s for s in run if s["has_best"]]
    n = len(run)
    v1_diff = v1_subopt = v1_lost = 0
    v1_sav = 0.0
    orc = sum(s["oracle_savings"] for s in wb)
    for s in wb:
        byidx = {c["menu_idx"]: c for c in s["_cands"]}
        v1 = byidx.get(s.get("v1_pick_idx"))
        if v1 is None or not v1["is_best"]:
            v1_diff += 1
        if v1 is not None and v1["is_acceptable"] and not v1["is_best"]:
            v1_subopt += 1
        if v1 is None or not v1["is_acceptable"]:
            v1_lost += 1
        if v1 is not None and v1["is_acceptable"]:
            v1_sav += v1["savings"]
    mean = lambda x: (sum(x) / len(x)) if x else None  # noqa: E731
    per_tac_valid = defaultdict(lambda: [0, 0])
    per_tac_best = defaultdict(int)
    for s in run:
        for c in s["_cands"]:
            per_tac_valid[c["menu_name"]][0] += c["is_valid"]
            per_tac_valid[c["menu_name"]][1] += 1
            per_tac_best[c["menu_name"]] += c["is_best"]
    return {
        "sites": n, "files": len({s["file"] for s in run}),
        "mean_run_candidates_per_site": mean([len(s["_cands"]) for s in run]),
        "mean_valid_per_site": mean([s["n_valid"] for s in run]),
        "mean_valid_per_site_given_ge1": mean([s["n_valid"] for s in wv]),
        "pct_sites_ge1_valid": 100 * len(wv) / n if n else None,
        "pct_sites_ge2_valid": 100 * sum(s["n_valid"] >= 2 for s in run) / n if n else None,
        "pct_ge2_valid_given_ge1": 100 * sum(s["n_valid"] >= 2 for s in wv) / len(wv) if wv else None,
        "sites_ge1_acceptable": len(wb),
        "mean_acceptable_given_ge1": mean([s["n_acceptable"] for s in wb]),
        "pct_ge2_acceptable_given_ge1": 100 * sum(s["n_acceptable"] >= 2 for s in wb) / len(wb) if wb else None,
        "pct_first_success_not_shortest": 100 * v1_diff / len(wb) if wb else None,
        "pct_first_success_acceptable_but_longer": 100 * v1_subopt / len(wb) if wb else None,
        "pct_first_success_no_edit_but_acceptable_exists": 100 * v1_lost / len(wb) if wb else None,
        "first_success_savings_frac_of_oracle": v1_sav / orc if orc else None,
        "per_tactic_valid_rate": {k: v[0] / v[1] for k, v in per_tac_valid.items()},
        "per_tactic_best_count": dict(per_tac_best),
    }


def menu_idx_of(raw: str) -> int:
    t = raw.strip()
    if t.startswith("by "):
        t = t[3:].strip()
    if t in MENU:
        return MENU.index(t)
    if t.startswith("simp"):
        return MENU.index("simp?")
    if t.startswith("exact") or t.startswith("apply"):
        return len(MENU)  # exact? fallback runs after the whole menu
    return -1


def old_groups_order_rule(old_dir: Path):
    out = {}
    all_first, all_last, n_unk = [], [], 0
    for fn in sorted(old_dir.glob("eval_groups_*.jsonl")):
        corpus = fn.stem.replace("eval_groups_", "")
        f_, l_ = [], []
        for line in fn.open():
            g = json.loads(line)
            idx = [menu_idx_of(c["raw"]) for c in g["candidates"]]
            n_unk += sum(i < 0 for i in idx)
            flags = [c["is_accepted"] for c in g["candidates"]]
            for sign, acc in ((-1, f_), (1, l_)):
                sc = [sign * i for i in idx]
                m = max(sc)
                top = [fl for fl, s in zip(flags, sc) if s == m]
                acc.append(sum(top) / len(top))
        out[corpus] = {"groups": len(f_), "menu_first_top1": sum(f_) / len(f_),
                       "menu_last_top1": sum(l_) / len(l_)}
        all_first += f_; all_last += l_
    out["pooled"] = {"groups": len(all_first), "menu_first_top1": sum(all_first) / len(all_first),
                     "menu_last_top1": sum(all_last) / len(all_last), "unmapped_candidates": n_unk}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-pools", nargs="*", default=[], help="corpus=path.jsonl.gz")
    ap.add_argument("--train-pools", nargs="*", default=[])
    ap.add_argument("--scores", nargs="*", default=[])
    ap.add_argument("--old-groups-dir", type=Path, default=None,
                    help="dir with first-success ranking groups (eval_groups_*.jsonl) for the order-rule contrast")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    res = {}
    if args.old_groups_dir:
        res["old_first_success_groups_order_rule"] = old_groups_order_rule(args.old_groups_dir)

    # train-set statistics + per-tactic prior baseline
    tr = [annotate(s) for p in args.train_pools for s in load_sites(p)]
    if tr:
        res["pool_stats_train"] = pool_stats(tr)
    prior_best, prior_valid = defaultdict(float), defaultdict(float)
    cnt = defaultdict(int)
    for s in tr:
        for c in s["_cands"]:
            cnt[c["menu_name"]] += 1
            prior_best[c["menu_name"]] += c["is_best"]
            prior_valid[c["menu_name"]] += c["is_valid"]
    for k in cnt:
        prior_best[k] /= cnt[k]; prior_valid[k] /= cnt[k]

    scores = {}
    for p in args.scores:
        for line in open(p):
            d = json.loads(line)
            scores.setdefault(d.pop("key"), {}).update(d)
    score_names = sorted({k for v in scores.values() for k in v})

    corpora = {}
    for spec in args.eval_pools:
        name, path = spec.split("=", 1)
        sites = [annotate(s) for s in load_sites(path)]
        for s in sites:
            s.setdefault("corpus", name)
        corpora[name] = sites
    corpora_all = dict(corpora)
    if len(corpora) > 1:
        corpora_all["pooled"] = [s for v in corpora.values() for s in v]

    def sk(s, c, n):
        return scores.get(f"{site_key(s)}|{c['menu_idx']}", {}).get(n, float("-inf"))

    methods = {
        "menu_first": (lambda s, c: -c["menu_idx"],) * 2,
        "menu_last": (lambda s, c: c["menu_idx"],) * 2,
        "shortest": (lambda s, c: -len(c["final_tac"]),) * 2,
        # reference, NOT a ranker: uses the verifier's labels (what first-success LeanPolish does)
        "ref:first_success(verifier)": (
            lambda s, c: (1000 if c.get("outcome") in ("chosen", "valid_not_chosen", "rejected_quality") else 0) - c["menu_idx"],
            lambda s, c: float(c["is_valid"])),
        "tactic_prior(train)": (lambda s, c: prior_best.get(c["menu_name"], 0.0),
                                lambda s, c: prior_valid.get(c["menu_name"], 0.0)),
    }
    for n in score_names:
        if not (n.endswith("_best") or n.endswith("_valid")):
            methods[n] = (lambda s, c, n=n: sk(s, c, n),) * 2
    for base in sorted({n.rsplit("_", 1)[0] for n in score_names if n.endswith("_best")}):
        methods[base] = (lambda s, c, b=base: sk(s, c, b + "_best"),
                         lambda s, c, b=base: sk(s, c, b + "_valid"))
        methods[base + "[valid-head,shortest-if-p>0.5]"] = (
            lambda s, c, b=base: (1e6 if sk(s, c, b + "_valid") > 0 else 0) - len(c["final_tac"]),
            lambda s, c, b=base: sk(s, c, b + "_valid"))
    res["pool_stats_eval"] = {k: pool_stats(v) for k, v in corpora_all.items()}
    res["selection"] = {}
    for k, sites in corpora_all.items():
        res["selection"][k] = {"random": random_block(sites)}
        for m, (sel, val) in methods.items():
            res["selection"][k][m] = block(sites, sel, val)
        res["selection"][k]["oracle"] = block(sites, lambda s, c: float(c["is_best"]),
                                              lambda s, c: float(c["is_valid"]))
    missing = sum(1 for v in corpora_all.get("pooled", next(iter(corpora_all.values()), [])) for c in v["_cands"]
                  if scores and f"{site_key(v)}|{c['menu_idx']}" not in scores) if corpora_all else 0
    res["missing_model_scores"] = missing
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2, default=str))
    # compact print
    for k, d in res.get("selection", {}).items():
        print(f"== {k}")
        for m, v in d.items():
            f = lambda x: "-" if x is None else f"{100*x:.1f}"  # noqa: E731
            print(f"  {m:45s} top1 {f(v.get('top1_best'))} top1_2p {f(v.get('top1_best_2p'))} "
                  f"valid@1 {f(v.get('top1_valid'))} sav {f(v.get('savings_frac'))} "
                  f"AUROC {f(v.get('auroc_valid'))} within {f(v.get('auroc_within'))}")
    if "old_first_success_groups_order_rule" in res:
        print(json.dumps(res["old_first_success_groups_order_rule"], indent=1))


if __name__ == "__main__":
    main()
