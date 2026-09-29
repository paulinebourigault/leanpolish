"""Shared helpers for complete-menu pools (ranker experiment)."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path

WS = re.compile(r"\s+")
NO_GOAL_TEXT = "(no local goal)"
TEMPLATE = "[GOAL]\n{goal}\n\n[ORIGINAL]\n{original}\n\n[CANDIDATE]\n{candidate}"
TEMPLATE_NOGOAL = "[ORIGINAL]\n{original}\n\n[CANDIDATE]\n{candidate}"
PROMPT_TEMPLATE = "[GOAL]\n{goal}\n\n[ORIGINAL]\n{original}\n\n[CANDIDATE]\n"

MENU = ["rfl", "ring", "abel", "norm_num", "norm_cast", "positivity", "decide",
        "linarith", "omega", "field_simp", "contradiction", "ext", "gcongr",
        "tauto", "simp?"]
ACCEPTABLE = {"chosen", "valid_not_chosen"}
MENU_POOL_RE = re.compile(r"\[MENU_POOL\] (\{.*\})\s*$")


def norm(s: str) -> str:
    return WS.sub(" ", s).strip()


def goal_hash(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()


def open_any(p):
    p = str(p)
    return gzip.open(p, "rt") if p.endswith(".gz") else open(p)


def load_sites(path) -> list[dict]:
    with open_any(path) as f:
        return [json.loads(l) for l in f if l.strip()]


def goal_text(site: dict, max_goal_chars: int = 1500) -> str:
    g = site.get("goal_state") or site.get("goal_pretty") or ""
    if not g.strip():
        return NO_GOAL_TEXT
    if len(g) > max_goal_chars:
        g = g[:max_goal_chars] + " …"
    return g


def cand_text(site: dict, cand: dict, with_goal: bool = True) -> str:
    if with_goal:
        return TEMPLATE.format(goal=goal_text(site), original=site["original"],
                               candidate=cand["final_tac"])
    return TEMPLATE_NOGOAL.format(original=site["original"], candidate=cand["final_tac"])


def pool_candidates(site: dict) -> list[dict]:
    """Candidates that were actually run (not length-skipped)."""
    return [c for c in site["candidates"] if not c.get("skipped")]


def annotate(site: dict) -> dict:
    """Add per-candidate labels: valid, acceptable (valid & shorter & quality gate),
    best (acceptable with minimal final length), savings (chars, 0 if not acceptable).
    Adds site-level fields n_valid, n_acceptable, has_best, oracle_savings."""
    cands = pool_candidates(site)
    orig_len = len(site["original"])
    acc = [c for c in cands if c.get("outcome") in ACCEPTABLE]
    min_len = min((len(c["final_tac"]) for c in acc), default=None)
    for c in cands:
        c["is_valid"] = bool(c.get("valid"))
        c["is_acceptable"] = c.get("outcome") in ACCEPTABLE
        c["is_best"] = c["is_acceptable"] and len(c["final_tac"]) == min_len
        c["savings"] = max(0, orig_len - len(c["final_tac"])) if c["is_acceptable"] else 0
    site["_cands"] = cands
    site["n_valid"] = sum(c["is_valid"] for c in cands)
    site["n_acceptable"] = len(acc)
    site["has_best"] = min_len is not None
    site["oracle_savings"] = max((c["savings"] for c in cands), default=0)
    return site


def site_key(site: dict) -> str:
    return f"{site.get('corpus','')}|{site['file']}|{site['start_byte']}|{site['end_byte']}"


def parse_logs(log_paths, corpus: str) -> list[dict]:
    seen = set()
    out = []
    for lp in log_paths:
        with open(lp, errors="replace") as f:
            for line in f:
                m = MENU_POOL_RE.search(line)
                if not m:
                    continue
                try:
                    d = json.loads(m.group(1))
                except json.JSONDecodeError:
                    continue
                d["corpus"] = corpus
                k = site_key(d)
                if k in seen:
                    continue
                seen.add(k)
                out.append(d)
    return out
