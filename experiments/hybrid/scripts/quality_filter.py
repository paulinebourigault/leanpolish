"""Python port of LeanPolish.lean `isQualityUpgrade` (line ~716) with the legacy string axis
classifier `tacticAxisOfString` (the Lean binary uses the syntax-tree classifier when an
Environment is in scope; the two agree on plain `tac args` heads, which covers our edits),
plus the teacher's menu / guard metadata used to explain teacher misses."""

STRUCT = {"rfl", "Rfl", "tacticRfl", "ring", "ring1", "ring_nf", "ringNF", "abel", "abel_nf", "abelNF",
          "norm_num", "normNum", "norm_num1", "normNum1", "norm_cast", "normCast", "push_cast", "pushCast",
          "push_neg", "pushNeg", "positivity", "decide", "tacticDecide", "linarith", "Linarith", "linarith!",
          "nlinarith", "Nlinarith", "nlinarith!", "omega", "tacticOmega", "omega_nat", "polyrith", "Polyrith",
          "field_simp", "fieldSimp", "gcongr", "Gcongr", "GCongr", "linear_combination", "linearCombination"}
OPAQUE = {"simp", "tacticSimp", "simp_all", "simpAll", "simp_arith", "simpArith", "simp_rw", "simpRw",
          "aesop", "Aesop", "Aesop_", "hint", "tauto", "Tauto", "fin_cases", "finCases"}

def axis(s):
    s = s.strip()
    if s.startswith("by "): s = s[3:].strip()
    elif s.startswith("· "): s = s[2:].strip()
    head = ''
    for ch in s:
        if ch.isalnum() or ch == '_': head += ch
        else: break
    return 'structural' if head in STRUCT else 'opaque' if head in OPAQUE else 'neutral'

def is_quality_upgrade(orig_text, new_tac):
    def strip(s):
        s = s.strip()
        if s.startswith("· "): s = s[2:].strip()
        if s.startswith("by "): s = s[3:].strip()
        return s
    orig, repl = strip(orig_text), strip(new_tac)
    multi = ';' in orig or '<;>' in orig
    if not multi:
        if (orig.startswith(("exact ", "rw ", "rw[", "rewrite ", "rewrite[", "apply ", "refine ", "refine'",
                             "use ", "convert ", "cases ", "rcases ", "obtain ", "calc ", "induction ", "match ",
                             "nomatch ", "absurd ", "nofun", "conv ", "conv\n"))
                or orig in ("constructor", "left", "right", "exfalso", "symmetry", "nomatch")):
            return False
    if repl == "rfl": return True
    if orig in ("trivial", "assumption", "contradiction"): return False
    if orig in ("ring", "abel"): return False
    simp_like = repl == "simp" or repl.startswith("simp only") or repl.startswith("simp [")
    t3 = repl in ("linarith", "omega", "field_simp", "tauto", "contradiction", "ext", "gcongr") or simp_like
    if orig.startswith("norm_num") and t3: return False
    if orig.startswith("positivity") and t3: return False
    if orig.startswith("norm_cast") and t3: return False
    if orig == "decide" and t3: return False
    t4 = repl in ("field_simp", "tauto", "contradiction", "ext", "gcongr") or simp_like
    if orig.startswith("linarith") and t4: return False
    if orig.startswith("nlinarith") and t4: return False
    if orig.startswith("omega") and t4: return False
    if orig.startswith("field_simp") and simp_like: return False
    if orig == "tauto" and simp_like: return False
    if orig.startswith("gcongr") and simp_like: return False
    if orig.startswith("push_cast") and simp_like: return False
    if orig.startswith("push_neg") and simp_like: return False
    if orig.startswith("simp_rw") and simp_like: return False
    if orig.startswith("simp only") and repl == "simp": return False
    if axis(orig) == 'structural' and axis(repl) == 'opaque': return False
    return True

# teacher menu: tactic -> minimum original span (bytes, strict >) guard from checkAutomations
MENU_GUARD = {"rfl": 3, "ring": 4, "abel": 4, "norm_num": 8, "norm_cast": 9, "positivity": 11, "decide": 6,
              "linarith": 8, "omega": 5, "field_simp": 10, "contradiction": 13, "ext": 3, "gcongr": 6,
              "tauto": 5}
MENU_ORDER = list(MENU_GUARD) + ["simp?", "exact?"]

def menu_class(orig, repl):
    """Return (in_menu: bool, menu_item or None, reason_if_teacher_would_skip or None)."""
    r = repl.strip()
    if r.startswith("by "): r = r[3:].strip()
    ob = len(orig.encode())
    if r in MENU_GUARD:
        if ob <= MENU_GUARD[r]: return True, r, f"length_guard(orig {ob}B <= {MENU_GUARD[r]}B)"
        return True, r, None
    if r.startswith("simp only") :
        return True, "simp?", None if len(r) < len(orig) else "simp?_not_shorter_in_chars"
    if r.startswith("exact ") and "\n" not in r:
        why = []
        if ob <= 20: why.append("exact?_skipped(orig<=20B)")
        if len(r) > 60: why.append("exact?_suggestion>60chars")
        if "'" in r: why.append("exact?_primed_name")
        return True, "exact?", ";".join(why) or None
    return False, None, None
