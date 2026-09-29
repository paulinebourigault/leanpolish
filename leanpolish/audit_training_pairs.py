#!/usr/bin/env python3
"""Audit LeanPolish training-pair jsonl files.

For each input row, the audit preserves the original record and adds
``audit_flags`` plus ``audit_severity`` metadata. It also writes a clean subset
containing rows whose severity is ``ok`` or ``info`` and a summary of flag
counts. The audit is conservative: it reports possible soundness, provenance,
and quality issues without deleting source records.

Usage:
    python3 audit_training_pairs.py                 # default file list
    python3 audit_training_pairs.py file1 file2 ... # explicit list
    python3 audit_training_pairs.py --no-write      # report only
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ─────────────────────────────────────────────────────────────────────────────
# Config: known categories and tactic taxonomy
# ─────────────────────────────────────────────────────────────────────────────

KNOWN_TYPES = {
    "tactic_replacement",
    "l2_replacement",
    "l2_detection",
    "dead_code_removal",
    "warning_cleanup",
    # Negative example: a tactic that was tried at this site and rejected
    # by the verifier.  Shares `attempt_id` with the accepted pair.
    "rejected_attempt",
}

# Structural tactics that name witnesses or perform case analysis.
# Replacing one of these with an opaque automation tactic loses information.
STRUCTURAL_TACTICS = {
    "induction", "induction'", "cases", "cases'", "rcases", "rintro",
    "obtain", "match", "fun_cases", "intro", "intros",
    "use", "refine", "refine'", "constructor",
    "exact", "exact?", "apply", "apply?",
    "calc", "show", "have", "let", "set", "suffices",
}

# Opaque automation tactics: powerful, terse, but lose intent/structure.
OPAQUE_TACTICS = {
    "simp", "simp_all", "decide", "tauto", "aesop",
    "omega", "linarith", "nlinarith", "polyrith", "positivity",
    "norm_num", "norm_cast", "ring", "field_simp",
    "trivial", "exact?", "hint",
}

# Internal Lean name-mangling artifacts that should never appear in
# user-facing replacement text.
INTERNAL_NAME_MARKERS = (
    "_uniq.", "._@.", "._hyg.", "auxLemma", "_aux_def_",
    "<failed to format>", "<unknown>", "_macroExpand",
    "_eta_expand", ".match_", ".proof_",
)

# Sorry markers — any of these in the replacement is a hard-fail.
SORRY_MARKERS = (
    re.compile(r"\bsorry\b"),
    re.compile(r"\bsorryAx\b"),
    re.compile(r"\badmit\b"),
)

# Bracket pairs to balance-check inside replacement text.
# `⟨` / `⟩` are the only multi-byte ones we care about in Lean.
BRACKET_PAIRS = [("(", ")"), ("[", "]"), ("{", "}"), ("⟨", "⟩")]

# Tokens that should not be the very last non-whitespace text of a
# tactic-position replacement (would leave a dangling expression).
TRAILING_DANGLERS = (";", ",", ":=", "=>", "<;>", "·", "|", "↦")

# A first-token regex extractor for the replacement.  Lean tactic names
# can contain alphanumerics, underscores, primes, dots and the question
# mark suffix.
FIRST_TOKEN_RE = re.compile(r"^\s*([A-Za-z_][\w'.?!]*)")

# `have h : T := pf` style, capturing the introduced name.
HAVE_NAME_RE = re.compile(r"\bhave\s+([A-Za-z_][\w']*)\s*[:(]")

# ─────────────────────────────────────────────────────────────────────────────
# Default file list (relative to repo root).
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = [
    REPO_ROOT / "LeanPolish/mathlib_optimization/rl_training_data.jsonl",
    REPO_ROOT / "LeanPolish/putnam_bench_proofs/rl_training_data.jsonl",
    REPO_ROOT / "data/Putnam2025/AxiomProver_Putnam2025/rl_training_data.jsonl",
    REPO_ROOT / "data/Putnam2025/AxiomProver_Putnam2025/putnam_bench_proofs/rl_training_data.jsonl",
]

# ─────────────────────────────────────────────────────────────────────────────
# Audit data structures
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_RANK = {"ok": 0, "info": 1, "warn": 2, "error": 3}


@dataclass
class Flag:
    code: str          # short stable id, e.g. "sorry_in_replacement"
    severity: str      # ok | info | warn | error
    detail: str = ""   # optional human-readable note

    def to_obj(self) -> dict[str, str]:
        out = {"code": self.code, "severity": self.severity}
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class AuditResult:
    flags: list[Flag] = field(default_factory=list)

    def add(self, code: str, severity: str, detail: str = "") -> None:
        self.flags.append(Flag(code, severity, detail))

    def severity(self) -> str:
        if not self.flags:
            return "ok"
        return max((f.severity for f in self.flags), key=lambda s: SEVERITY_RANK[s])


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks.  Each takes the parsed record and an AuditResult
# accumulator.  Order matters only for reading: severity is taken as the
# max across all flags.
# ─────────────────────────────────────────────────────────────────────────────

def _first_token(s: str) -> str:
    m = FIRST_TOKEN_RE.match(s or "")
    return m.group(1) if m else ""


def check_schema(rec: dict, ar: AuditResult) -> None:
    required = ("original", "replacement", "kind", "type", "file",
                "start_byte", "end_byte", "bytes_original", "bytes_shortened")
    for k in required:
        if k not in rec:
            ar.add("schema_missing_field", "error", k)
    t = rec.get("type", "")
    if t and t not in KNOWN_TYPES:
        ar.add("schema_unknown_type", "warn", t)


def check_byte_range(rec: dict, ar: AuditResult) -> None:
    s = rec.get("start_byte"); e = rec.get("end_byte")
    bo = rec.get("bytes_original")
    if not (isinstance(s, int) and isinstance(e, int)):
        return
    if s < 0 or e < 0:
        ar.add("byte_range_negative", "error", f"{s}..{e}")
    if e < s:
        ar.add("byte_range_inverted", "error", f"{s}..{e}")
    if isinstance(bo, int) and e > bo:
        # warning_cleanup records can legitimately have line-based positions
        # beyond byte_original since they reference shortened text positions.
        sev = "warn" if rec.get("type") == "warning_cleanup" else "error"
        ar.add("byte_range_past_eof", sev, f"end={e} bytes_original={bo}")


def check_size_metrics(rec: dict, ar: AuditResult) -> None:
    bo = rec.get("bytes_original"); bs = rec.get("bytes_shortened")
    if isinstance(bo, int) and isinstance(bs, int):
        if bs > bo:
            ar.add("file_grew", "warn",
                   f"bytes_original={bo} bytes_shortened={bs}")
    sav = rec.get("savings")
    orig = rec.get("original", "") or ""
    repl = rec.get("replacement", "") or ""
    if isinstance(sav, int) and sav < 0:
        ar.add("negative_savings", "warn", f"savings={sav}")
    if rec.get("type") in {"tactic_replacement", "l2_replacement"}:
        if len(repl) >= len(orig) and orig and repl:
            ar.add("replacement_not_shorter", "warn",
                   f"orig={len(orig)} repl={len(repl)}")


def check_identity(rec: dict, ar: AuditResult) -> None:
    # Negative pairs legitimately may match the original, 
    # so skip the identity check there.
    if rec.get("type") == "rejected_attempt":
        return
    orig = (rec.get("original") or "").strip()
    repl = (rec.get("replacement") or "").strip()
    if orig and orig == repl:
        ar.add("identity_replacement", "error", "original == replacement")


def check_sorry(rec: dict, ar: AuditResult) -> None:
    repl = rec.get("replacement", "") or ""
    for pat in SORRY_MARKERS:
        if pat.search(repl):
            ar.add("sorry_in_replacement", "error", pat.pattern)
            break


def check_internal_names(rec: dict, ar: AuditResult) -> None:
    repl = rec.get("replacement", "") or ""
    for marker in INTERNAL_NAME_MARKERS:
        if marker in repl:
            ar.add("internal_name_leak", "error", marker)
            break


def check_dead_code_emptiness(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") != "dead_code_removal":
        return
    repl = (rec.get("replacement") or "").strip()
    if repl:
        ar.add("dead_code_nonempty_replacement", "error",
               f"len={len(repl)}")


def check_nondead_emptiness(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") in {"dead_code_removal", "warning_cleanup"}:
        return
    if not (rec.get("replacement") or "").strip():
        orig = (rec.get("original") or "").strip()
        if orig:
            ar.add("empty_replacement_nondead", "error", "")


def check_brackets(rec: dict, ar: AuditResult) -> None:
    repl = rec.get("replacement", "") or ""
    if not repl:
        return
    for opener, closer in BRACKET_PAIRS:
        if repl.count(opener) != repl.count(closer):
            ar.add("bracket_mismatch", "error",
                   f"{opener}={repl.count(opener)} {closer}={repl.count(closer)}")


def check_trailing_dangler(rec: dict, ar: AuditResult) -> None:
    repl = (rec.get("replacement") or "").rstrip()
    if not repl:
        return
    for dangler in TRAILING_DANGLERS:
        if repl.endswith(dangler):
            ar.add("trailing_dangler", "warn", dangler)
            break


def check_bare_simp(rec: dict, ar: AuditResult) -> None:
    """Bare `simp` is the canonical anti-pattern: opaque, slow, fragile.

    Flag when:
      (a) replacement is exactly `simp` (no `[..]` and not `simp only`), AND
      (b) original was a more specific simp variant or any structural tactic.
    """
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    repl = (rec.get("replacement") or "").strip()
    if repl != "simp":
        return
    orig_first = _first_token(rec.get("original") or "")
    if orig_first in {"simp", "simp?"}:
        # downgrade only if original carried more info
        orig = rec.get("original") or ""
        if "[" in orig or "only" in orig:
            ar.add("simp_lost_lemmas", "warn",
                   "simp [..] / simp only [..] -> bare simp")
    else:
        ar.add("bare_simp_downgrade", "warn",
               f"orig_tactic={orig_first or '?'}")


def check_simp_only_to_simp(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    orig = (rec.get("original") or "").lstrip()
    repl = (rec.get("replacement") or "").strip()
    if orig.startswith("simp only") and repl.split() and repl.split()[0] in {"simp", "simp_all"}:
        if "only" not in repl:
            ar.add("simp_only_widened", "warn",
                   f"orig=simp_only repl={repl[:40]}")


def check_structural_to_opaque(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    orig_tok = _first_token(rec.get("original") or "")
    repl_tok = _first_token(rec.get("replacement") or "")
    if orig_tok in STRUCTURAL_TACTICS and repl_tok in OPAQUE_TACTICS:
        ar.add("structural_to_opaque", "warn",
               f"{orig_tok} -> {repl_tok}")


def check_named_have_inlined(rec: dict, ar: AuditResult) -> None:
    """If `have h := pf` is being inlined and `h` is referenced elsewhere
    in the visible context window, the inline silently breaks downstream
    code (verification will catch it but the pair is wasted compute and
    misleading as training signal).

    Limitation: `context` is a ±300-char window; this is a partial check.
    True detection would need full file source.
    """
    orig = rec.get("original") or ""
    if "have" not in orig:
        return
    m = HAVE_NAME_RE.search(orig)
    if not m:
        return
    name = m.group(1)
    ctx = rec.get("context") or ""
    # exclude the original block itself from the search
    ctx_minus_orig = ctx.replace(orig, "", 1)
    pat = re.compile(rf"\b{re.escape(name)}\b")
    if pat.search(ctx_minus_orig):
        ar.add("have_name_referenced", "warn",
               f"name={name}")


def check_decide_blowup_risk(rec: dict, ar: AuditResult) -> None:
    """`decide` reduces in the kernel; if the goal type is large,
    introducing `decide` may compile but blow up kernel reduction."""
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    repl_tok = _first_token(rec.get("replacement") or "")
    if repl_tok != "decide":
        return
    orig_tok = _first_token(rec.get("original") or "")
    if orig_tok == "decide":
        return
    goal = rec.get("goal_pretty") or rec.get("goal_type") or ""
    if len(goal) > 200:
        ar.add("decide_on_large_goal", "info",
               f"goal_len={len(goal)}")


def check_omega_linarith_swap(rec: dict, ar: AuditResult) -> None:
    """omega ↔ linarith are not interchangeable: omega = ℤ/ℕ Presburger,
    linarith = ordered fields.  Flag swaps (verifier may have caught a
    spurious success on a weaker domain)."""
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    o = _first_token(rec.get("original") or "")
    r = _first_token(rec.get("replacement") or "")
    if {o, r} == {"omega", "linarith"} or {o, r} == {"omega", "nlinarith"}:
        ar.add("omega_linarith_swap", "info", f"{o} -> {r}")


def check_missing_pretty(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") not in {"tactic_replacement", "l2_replacement"}:
        return
    if not rec.get("goal_pretty"):
        ar.add("missing_goal_pretty", "info", "")


def check_missing_failed_tactics(rec: dict, ar: AuditResult) -> None:
    if rec.get("type") != "tactic_replacement":
        return
    ft = rec.get("failed_tactics")
    if ft is None:
        ar.add("missing_failed_tactics", "info", "field absent")
    elif isinstance(ft, list) and not ft:
        ar.add("empty_failed_tactics", "info", "")


# Master checklist.  Order is for readability only.
ALL_CHECKS = [
    check_schema,
    check_byte_range,
    check_size_metrics,
    check_identity,
    check_sorry,
    check_internal_names,
    check_dead_code_emptiness,
    check_nondead_emptiness,
    check_brackets,
    check_trailing_dangler,
    check_bare_simp,
    check_simp_only_to_simp,
    check_structural_to_opaque,
    check_named_have_inlined,
    check_decide_blowup_risk,
    check_omega_linarith_swap,
    check_missing_pretty,
    check_missing_failed_tactics,
]


def audit_record(rec: dict) -> AuditResult:
    ar = AuditResult()
    for check in ALL_CHECKS:
        try:
            check(rec, ar)
        except Exception as exc:  # defensive: a buggy check must not
            ar.add("audit_check_crashed", "info",  # taint the data
                   f"{check.__name__}: {exc!r}")
    return ar


# ─────────────────────────────────────────────────────────────────────────────
# Cross-record checks (duplicates, contradictory pairs)
# ─────────────────────────────────────────────────────────────────────────────

def cross_check(records: list[tuple[dict, AuditResult]]) -> None:
    """Add audit flags for duplicates and contradictory pairs across the
    file.  Mutates AuditResults in place."""
    by_loc: dict[tuple, list[int]] = collections.defaultdict(list)
    for i, (rec, _) in enumerate(records):
        key = (rec.get("file"), rec.get("start_byte"), rec.get("end_byte"),
               rec.get("type"))
        if key[0] is not None and key[1] is not None and key[2] is not None:
            by_loc[key].append(i)
    for key, idxs in by_loc.items():
        if len(idxs) <= 1:
            continue
        repls = {(records[i][0].get("replacement") or "").strip() for i in idxs}
        if len(repls) == 1:
            for i in idxs[1:]:  # keep first, flag the rest
                records[i][1].add("duplicate_pair", "info",
                                  f"first_idx={idxs[0]}")
        else:
            for i in idxs:
                records[i][1].add("contradictory_pair", "error",
                                  f"distinct_replacements={len(repls)}")


# ─────────────────────────────────────────────────────────────────────────────
# I/O + reporting
# ─────────────────────────────────────────────────────────────────────────────

def process_file(path: Path, write: bool) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    audited_path = path.with_suffix(".audited.jsonl")
    clean_path = path.with_suffix(".clean.jsonl")
    report_path = path.with_suffix(".audit_report.json")

    records: list[tuple[dict, AuditResult]] = []
    parse_errors = 0
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.rstrip("\n")
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError as exc:
                parse_errors += 1
                placeholder = {
                    "_parse_error": str(exc),
                    "_raw": raw[:500],
                    "_lineno": lineno,
                    "type": "parse_error",
                }
                ar = AuditResult()
                ar.add("json_parse_error", "error", str(exc))
                records.append((placeholder, ar))
                continue
            ar = audit_record(rec)
            records.append((rec, ar))

    cross_check(records)

    flag_counts: collections.Counter = collections.Counter()
    severity_counts: collections.Counter = collections.Counter()
    by_type_severity: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for rec, ar in records:
        sev = ar.severity()
        severity_counts[sev] += 1
        by_type_severity[rec.get("type", "?")][sev] += 1
        for f in ar.flags:
            flag_counts[f.code] += 1

    if write:
        with audited_path.open("w", encoding="utf-8") as fa, \
             clean_path.open("w", encoding="utf-8") as fc:
            for rec, ar in records:
                sev = ar.severity()
                out = dict(rec)
                out["audit_severity"] = sev
                out["audit_flags"] = [f.to_obj() for f in ar.flags]
                fa.write(json.dumps(out, ensure_ascii=False) + "\n")
                if sev in {"ok", "info"} and not rec.get("_parse_error"):
                    fc.write(json.dumps(rec, ensure_ascii=False) + "\n")
        report_obj = {
            "input_file": str(path),
            "audited_file": str(audited_path),
            "clean_file": str(clean_path),
            "total_records": len(records),
            "parse_errors": parse_errors,
            "severity_counts": dict(severity_counts),
            "flag_counts": dict(flag_counts.most_common()),
            "by_type_severity": {t: dict(c) for t, c in by_type_severity.items()},
        }
        report_path.write_text(json.dumps(report_obj, indent=2))

    return {
        "path": str(path),
        "exists": True,
        "total": len(records),
        "parse_errors": parse_errors,
        "severity_counts": dict(severity_counts),
        "flag_counts": dict(flag_counts),
        "by_type_severity": {t: dict(c) for t, c in by_type_severity.items()},
    }


def print_summary(results: list[dict[str, Any]]) -> None:
    print()
    print("=" * 78)
    print("Per-file summary")
    print("=" * 78)
    grand_total = 0
    grand_sev: collections.Counter = collections.Counter()
    grand_flags: collections.Counter = collections.Counter()
    grand_type_sev: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for r in results:
        if not r.get("exists"):
            print(f"\n[MISSING] {r['path']}")
            continue
        print(f"\n{r['path']}")
        print(f"  total={r['total']}  parse_errors={r['parse_errors']}")
        print(f"  severity: " + ", ".join(
            f"{k}={v}" for k, v in sorted(r['severity_counts'].items(),
                                          key=lambda x: -SEVERITY_RANK[x[0]])))
        grand_total += r['total']
        for k, v in r['severity_counts'].items():
            grand_sev[k] += v
        for k, v in r['flag_counts'].items():
            grand_flags[k] += v
        for t, sc in r.get("by_type_severity", {}).items():
            for s, n in sc.items():
                grand_type_sev[t][s] += n

    print()
    print("=" * 78)
    print(f"GRAND TOTAL: {grand_total} pairs")
    print("=" * 78)
    print("\nSeverity:")
    for s in ("error", "warn", "info", "ok"):
        print(f"  {s:>6}: {grand_sev.get(s, 0):6}")

    print("\nFlag counts (sorted):")
    for code, n in grand_flags.most_common():
        print(f"  {n:6}  {code}")

    print("\nSeverity breakdown by record type:")
    for t in sorted(grand_type_sev):
        sc = grand_type_sev[t]
        line = ", ".join(f"{k}={sc.get(k, 0)}" for k in ("error", "warn", "info", "ok"))
        print(f"  {t:<22} {line}")

    clean = grand_sev.get("ok", 0) + grand_sev.get("info", 0)
    pct = (100.0 * clean / grand_total) if grand_total else 0
    print(f"\nClean dataset (ok + info, no warn/error): {clean} / {grand_total} "
          f"({pct:.1f}%)")


def main(argv: Iterable[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("files", nargs="*", help="JSONL files to audit")
    p.add_argument("--no-write", action="store_true",
                   help="Report only; do not emit *.audited.jsonl or *.clean.jsonl")
    args = p.parse_args(list(argv))

    paths = [Path(f) for f in args.files] if args.files else DEFAULT_FILES
    write = not args.no_write
    results = [process_file(Path(p), write) for p in paths]
    print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
