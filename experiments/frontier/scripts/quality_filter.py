#!/usr/bin/env python3
"""Python port of LeanPolish.lean `isQualityUpgrade` (LeanPolish.lean ~l.716) with the
string-based tactic-axis classifier `tacticAxisOfString` (the Lean code's documented
fallback when no Environment is in scope; the production call uses the syntax-tree
classifier, which differs only on wrapped forms like `(config := ..) simp` / `first | ..`).
Deletions (empty replacement) are not tactic substitutions and are not subject to this
filter in LeanPolish (dead-code phase); we report them separately.
"""
import re

STRUCTURAL = {"rfl", "Rfl", "tacticRfl", "ring", "ring1", "ring_nf", "ringNF", "abel", "abel_nf",
              "abelNF", "norm_num", "normNum", "norm_num1", "normNum1", "norm_cast", "normCast",
              "push_cast", "pushCast", "push_neg", "pushNeg", "positivity", "decide", "tacticDecide",
              "linarith", "Linarith", "linarith!", "nlinarith", "Nlinarith", "nlinarith!", "omega",
              "tacticOmega", "omega_nat", "polyrith", "Polyrith", "field_simp", "fieldSimp", "gcongr",
              "Gcongr", "GCongr", "linear_combination", "linearCombination"}
OPAQUE = {"simp", "tacticSimp", "simp_all", "simpAll", "simp_arith", "simpArith", "simp_rw",
          "simpRw", "aesop", "Aesop", "Aesop_", "hint", "tauto", "Tauto", "fin_cases", "finCases"}


def axis_of_string(s):
    s = s.strip()
    if s.startswith("by "):
        s = s[3:].strip()
    elif s.startswith("· "):
        s = s[2:].strip()
    m = re.match(r"[A-Za-z0-9_]*", s)
    h = m.group(0)
    return 'structural' if h in STRUCTURAL else 'opaque' if h in OPAQUE else 'neutral'


def is_quality_upgrade(orig_text, new_tac):
    def strip(s):
        s = s.strip()
        if s.startswith("· "):
            s = s[2:].strip()
        if s.startswith("by "):
            s = s[3:].strip()
        return s
    orig, repl = strip(orig_text), strip(new_tac)
    multi = ";" in orig or "<;>" in orig
    if not multi:
        sw = orig.startswith
        if (sw("exact ") or sw("rw ") or sw("rw[") or sw("rewrite ") or sw("rewrite[") or
                sw("apply ") or sw("refine ") or sw("refine'") or sw("use ") or sw("convert ") or
                sw("cases ") or sw("rcases ") or sw("obtain ") or sw("calc ") or
                sw("induction ") or sw("match ") or orig in ("constructor", "left", "right",
                                                             "exfalso", "symmetry", "nomatch") or
                sw("nomatch ") or sw("absurd ") or sw("nofun") or sw("conv ") or sw("conv\n")):
            return False
    if repl == "rfl":
        return True
    if orig in ("trivial", "assumption", "contradiction"):
        return False
    if orig in ("ring", "abel"):
        return False
    simp_like = repl == "simp" or repl.startswith("simp only") or repl.startswith("simp [")
    t3 = repl in ("linarith", "omega", "field_simp", "tauto", "contradiction", "ext", "gcongr") or simp_like
    if (orig.startswith("norm_num") or orig.startswith("positivity") or orig.startswith("norm_cast")
            or orig == "decide") and t3:
        return False
    t4 = repl in ("field_simp", "tauto", "contradiction", "ext", "gcongr") or simp_like
    if (orig.startswith("linarith") or orig.startswith("nlinarith") or orig.startswith("omega")) and t4:
        return False
    if (orig.startswith("field_simp") or orig == "tauto" or orig.startswith("gcongr")) and simp_like:
        return False
    if (orig.startswith("push_cast") or orig.startswith("push_neg") or orig.startswith("simp_rw")) and simp_like:
        return False
    if orig.startswith("simp only") and repl == "simp":
        return False
    if axis_of_string(orig) == 'structural' and axis_of_string(repl) == 'opaque':
        return False
    return True


if __name__ == '__main__':
    tests = [("exact foo", "simp", False), ("norm_num", "simp", False), ("simp only [a]", "simp", False),
             ("nlinarith [x]", "linarith", True), ("linarith", "simp", False), ("ring_nf", "ring", True),
             ("rfl", "simp", False), ("simp [a, b]", "simp", True), ("exact foo; simp", "simp", True)]
    for o, r, exp in tests:
        assert is_quality_upgrade(o, r) == exp, (o, r)
    print('ok')
