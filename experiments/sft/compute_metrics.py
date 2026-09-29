#!/usr/bin/env python3
"""Compute experiment metrics from candidates + screening + exact verification.

Final validity of each candidate:
  noop               -> valid (trivially: file unchanged), never shorter
  matches_reference  -> valid (the reference edit was kernel-verified at
                        dataset build AND re-elaborated out of process);
                        a subsample is re-checked in the agreement pass
  screen fail / introduces_sorry / splice_mismatch / unsupported_import /
  source_missing     -> invalid (zero savings)
  screen pass / screen_baseline_broken
                     -> verdict of exact verify_pair.py (pass -> valid);
                        missing exact verdict -> invalid (conservative)

Savings model: an edit is applied only if valid AND strictly token-shorter
under the selected token counter (LEANPOLISH_COUNTER, below); otherwise the file is left
unchanged and the candidate contributes exactly zero savings.

Metrics per (model_tag, corpus):
  valid@1, valid_shorter@1          (greedy decoding)
  valid@4, valid_shorter@4          (any of the 4 stochastic samples)
  aggregate token savings @1 and best-of-4, failures = 0,
    absolute and as % of total original file tokens (unique files)
  median savings conditional on a valid improvement (greedy)
  files with >= 1 valid improvement
  exact-match@1 vs the reference replacement (secondary)
  95% bootstrap CIs by SOURCE FILE for the headline rates and savings
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import random
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("LEANPOLISH_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "leanpolish"))
# Token counter: LEANPOLISH_COUNTER=appL (default; retokenize_appendixL.count_appL, counts
# comments) or lean (Python port of LeanPolish.lean countLeanTokens, the primary counter
# used for the token columns of the paper tables).
if os.environ.get("LEANPOLISH_COUNTER", "appL") == "lean":
    from lean_counter import count_lean_tokens as count_appL  # noqa: E402
else:
    from retokenize_appendixL import count_appL  # noqa: E402


def ckey(c) -> str:
    return hashlib.sha256(
        f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}"
        .encode()).hexdigest()


TRIVIAL_VALID = {"noop", "matches_reference"}
INVALID_SCREEN = {"fail", "introduces_sorry", "splice_mismatch",
                  "unsupported_import", "source_missing", "missing"}


def load_jsonl(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--exact-glob", required=True,
                    help="glob of chunk_*.kernel_verified.jsonl files")
    ap.add_argument("--out", required=True)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    screen = {r["key"]: r.get("screen_verdict", "missing")
              for r in load_jsonl(args.screen)}
    exact = {}
    for p in sorted(glob.glob(args.exact_glob)):
        for r in load_jsonl(p):
            exact[r["key"]] = r.get("kernel_verdict")

    cands = []
    for p in args.cands:
        cands.extend(load_jsonl(p))

    # resolve validity + savings per candidate
    n_exact_used = 0
    for c in cands:
        k = ckey(c)
        sv = screen.get(k, "missing")
        if sv in TRIVIAL_VALID:
            valid = True
        elif sv in INVALID_SCREEN:
            valid = False
        else:  # pass / screen_baseline_broken -> exact lane decides
            valid = exact.get(k) == "pass"
            n_exact_used += 1
        tok_orig = count_appL(c["original"])
        tok_repl = count_appL(c["replacement"])
        c["_valid"] = valid
        c["_tok_savings"] = tok_orig - tok_repl
        c["_shorter"] = valid and (tok_orig - tok_repl) > 0
        c["_applied_savings"] = (tok_orig - tok_repl) if c["_shorter"] else 0
        c["_exact_match"] = (c["replacement"] == c.get("reference_replacement"))
        ref = c.get("reference_replacement")
        ref_savings = (tok_orig - count_appL(ref)) if ref is not None else None
        # student finds a kernel-valid shortening the teacher did not emit /
        # a strictly larger saving than the teacher's accepted edit
        c["_novel_valid_shorter"] = c["_shorter"] and not c["_exact_match"]
        c["_beats_reference"] = (c["_shorter"] and ref_savings is not None
                                 and c["_tok_savings"] > ref_savings)
        c["_screen_verdict"] = sv

    # group candidates per (model, corpus, site)
    sites = defaultdict(lambda: {"greedy": None, "sampled": []})
    for c in cands:
        skey = (c["model_tag"], c["corpus"], c["file"],
                c["start_byte"], c["end_byte"])
        if c["decoding_index"] == "greedy":
            sites[skey]["greedy"] = c
        else:
            sites[skey]["sampled"].append(c)

    # per-file aggregation for bootstrap
    per_file = defaultdict(lambda: defaultdict(list))  # (tag,corpus) -> file -> site rows
    file_tokens = {}
    for (tag, corpus, file, s, e), d in sites.items():
        g, smp = d["greedy"], d["sampled"]
        best = max(smp, key=lambda c: c["_applied_savings"], default=None)
        row = {
            "v1": bool(g and g["_valid"]),
            "vs1": bool(g and g["_shorter"]),
            "sav1": g["_applied_savings"] if g else 0,
            "v4": any(c["_valid"] for c in smp),
            "vs4": any(c["_shorter"] for c in smp),
            "sav4": best["_applied_savings"] if best else 0,
            "em1": bool(g and g["_exact_match"]),
            "nov1": bool(g and g["_novel_valid_shorter"]),
            "nov4": any(c["_novel_valid_shorter"] for c in smp),
            "beat1": bool(g and g["_beats_reference"]),
            "beat4": any(c["_beats_reference"] for c in smp),
        }
        per_file[(tag, corpus)][file].append(row)
        if g and g.get("tokens_original"):
            file_tokens[(corpus, file)] = g["tokens_original"]

    def agg(rows_by_file, files):
        rows = [r for f in files for r in rows_by_file[f]]
        n = len(rows)
        tot_tokens = sum(file_tokens.get((corpus, f), 0) for f in files)
        return {
            "sites": n,
            "valid@1": sum(r["v1"] for r in rows) / n,
            "valid_shorter@1": sum(r["vs1"] for r in rows) / n,
            "valid@4": sum(r["v4"] for r in rows) / n,
            "valid_shorter@4": sum(r["vs4"] for r in rows) / n,
            "savings@1": sum(r["sav1"] for r in rows),
            "savings@4": sum(r["sav4"] for r in rows),
            "savings@1_pct_of_corpus": (100 * sum(r["sav1"] for r in rows)
                                        / tot_tokens if tot_tokens else None),
            "savings@4_pct_of_corpus": (100 * sum(r["sav4"] for r in rows)
                                        / tot_tokens if tot_tokens else None),
            "exact_match@1": sum(r["em1"] for r in rows) / n,
            "novel_valid_shorter@1": sum(r["nov1"] for r in rows) / n,
            "novel_valid_shorter@4": sum(r["nov4"] for r in rows) / n,
            "beats_reference@1": sum(r["beat1"] for r in rows) / n,
            "beats_reference@4": sum(r["beat4"] for r in rows) / n,
            "files_with_improvement@1":
                sum(1 for f in files if any(r["vs1"] for r in rows_by_file[f])),
        }

    rng = random.Random(args.seed)
    results = {}
    for (tag, corpus), rows_by_file in sorted(per_file.items()):
        files = sorted(rows_by_file)
        point = agg(rows_by_file, files)
        med = sorted(r["sav1"] for f in files for r in rows_by_file[f]
                     if r["vs1"])
        point["median_savings_given_improvement@1"] = (
            med[len(med) // 2] if med else None)
        boots = defaultdict(list)
        for _ in range(args.bootstrap):
            bs_files = [files[rng.randrange(len(files))] for _ in files]
            a = agg(rows_by_file, bs_files)
            for m in ("valid@1", "valid_shorter@1", "valid@4",
                      "valid_shorter@4", "savings@1", "savings@4"):
                boots[m].append(a[m])
        for m, vals in boots.items():
            vals.sort()
            point[f"{m}_ci95"] = [vals[int(0.025 * len(vals))],
                                  vals[int(0.975 * len(vals))]]
        results[f"{tag}/{corpus}"] = point

    meta = {
        "n_candidates": len(cands),
        "n_sites": len(sites),
        "screen_verdict_dist": dict(
            __import__("collections").Counter(c["_screen_verdict"] for c in cands)),
        "exact_lane_candidates": n_exact_used,
        "policy": "edit applied iff kernel-valid AND strictly appL-token-shorter; "
                  "all other candidates contribute zero savings",
    }
    out = {"meta": meta, "results": results}
    Path(args.out).write_text(json.dumps(out, indent=2))

    # compact table
    print(f"{'condition':<28} {'valid@1':>8} {'v+s@1':>8} {'v+s@4':>8} "
          f"{'sav@1':>8} {'sav@4':>8} {'sav@1%':>7}")
    for k, v in results.items():
        print(f"{k:<28} {v['valid@1']:>8.3f} {v['valid_shorter@1']:>8.3f} "
              f"{v['valid_shorter@4']:>8.3f} {v['savings@1']:>8} "
              f"{v['savings@4']:>8} "
              f"{(v['savings@1_pct_of_corpus'] or 0):>7.2f}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
