#!/usr/bin/env python3
"""Recompute token-reduction metrics with the Appendix-L tokenizer.

This script compares original Lean files with LeanPolish or linter outputs
without rerunning either tool. With ``--full-corpus``, files that have no output
file are counted as zero reduction, matching the full-corpus denominator used for
reported metrics.

Usage:
    python retokenize_appendixL.py --tool leanpolish \
        --orig-dir goedel_workbook --short-dir goedel_optimization \
        --full-corpus --out reports/appendixL_goedel_workbook_leanpolish

    python retokenize_appendixL.py --compare \
        --orig-dir goedel_workbook --leanpolish-dir goedel_optimization \
        --linter-dir goedel_workbook --full-corpus \
        --out reports/appendixL_goedel_workbook
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional

# ─── Appendix-L tokenizer (Gu et al. 2025, Appendix L) ─────────────────────

_APPL_OPS_3 = {"...", "<;>"}
_APPL_OPS_2 = {":=", "!=", "&&", "-.", "->", "<-", "..", "::", ":>", ";;",
               "==", "||", "=>", "<=", ">=", "?_"}


def _is_appL_ident_char(c: str) -> bool:
    return c.isalnum() or c in "_.'"


def count_appL(text: str) -> int:
    """Token count under the Appendix-L lexer."""
    toks: List[str] = []
    for line in text.split("\n"):
        cur = ""
        for c in line:
            if c in (" ", "\t"):
                if cur:
                    toks.append(cur)
                    cur = ""
            elif _is_appL_ident_char(c):
                cur += c
            else:
                if cur:
                    toks.append(cur)
                    cur = ""
                toks.append(c)
        if cur:
            toks.append(cur)
    n = len(toks)
    out = 0
    i = 0
    while i < n:
        if i + 3 <= n and (toks[i] + toks[i + 1] + toks[i + 2]) in _APPL_OPS_3:
            out += 1
            i += 3
            continue
        if i + 2 <= n and (toks[i] + toks[i + 1]) in _APPL_OPS_2:
            out += 1
            i += 2
            continue
        out += 1
        i += 1
    return out


# ─── Locating original files and matching shortened/linter outputs ─────────

SUFFIX = {
    "leanpolish": "_shortened.lean",
    "linter":       "_linter.lean",
}
ARTIFACT_SUFFIXES = ("_shortened.lean", "_linter.lean")


def list_originals(orig_dir: Path) -> List[Path]:
    """All original .lean files under `orig_dir` (excluding artifact suffixes)."""
    return sorted(
        f for f in orig_dir.rglob("*.lean")
        if not f.name.startswith(".")
        and not any(f.name.endswith(sfx) for sfx in ARTIFACT_SUFFIXES)
    )


def short_path_for(orig: Path, orig_dir: Path, short_dir: Path, suffix: str) -> Path:
    """Mirror the relative path of `orig` under `short_dir` and add `suffix`."""
    rel = orig.relative_to(orig_dir)
    return (short_dir / rel.parent / (orig.stem + suffix))


# ─── Aggregation ──────────────────────────────────────────────────────────-

def _stats(reductions: List[float]) -> Dict:
    if not reductions:
        return {"n": 0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0,
                "p25": 0.0, "p75": 0.0}
    s = sorted(reductions)
    return {
        "n":      len(s),
        "mean":   round(statistics.mean(s), 4),
        "median": round(statistics.median(s), 4),
        "min":    round(min(s), 4),
        "max":    round(max(s), 4),
        "p25":    round(s[len(s) // 4], 4),
        "p75":    round(s[(3 * len(s)) // 4], 4),
    }


def aggregate(orig_dir: Path, short_dir: Path, suffix: str,
              label: str, full_corpus: bool) -> Dict:
    """
    Walk every original under `orig_dir`. For each, look for the matching
    short_dir/<rel>/<stem><suffix>. If present -> real pair. If absent and
    full_corpus -> count as 0 saving (matches the full-corpus denominator).
    """
    originals = list_originals(orig_dir)
    rows: List[Dict] = []
    total_orig = total_short = 0
    per_file_pct: List[float] = []
    matched = unchanged = 0

    for orig in originals:
        a = orig.read_text(encoding="utf-8", errors="replace")
        ta = count_appL(a)
        sp = short_path_for(orig, orig_dir, short_dir, suffix)
        if sp.exists():
            b = sp.read_text(encoding="utf-8", errors="replace")
            tb = count_appL(b)
            matched += 1
            status = "shortened"
        else:
            if not full_corpus:
                continue           # skip files the tool did not touch
            tb = ta
            unchanged += 1
            status = "unchanged"
        total_orig  += ta
        total_short += tb
        pct = 100.0 * (ta - tb) / ta if ta else 0.0
        per_file_pct.append(pct)
        rows.append({
            "file":                  str(orig),
            "status":                status,
            "tokens_appL_original":  ta,
            "tokens_appL_shortened": tb,
            "tokens_appL_saved":     ta - tb,
            "tokens_appL_pct":       round(pct, 4),
        })

    aggregate_pct = 100.0 * (total_orig - total_short) / total_orig if total_orig else 0.0
    summary = {
        "tool":   label,
        "mode":   "full_corpus" if full_corpus else "shortened_only",
        "files":  len(rows),
        "files_with_output":           matched,
        "files_unchanged":             unchanged,
        "files_total_in_dir":          len(originals),
        "tokens_appL_total_original":  total_orig,
        "tokens_appL_total_shortened": total_short,
        "tokens_appL_total_saved":     total_orig - total_short,
        "headline_pct_aggregate":      round(aggregate_pct, 4),
        "per_file_pct_stats":          _stats(per_file_pct),
    }
    return {"summary": summary, "rows": rows}


# ─── CLI ──────────────────────────────────────────────────────────────────-

def _write_outputs(result: Dict, out_prefix: Path) -> None:
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = out_prefix.with_suffix(".json")
    csv_path  = out_prefix.with_suffix(".csv")
    json_path.write_text(json.dumps(result, indent=2))
    if result["rows"]:
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(result["rows"][0].keys()))
            w.writeheader()
            w.writerows(result["rows"])
    s = result["summary"]
    print(f"[OUT] {json_path}")
    if result["rows"]:
        print(f"[OUT] {csv_path}")
    print(f"[SUMMARY {s['tool']:<13s}] mode={s['mode']:<14s}  "
          f"files={s['files']}  (with_output={s['files_with_output']}, "
          f"unchanged={s['files_unchanged']}, total_in_dir={s['files_total_in_dir']})  "
          f"AppL tokens: {s['tokens_appL_total_original']} → "
          f"{s['tokens_appL_total_shortened']}  "
          f"({s['headline_pct_aggregate']}% aggregate, "
          f"mean per-file {s['per_file_pct_stats']['mean']}%, "
          f"median {s['per_file_pct_stats']['median']}%)")


def _resolve_short_dir(orig_dir: Path, short_dir: Optional[Path]) -> Path:
    return short_dir.resolve() if short_dir else orig_dir.resolve()


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--tool", choices=list(SUFFIX), default="leanpolish")
    ap.add_argument("--orig-dir", type=Path, required=False,
                    help="Directory holding original .lean source files.")
    ap.add_argument("--short-dir", type=Path, default=None,
                    help="Directory holding the tool's *_shortened.lean / "
                         "*_linter.lean outputs (defaults to --orig-dir).")
    ap.add_argument("--full-corpus", action="store_true",
                    help="Include originals where the tool produced no output, "
                         "counted as 0%% reduction. This is the recommended "
                         "denominator for reported aggregate metrics.")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output prefix (writes <prefix>.json and <prefix>.csv).")
    ap.add_argument("--compare", action="store_true",
                    help="Side-by-side: aggregate both tools on the same originals.")
    ap.add_argument("--leanpolish-dir", type=Path, default=None,
                    help="--compare: dir of *_shortened.lean outputs.")
    ap.add_argument("--linter-dir", type=Path, default=None,
                    help="--compare: dir of *_linter.lean outputs.")
    args = ap.parse_args(argv)

    if args.compare:
        if not args.orig_dir:
            ap.error("--compare requires --orig-dir")
        if not (args.leanpolish_dir and args.linter_dir):
            ap.error("--compare requires --leanpolish-dir and --linter-dir")
        ro = aggregate(args.orig_dir.resolve(), args.leanpolish_dir.resolve(),
                       SUFFIX["leanpolish"], "leanpolish", args.full_corpus)
        lb = aggregate(args.orig_dir.resolve(), args.linter_dir.resolve(),
                       SUFFIX["linter"],       "linter",       args.full_corpus)
        out_prefix = args.out or Path("appendixL_comparison")
        _write_outputs(ro, out_prefix.with_name(out_prefix.name + "_leanpolish"))
        _write_outputs(lb, out_prefix.with_name(out_prefix.name + "_linter"))
        return 0

    if not args.orig_dir:
        ap.error("--orig-dir is required")
    short = _resolve_short_dir(args.orig_dir, args.short_dir)
    res = aggregate(args.orig_dir.resolve(), short, SUFFIX[args.tool],
                    args.tool, args.full_corpus)
    out_prefix = args.out or args.orig_dir / f"appendixL_{args.tool}"
    _write_outputs(res, out_prefix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
