#!/usr/bin/env python3
"""Metrics for the frozen few-shot baseline (greedy, k=4 fixed demos).

Policy (as in the paper): a candidate counts as a success iff its
exact fresh-compilation verdict (verify_pair.verify_row via
verify_fewshot.py) is `pass` AND it is strictly shorter under the
selected token counter (LEANPOLISH_COUNTER, below). Everything else contributes exactly zero
(failures = 0). Candidates eligible for Lean but without a verdict yet are
reported as `pending` (coverage) and counted as zero.

Reported per (model, corpus), per (model, edit family) and per
(model, corpus, family); family = deletion (dead_code_removal) /
tactic (tactic_replacement) / other (l2_replacement, 1 site):
  sites, valid_shorter@1 (+ file-bootstrap 95% CI, 2,000 resamples, seed 42),
  token savings (failures = 0), savings as % of total original file
  tokens (unique files, via tokens_original) [corpus rows only],
  teacher (reference) savings on the same sites and recovery %,
  exact-match with reference, output-shape counts (deletion / noop /
  not-shorter / Lean-checked / pending).

Usage:
  python compute_fewshot_metrics.py --cands cands_fewshot_*.jsonl \
      --verdicts verdicts_fewshot.jsonl --out fewshot_metrics.json \
      [--md fewshot_results.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("LEANPOLISH_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / "leanpolish"))
# Token counter: LEANPOLISH_COUNTER=appL (default; retokenize_appendixL.count_appL, counts
# comments) or lean (Python port of LeanPolish.lean countLeanTokens, the primary counter
# used for the token columns of the paper tables).
if os.environ.get("LEANPOLISH_COUNTER", "appL") == "lean":
    from lean_counter import count_lean_tokens as count_appL  # noqa: E402
else:
    from retokenize_appendixL import count_appL  # noqa: E402

FAMILY = {"dead_code_removal": "deletion", "tactic_replacement": "tactic"}
CORPUS_ORDER = ["minif2f", "putnam_verified", "putnam2025_per_file"]


def ckey(c) -> str:
    return hashlib.sha256(
        f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}"
        .encode()).hexdigest()


def load(path):
    with open(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("--verdicts", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--md", default=None)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    verdict = {}
    for p in args.verdicts:
        for r in load(p):
            verdict[r["key"]] = r["kernel_verdict"]

    rows = []
    for p in args.cands:
        for c in load(p):
            if c.get("decoding_index", "greedy") != "greedy":
                continue
            k = ckey(c)
            to, tr = count_appL(c["original"]), count_appL(c["replacement"])
            ref = c.get("reference_replacement")
            v = verdict.get(k)
            if c["replacement"] == c["original"]:
                shape = "noop"
            elif tr >= to:
                shape = "not_shorter"
            elif v is None:
                shape = "pending"
            else:
                shape = "lean_checked"
            success = (v == "pass") and tr < to
            rows.append({
                "model": c["model_tag"], "corpus": c["corpus"], "file": c["file"],
                "family": FAMILY.get(c["type"], "other"),
                "success": success, "sav": (to - tr) if success else 0,
                "ref_sav": (to - count_appL(ref)) if ref is not None else 0,
                "em": c["replacement"] == ref,
                "deletion_output": c["replacement"] == "",
                "shape": shape, "verdict": v,
                "tokens_original": c.get("tokens_original") or 0,
            })

    rng = random.Random(args.seed)

    def summarize(sel, with_corpus_pct):
        by_file = defaultdict(list)
        for r in sel:
            by_file[(r["corpus"], r["file"])].append(r)
        files = sorted(by_file)
        ftok = {f: by_file[f][0]["tokens_original"] for f in files}

        def agg(fs):
            rs = [r for f in fs for r in by_file[f]]
            return (sum(r["success"] for r in rs) / len(rs) if rs else 0.0,
                    sum(r["sav"] for r in rs))
        vs, sav = agg(files)
        bs_vs, bs_sav = [], []
        for _ in range(args.bootstrap):
            fs = [files[rng.randrange(len(files))] for _ in files]
            a, b = agg(fs)
            bs_vs.append(a); bs_sav.append(b)
        bs_vs.sort(); bs_sav.sort()
        lo, hi = int(0.025 * len(bs_vs)), int(0.975 * len(bs_vs))
        ref = sum(r["ref_sav"] for r in sel)
        shapes = Counter(r["shape"] for r in sel)
        verdicts = Counter(r["verdict"] for r in sel if r["shape"] == "lean_checked")
        out = {
            "sites": len(sel), "files": len(files),
            "valid_shorter@1": vs, "valid_shorter@1_ci95": [bs_vs[lo], bs_vs[hi]],
            "n_success": sum(r["success"] for r in sel),
            "savings_appL": sav, "savings_appL_ci95": [bs_sav[lo], bs_sav[hi]],
            "teacher_savings_appL": ref,
            "recovery_pct_of_teacher": (100 * sav / ref) if ref else None,
            "exact_match@1": sum(r["em"] for r in sel) / len(sel),
            "deletion_outputs": sum(r["deletion_output"] for r in sel),
            "output_shapes": dict(shapes),
            "lean_verdicts": dict(verdicts),
            "pending_unverified": shapes.get("pending", 0),
        }
        if with_corpus_pct:
            tot = sum(ftok.values())
            out["original_file_tokens"] = tot
            out["savings_pct_of_corpus"] = (100 * sav / tot) if tot else None
        return out

    models = sorted({r["model"] for r in rows})
    res = {}
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        res[f"{m}/ALL"] = summarize(mr, True)
        for c in CORPUS_ORDER:
            sel = [r for r in mr if r["corpus"] == c]
            if sel:
                res[f"{m}/{c}"] = summarize(sel, True)
        for fam in ("deletion", "tactic", "other"):
            sel = [r for r in mr if r["family"] == fam]
            if sel:
                res[f"{m}/family:{fam}"] = summarize(sel, False)
            for c in CORPUS_ORDER:
                sel = [r for r in mr if r["family"] == fam and r["corpus"] == c]
                if sel:
                    res[f"{m}/{c}/family:{fam}"] = summarize(sel, False)

    meta = {
        "n_candidates": len(rows), "models": models,
        "policy": "success iff exact fresh `lake env lean` pass of the spliced "
                  "file (verify_pair.verify_row) AND strictly shorter by "
                  "count_appL; all other candidates contribute zero",
        "total_pending_unverified": sum(r["shape"] == "pending" for r in rows),
    }
    Path(args.out).write_text(json.dumps({"meta": meta, "results": res}, indent=2))

    hdr = (f"| condition | sites | v+s@1 (95% CI) | savings appL | % corpus "
           f"| teacher sav | recovery | pending |")
    lines = [hdr, "|" + "---|" * 8]
    for k, v in res.items():
        ci = v["valid_shorter@1_ci95"]
        pct = v.get("savings_pct_of_corpus")
        rec = v["recovery_pct_of_teacher"]
        lines.append(
            f"| {k} | {v['sites']} | {100*v['valid_shorter@1']:.1f} "
            f"({100*ci[0]:.1f}–{100*ci[1]:.1f}) | {v['savings_appL']} | "
            f"{'' if pct is None else f'{pct:.2f}'} | {v['teacher_savings_appL']} | "
            f"{'' if rec is None else f'{rec:.1f}%'} | {v['pending_unverified']} |")
    table = "\n".join(lines)
    print(table)
    print(f"\npending (eligible, unverified) candidates: {meta['total_pending_unverified']}")
    if args.md:
        Path(args.md).write_text(table + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
