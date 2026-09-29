#!/usr/bin/env python3
"""Analyse first-success (base) vs complete-menu (cm) LeanPolish runs.

Paper: Sec. 3 "Complete-menu search" (pool statistics, runtime ratio).

Layout expected under $DATA_DIR (default ./data; see the complete_menu_runs archive):
  data/runs/{base,cm}/{corpus}/**/<stem>.lean, <stem>_shortened.lean, <stem>_report.json
  data/raw/{base,cm}/{corpus}/*.log   (raw Lean stdout; [CHUNK_WALL_S], [MENU_POOL])
  data/corpora/{corpus}/**/*.lean     (pristine originals)

Outputs: $OUT_DIR/metrics.json (default ./results); $DATA_DIR/pools/<corpus>_pools.jsonl and
$DATA_DIR/candidate_pools.jsonl (complete-menu pools, read by final_metrics.py); printed summary.
Environment: DATA_DIR, OUT_DIR, LEANPOLISH_ROOT (repository root; default two levels up).
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("LEANPOLISH_ROOT", HERE.parents[1]))
sys.path.insert(0, str(REPO / "leanpolish"))  # retokenize_appendixL
from retokenize_appendixL import count_appL  # noqa: E402

DATA = Path(os.environ.get("DATA_DIR", HERE / "data"))
OUT = Path(os.environ.get("OUT_DIR", HERE / "results"))
CORPORA = ["putnam_verified", "axiom", "axiom_r2", "minif2f"] + [f"mathlib_b{i}" for i in range(1, 7)]
CM_ONLY = ["goedel_extra"]
MODES = ["base", "cm"]
SEL_LABELS = {"chosen", "valid_not_chosen"}


def originals(corpus):
    root = DATA / "corpora" / corpus
    return sorted(p for p in root.rglob("*.lean")
                  if not p.name.endswith("_shortened.lean"))


def rel(corpus, p):
    return str(p.relative_to(DATA / "corpora" / corpus))


def load_mode(mode, corpus):
    """Per-file record: report (or None), shortened text (post-verified) or None, wall."""
    out = {}
    run = DATA / "runs" / mode / corpus
    raw = DATA / "raw" / mode / corpus
    walls, pools = {}, []
    if raw.is_dir():
        for lg in raw.glob("*.log"):
            files, wall = None, None
            for line in lg.read_text(errors="replace").splitlines():
                if line.startswith("[CHUNK_FILES]"):
                    files = json.loads(line[len("[CHUNK_FILES]"):])
                elif line.startswith("[CHUNK_WALL_S]"):
                    wall = float(line.split()[1])
                elif line.startswith("[MENU_POOL]"):
                    try:
                        pools.append(json.loads(line[len("[MENU_POOL]"):].strip()))
                    except json.JSONDecodeError:
                        pass
            if files and len(files) == 1 and wall is not None:
                # files[0] is relative to the lake root: runs/<mode>/<corpus>/<rel>
                r = files[0].split(f"runs/{mode}/{corpus}/", 1)[-1]
                walls[r] = wall
    for p in originals(corpus):
        r = rel(corpus, p)
        rp = run / Path(r).with_name(Path(r).stem + "_report.json")
        sp = run / Path(r).with_name(Path(r).stem + "_shortened.lean")
        rep = json.loads(rp.read_text()) if rp.exists() else None
        out[r] = {
            "report": rep,
            "short": sp.read_text() if sp.exists() else None,
            "wall": walls.get(r),
        }
    return out, pools


def pool_key(pool, mode, corpus):
    f = pool["file"].split(f"runs/{mode}/{corpus}/", 1)[-1]
    return (f, pool["start_byte"], pool["end_byte"])


def pair_file(pair, mode, corpus):
    return pair.get("file", "").split(f"runs/{mode}/{corpus}/", 1)[-1]


def rank_rules(pool_cands, oracle_tac, rng):
    """Top-1 of (earliest menu idx, latest menu idx, shortest string, random) vs oracle.
    pool_cands: list of (menu_order, text). Ties -> expected accuracy (1/k)."""
    def acc_of(scores, better):
        best = better(s for s, _ in scores)
        tied = [t for s, t in scores if s == best]
        return sum(1 for t in tied if t == oracle_tac) / len(tied)
    earliest = acc_of([(o, t) for o, t in pool_cands], min)
    latest = acc_of([(o, t) for o, t in pool_cands], max)
    shortest = acc_of([(len(t), t) for o, t in pool_cands], min)
    rand = sum(1 for _, t in pool_cands if t == oracle_tac) / len(pool_cands)
    return {"earliest_menu": earliest, "latest_menu": latest,
            "shortest_string": shortest, "random": rand}


def mean(xs):
    return statistics.mean(xs) if xs else None


def main():
    rng = random.Random(0)
    metrics = {}
    pools_out = []
    for corpus in CORPORA:
        if not (DATA / "corpora" / corpus).is_dir() or not all((DATA / "raw" / m / corpus).is_dir() for m in MODES):
            continue
        origs = {rel(corpus, p): p.read_text() for p in originals(corpus)}
        tok_orig = {r: count_appL(t) for r, t in origs.items()}
        per_mode, pools_by_mode = {}, {}
        cm_ = {}
        for mode in MODES:
            per_mode[mode], pools_by_mode[mode] = load_mode(mode, corpus)
        # restrict to files that have a report in BOTH modes (same denominator)
        # attempted = the run finished for this file (raw log written) or a report exists;
        # attempted files with no report (optimizer error / no output) count as 0 saved.
        done = [r for r in origs if all(per_mode[m][r]["report"] is not None or per_mode[m][r]["wall"] is not None for m in MODES)]
        for m in MODES:
            cm_.setdefault("files_without_report", {})[m] = sorted(r for r in done if per_mode[m][r]["report"] is None)
        cm_["n_files_corpus"] = len(origs); cm_["n_files_done_both"] = len(done)
        denom = sum(tok_orig[r] for r in done)
        cm_["tokens_original_total"] = denom
        bdenom = sum(len(origs[r].encode()) for r in done)
        cm_["bytes_original_total"] = bdenom
        acc_sites = {}
        for mode in MODES:
            saved, n_short, n_tac, n_acc, n_dead, walls, n_err = 0, 0, 0, 0, 0, [], 0
            bsaved = 0
            sites = {}
            for r in done:
                rec = per_mode[mode][r]
                if rec["report"] is None:
                    if rec["wall"] is not None:
                        walls.append(rec["wall"])
                    continue
                if rec["short"] is not None and rec["report"].get("verified"):
                    bsaved += len(origs[r].encode()) - len(rec["short"].encode())
                    s = tok_orig[r] - count_appL(rec["short"])
                    saved += max(s, 0) if s > 0 else 0
                    n_short += 1 if s > 0 else 0
                if rec["report"].get("error") or not rec["report"].get("verified", True):
                    pass
                for pr in rec["report"].get("training_pairs", []):
                    if pr.get("outcome") != "accepted":
                        continue
                    n_acc += 1
                    if pr.get("type") == "tactic_replacement":
                        n_tac += 1
                        sites[(r, pr["start_byte"], pr["end_byte"])] = pr["replacement"]
                    elif pr.get("type") == "dead_code_removal":
                        n_dead += 1
                if rec["wall"] is not None:
                    walls.append(rec["wall"])
            acc_sites[mode] = sites
            cm_[mode] = {
                "tokens_saved": saved,
                "token_reduction_pct": 100.0 * saved / denom if denom else None,
                "files_shortened": n_short,
                "bytes_saved": bsaved,
                "byte_reduction_pct": 100.0 * bsaved / bdenom if bdenom else None,
                "accepted_edits_all": n_acc,
                "accepted_tactic_replacements": n_tac,
                "accepted_dead_code": n_dead,
                "wall_s_mean_per_file": mean(walls),
                "wall_s_median_per_file": statistics.median(walls) if walls else None,
                "wall_s_total": sum(walls),
                "n_wall": len(walls),
                "wall_s_by_file": {r: per_mode[mode][r]["wall"] for r in done},
            }
        b, c = acc_sites["base"], acc_sites["cm"]
        same = [k for k in b if k in c and b[k] == c[k]]
        diff = [k for k in b if k in c and b[k] != c[k]]
        cm_["site_comparison"] = {
            "accepted_in_both_same_tactic": len(same),
            "accepted_in_both_different_tactic": len(diff),
            "different_tactic_cm_shorter": sum(1 for k in diff if len(c[k]) < len(b[k])),
            "different_tactic_appL_token_delta_sum": sum(count_appL(b[k]) - count_appL(c[k]) for k in diff),
            "different_tactic_cm_fewer_appL_tokens": sum(1 for k in diff if count_appL(c[k]) < count_appL(b[k])),
            "different_tactic_byte_delta_sum": sum(len(b[k].encode()) - len(c[k].encode()) for k in diff),
            "different_tactic_pairs_count": dict(sorted(__import__("collections").Counter(
                f"{b[k]} -> {c[k]}" if len(b[k]) < 40 and len(c[k]) < 40 else "long" for k in diff).items(),
                key=lambda kv: -kv[1])),
            "only_base": len([k for k in b if k not in c]),
            "only_cm": len([k for k in c if k not in b]),
            "examples_different": [
                {"file": k[0], "start": k[1], "base": b[k], "cm": c[k]} for k in diff[:25]],
        }
        # ── pools (cm) ──────────────────────────────────────────────────
        cmpools = pools_by_mode["cm"]
        n_valid, n_sel, n_tried = [], [], []
        diff_pick, v1_none_cm_some = 0, 0
        rank_cm = defaultdict(list)
        label_counts = defaultdict(int)
        for pool in cmpools:
            key = pool_key(pool, "cm", corpus)
            cands = [x for x in pool["candidates"] if not x["skipped"]]
            usable = [x for x in cands if x["valid"] and x["len"] < pool["orig_span"]]
            sel = [x for x in cands if x["outcome"] in SEL_LABELS]
            for x in pool["candidates"]:
                label_counts[x["outcome"]] += 1
            n_tried.append(len(cands))
            n_valid.append(len(usable))
            n_sel.append(len(sel))
            if pool["chosen_idx"] is not None:
                v1 = pool["v1_pick_idx"]
                if v1 is None or not pool["v1_pick_quality_ok"]:
                    v1_none_cm_some += 1
                elif v1 != pool["chosen_idx"]:
                    diff_pick += 1
                oracle = next(x["final_tac"] for x in cands if x["menu_idx"] == pool["chosen_idx"])
                # pool = chosen + all emitted siblings (what a released group would contain)
                pc = [(x["menu_idx"], x["final_tac"]) for x in cands]
                for k, v in rank_rules(pc, oracle, rng).items():
                    rank_cm["all_siblings:" + k].append(v)
                # valid-only pool (candidates that are kernel-valid and shorter)
                pv = [(x["menu_idx"], x["final_tac"]) for x in usable]
                for k, v in rank_rules(pv, oracle, rng).items():
                    rank_cm["valid_only:" + k].append(v)
                # selectable pool: valid, shorter AND quality-passing (chosen + valid_not_chosen)
                ps = [(x["menu_idx"], x["final_tac"]) for x in sel]
                for k, v in rank_rules(ps, oracle, rng).items():
                    rank_cm["selectable:" + k].append(v)
                if len(ps) >= 2:
                    for k, v in rank_rules(ps, oracle, rng).items():
                        rank_cm["selectable_ge2:" + k].append(v)
            ot = count_appL(pool["original"])
            pools_out.append({
                "corpus": corpus, "file": key[0],
                "start_byte": pool["start_byte"], "end_byte": pool["end_byte"],
                "kind": pool["kind"], "orig_span_bytes": pool["orig_span"],
                "goal_pretty": pool.get("goal_pretty", ""), "goal_state": pool.get("goal_state", ""),
                "original": pool["original"], "original_tokens_appL": ot,
                "chosen_idx": pool["chosen_idx"], "chosen_tac": pool["chosen_tac"],
                "v1_pick_idx": pool["v1_pick_idx"], "v1_pick_quality_ok": pool["v1_pick_quality_ok"],
                "accepted_after_verify": key in c,
                "cm_accepted_replacement": c.get(key),
                "base_accepted_replacement": b.get(key),
                "candidates": [dict(x, token_savings_appL=ot - count_appL(x["final_tac"]))
                               for x in pool["candidates"]],
            })
        # menu-search cost measured inside the cm run: complete = sum of all attempts;
        # first-success (simulated on the same attempts) = attempts up to and including the first-success pick
        cost_cm = sum(x["wall_ms"] for p in cmpools for x in p["candidates"])
        cost_fs = 0
        for p in cmpools:
            for x in p["candidates"]:
                cost_fs += x["wall_ms"]
                if p["v1_pick_idx"] is not None and x["menu_idx"] == p["v1_pick_idx"]:
                    break
        cm_["menu_search_cost_ms"] = {"complete_menu": cost_cm, "first_success_simulated": cost_fs,
                                      "ratio": cost_cm / cost_fs if cost_fs else None,
                                      "extra_s_per_file": (cost_cm - cost_fs) / 1000 / max(1, len(done))}
        sites_with_valid = [v for v in n_valid if v >= 1]
        cm_["cm_pools"] = {
            "n_sites_menu_tried": len(cmpools),
            "mean_candidates_tried_per_site": mean(n_tried),
            "n_sites_with_>=1_valid": len(sites_with_valid),
            "mean_valid_per_site_all": mean(n_valid),
            "mean_valid_per_site_given_>=1": mean(sites_with_valid),
            "frac_sites_>=2_valid_given_>=1": (sum(1 for v in sites_with_valid if v >= 2) / len(sites_with_valid)) if sites_with_valid else None,
            "n_sites_with_chosen": sum(1 for p in cmpools if p["chosen_idx"] is not None),
            "n_sites_cm_pick_differs_from_v1_pick": diff_pick,
            "n_sites_cm_edit_where_v1_no_edit": v1_none_cm_some,
            "outcome_label_counts": dict(label_counts),
        }
        cm_["ranking_cm_pools_top1_pct"] = {k: 100.0 * mean(v) for k, v in sorted(rank_cm.items())}
        cm_["ranking_cm_pools_n"] = {k: len(v) for k, v in sorted(rank_cm.items())}
        # ── released-style (first-success) groups from the base run: accepted + rejected rows by attempt_id
        groups = defaultdict(list)
        for r in done:
            for pr in (per_mode["base"][r]["report"] or {}).get("training_pairs", []):
                if pr.get("type") in ("tactic_replacement", "rejected_attempt"):
                    groups[pr["attempt_id"]].append(pr)
        rank_v1 = defaultdict(list)
        for gid, rows in groups.items():
            acc = [x for x in rows if x.get("outcome") == "accepted"]
            if not acc or len(rows) < 2:
                continue
            oracle = acc[0]["replacement"]
            # menu position = rank_in_attempt for rejected (tried in menu order), winner last
            pc = [(x.get("rank_in_attempt", 1) if x.get("outcome") != "accepted" else 10**6,
                   x["replacement"]) for x in rows]
            # lengths are compared as emitted (both texts use the same `by ` prefix policy)
            for k, v in rank_rules(pc, oracle, rng).items():
                rank_v1[k].append(v)
        cm_["ranking_v1_pools_top1_pct"] = {k: 100.0 * mean(v) for k, v in sorted(rank_v1.items())}
        cm_["ranking_v1_pools_n_groups_ge2"] = len(next(iter(rank_v1.values()), []))
        metrics[corpus] = cm_
    # cm-only corpora (training pools): export pools, no FS comparison
    for corpus in CM_ONLY:
        if not (DATA / "raw" / "cm" / corpus).is_dir():
            continue
        _, pools = load_mode("cm", corpus)
        accepted = {}
        for rp in (DATA / "runs" / "cm" / corpus).rglob("*_report.json"):
            try:
                rep = json.loads(rp.read_text())
            except Exception:
                continue
            for pr in rep.get("training_pairs", []):
                if pr.get("outcome") == "accepted" and pr.get("type") == "tactic_replacement":
                    accepted[(pair_file(pr, "cm", corpus), pr["start_byte"], pr["end_byte"])] = pr["replacement"]
        for pool in pools:
            key = pool_key(pool, "cm", corpus)
            ot = count_appL(pool["original"])
            pools_out.append({
                "corpus": corpus, "file": key[0],
                "start_byte": pool["start_byte"], "end_byte": pool["end_byte"],
                "kind": pool["kind"], "orig_span_bytes": pool["orig_span"],
                "goal_pretty": pool.get("goal_pretty", ""), "goal_state": pool.get("goal_state", ""),
                "original": pool["original"], "original_tokens_appL": ot,
                "chosen_idx": pool["chosen_idx"], "chosen_tac": pool["chosen_tac"],
                "v1_pick_idx": pool["v1_pick_idx"], "v1_pick_quality_ok": pool["v1_pick_quality_ok"],
                "accepted_after_verify": key in accepted,
                "cm_accepted_replacement": accepted.get(key), "base_accepted_replacement": None,
                "candidates": [dict(x, token_savings_appL=ot - count_appL(x["final_tac"]))
                               for x in pool["candidates"]],
            })
        metrics.setdefault("_cm_only_pools", {})[corpus] = {
            "n_sites": len(pools), "n_files_with_raw_log": len(list((DATA / "raw" / "cm" / corpus).glob("*.log"))),
            "n_sites_with_chosen": sum(1 for p in pools if p["chosen_idx"] is not None)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (DATA / "pools").mkdir(exist_ok=True)
    for corpus in CORPORA + CM_ONLY:
        rows = [p for p in pools_out if p["corpus"] == corpus]
        if not rows:
            continue
        with open(DATA / "pools" / f"{corpus}_pools.jsonl", "w") as fh:
            for p in rows:
                fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(DATA / "candidate_pools.jsonl", "w") as fh:
        for p in pools_out:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    for corpus, m in metrics.items():
        if corpus.startswith("_"):
            print(corpus, m); continue
        print(f"== {corpus}: files {m['n_files_done_both']}/{m['n_files_corpus']}, tokens {m['tokens_original_total']}")
        for mode in MODES:
            x = m[mode]
            print(f"  {mode}: bytes saved {x['bytes_saved']} ({x['byte_reduction_pct']}%) tokens saved {x['tokens_saved']} ({x['token_reduction_pct']}%), tac {x['accepted_tactic_replacements']}, all {x['accepted_edits_all']}, wall mean {x['wall_s_mean_per_file']}")
        print("  sites:", {k: v for k, v in m["site_comparison"].items() if k != "examples_different"})
        print("  pools:", m["cm_pools"])
        print("  rank cm:", m["ranking_cm_pools_top1_pct"])
        print("  rank v1:", m["ranking_v1_pools_top1_pct"])


if __name__ == "__main__":
    main()
