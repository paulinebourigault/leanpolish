#!/usr/bin/env python3
"""Recompute the learning-experiment numbers quoted in the paper from saved records.

Read-only. Inputs (environment variables):
  RESULTS_DIR  saved learning-experiment records (default <release>/results_data), with
               data/eval_sites_<corpus>.jsonl, exp1_sft_dpo/{cands_*.jsonl, screen_results*.jsonl,
               verify_chunks*/*.kernel_verified.jsonl}, exp2_ranker/{data/eval_groups_*.jsonl,
               exp2_metrics.json, selection_*}, exp4_corpus_variation/corpus_variation.json
  HEADLINE_JSON  dataset headline totals (default <release>/experiments/metrics/results/headline_v4.json)
  OUT_JSON     output (default ./results/recompute_numbers.json next to this script)
Prints markdown tables to stdout.

Success policy (strict, "pass-only"):
  a candidate is a success iff its candidate key (sha256 of
  file:start:end:replacement, as in compute_metrics.ckey) has an exact-verifier
  kernel_verdict == "pass" in ANY saved exp1_sft_dpo/verify_chunks*/*kernel_verified.jsonl
  record, AND count_appL(original) - count_appL(replacement) > 0.
  Reference matches / noops are NOT treated as automatically valid.
  Failures contribute zero savings.

Usage: python3 experiments/metrics/recompute_numbers.py
"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

import os
HERE = Path(__file__).resolve().parent
SUPP = Path(os.environ.get("LEANPOLISH_ROOT", HERE.parents[1]))
ROOT = SUPP / "leanpolish"
EXP = Path(os.environ.get("RESULTS_DIR", SUPP / "results_data"))
RES = EXP / "exp1_sft_dpo"
HEADLINE_JSON = Path(os.environ.get("HEADLINE_JSON", HERE / "results" / "headline_v4.json"))
OUT_JSON = Path(os.environ.get("OUT_JSON", HERE / "results" / "recompute_numbers.json"))
sys.path.insert(0, str(ROOT))
from retokenize_appendixL import count_appL  # noqa: E402

CORPORA = ["minif2f", "putnam_verified", "putnam2025_per_file"]
MODELS = {  # tag -> candidates file
    "frozen": "cands_frozen.jsonl",
    "frozen_qwen": "cands_frozen_qwen.jsonl",
    "sft": "cands_sft.jsonl",
    "sft_qwen": "cands_sft_qwen.jsonl",
    "dpo": "cands_dpo.jsonl",
}
FAMILY = {"dead_code_removal": "deletion", "tactic_replacement": "tactic_replacement",
          "l2_replacement": "lemma_extraction"}
SEED = 20260926
NBOOT = 10_000
OUT = {}


def ckey(c):
    return hashlib.sha256(
        f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}".encode()
    ).hexdigest()


def read_jsonl(path):
    """Return (records, n_bad_lines, ends_with_newline)."""
    recs, bad = [], 0
    raw = Path(path).read_bytes()
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    return recs, bad, raw.endswith(b"\n")


def md(headers, rows):
    s = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    for r in rows:
        s += "| " + " | ".join(str(x) for x in r) + " |\n"
    return s


def pct(a, b):
    # round-half-up on exact fraction (69/80 -> 86.3%, not float-repr 86.2%)
    from fractions import Fraction
    if not b:
        return "n/a"
    q = Fraction(1000 * a, b)
    return f"{(q.numerator * 2 + q.denominator) // (2 * q.denominator) / 10:.1f}%"


# ---------------------------------------------------------------- 6. integrity
integrity = []
for p in sorted(glob.glob(str(EXP / "data" / "*.jsonl")) + glob.glob(str(RES / "*.jsonl"))
                + glob.glob(str(RES / "verify_chunks*" / "*.jsonl"))
                + glob.glob(str(EXP / "exp2_ranker" / "data" / "*.jsonl"))
                + glob.glob(str(EXP / "exp2_ranker" / "*.jsonl"))):
    recs, bad, nl = read_jsonl(p)
    integrity.append((str(Path(p).relative_to(EXP)), len(recs), bad, nl,
                      Path(p).stat().st_size))
OUT["integrity"] = integrity

# ------------------------------------------------------------ verdicts / sites
verdicts = defaultdict(set)
n_vrec = 0
for p in sorted(glob.glob(str(RES / "verify_chunks*" / "*kernel_verified.jsonl"))):
    for r in read_jsonl(p)[0]:
        n_vrec += 1
        verdicts[r["key"]].add(r.get("kernel_verdict"))
conflicts = sum(1 for v in verdicts.values() if len(v) > 1)
PASS = {k for k, v in verdicts.items() if v == {"pass"}}
OUT["verify"] = {"records": n_vrec, "distinct_keys": len(verdicts),
                 "conflicting_keys": conflicts, "pass_keys": len(PASS)}

# saved-summary replication inputs
screen = {}
for f in ("screen_results.jsonl", "screen_results_qwen.jsonl"):
    for r in read_jsonl(RES / f)[0]:
        screen.setdefault(f, {})[r["key"]] = r.get("screen_verdict", "missing")


def exact_map(globpat):
    m = {}
    for p in sorted(glob.glob(str(RES / globpat))):
        for r in read_jsonl(p)[0]:
            m[r["key"]] = r.get("kernel_verdict")
    return m


sites = {}  # (corpus, file, s, e) -> site record
for c in CORPORA:
    for r in read_jsonl(EXP / "data" / f"eval_sites_{c}.jsonl")[0]:
        sk = (r["corpus"], r["file"], int(r["start_byte"]), int(r["end_byte"]))
        r["_fam"] = FAMILY[r["type"]]
        r["_marker"] = "(no local goal)" in r["prompt"]
        r["_tok_o"] = count_appL(r["original"])
        r["_ref_sav"] = r["_tok_o"] - count_appL(r["reference_replacement"])
        refc = dict(r, replacement=r["reference_replacement"])
        r["_ref_pass"] = ckey(refc) in PASS
        sites[sk] = r
assert len(sites) == 1406, len(sites)

cands = {}  # tag -> list
for tag, f in MODELS.items():
    rows = read_jsonl(RES / f)[0]
    for c in rows:
        c["_key"] = ckey(c)
        c["_sk"] = (c["corpus"], c["file"], int(c["start_byte"]), int(c["end_byte"]))
        c["_sav"] = count_appL(c["original"]) - count_appL(c["replacement"])
        c["_ok"] = c["_key"] in PASS and c["_sav"] > 0
        c["_em"] = c["replacement"] == c.get("reference_replacement")
    cands[tag] = rows
    gs = [c for c in rows if c["decoding_index"] == "greedy"]
    assert len(gs) == 1406 and len({c["_sk"] for c in gs}) == 1406, tag
    assert all(c["_sk"] in sites for c in gs)
greedy = {tag: {c["_sk"]: c for c in rows if c["decoding_index"] == "greedy"}
          for tag, rows in cands.items()}
samples = {tag: defaultdict(list) for tag in cands}
for tag, rows in cands.items():
    for c in rows:
        if c["decoding_index"] != "greedy":
            samples[tag][c["_sk"]].append(c)

# ------------------------------------------------------------- 1. headline
head = {}
tbl = []
for c in CORPORA:
    sk_c = [sk for sk in sites if sk[0] == c]
    teacher = sum(sites[sk]["_ref_sav"] for sk in sk_c)
    teacher_pass = sum(sites[sk]["_ref_sav"] for sk in sk_c
                       if sites[sk]["_ref_pass"] and sites[sk]["_ref_sav"] > 0)
    n_ref_pass = sum(sites[sk]["_ref_pass"] for sk in sk_c)
    teacher_pos = sum(max(sites[sk]["_ref_sav"], 0) for sk in sk_c)
    head[c] = {"sites": len(sk_c), "teacher_savings": teacher, "teacher_savings_clamped": teacher_pos,
               "teacher_savings_passverified": teacher_pass,
               "ref_edits_with_pass_verdict": n_ref_pass,
               "ref_nonpositive_savings": sum(sites[sk]["_ref_sav"] <= 0 for sk in sk_c)}
    for tag in MODELS:
        ok = [greedy[tag][sk] for sk in sk_c if greedy[tag][sk]["_ok"]]
        sav = sum(x["_sav"] for x in ok)
        head[c][tag] = {"vs1": len(ok), "savings1": sav,
                        "recovered_pct": 100 * sav / teacher if teacher else None}
        tbl.append([c, tag, f"{len(ok)} / {len(sk_c)}", pct(len(ok), len(sk_c)),
                    f"{sav:,}", f"{teacher:,}", pct(sav, teacher)])
OUT["headline"] = head
print("## 1. Greedy valid-and-shorter@1 (strict pass-only)\n")
print(md(["corpus", "model", "v+s@1", "rate", "savings@1", "teacher savings", "% recovered"], tbl))
print(md(["corpus", "teacher sum", "teacher sum clamped at 0", "teacher sum (ref key has pass verdict)",
          "ref edits w/ pass verdict", "ref edits with <=0 appL savings"],
         [[c, head[c]["teacher_savings"], head[c]["teacher_savings_clamped"], head[c]["teacher_savings_passverified"],
           f"{head[c]['ref_edits_with_pass_verdict']}/{head[c]['sites']}",
           head[c]["ref_nonpositive_savings"]] for c in CORPORA]))

# --- replicate the saved summaries (experiments/sft/compute_metrics.py policy) for comparison
TRIV = {"noop", "matches_reference"}
INVALID = {"fail", "introduces_sorry", "splice_mismatch", "unsupported_import",
           "source_missing", "missing"}


def legacy(tag, scr, ex):
    res = {}
    for c in CORPORA:
        n = s = 0
        for sk, g in greedy[tag].items():
            if sk[0] != c:
                continue
            sv = scr.get(g["_key"], "missing")
            valid = True if sv in TRIV else (False if sv in INVALID else ex.get(g["_key"]) == "pass")
            if valid and g["_sav"] > 0:
                n += 1
                s += g["_sav"]
        res[c] = (n, s)
    return res


ex_main = exact_map("verify_chunks/chunk_*.kernel_verified.jsonl")
ex_qwen = exact_map("verify_chunks_qwen/chunk_*.kernel_verified.jsonl")
ex_all = exact_map("verify_chunks*/*kernel_verified.jsonl")
scr_main, scr_q = screen["screen_results.jsonl"], screen["screen_results_qwen.jsonl"]
legacy_rows = {
    "dpo: saved policy, exact=verify_chunks/chunk_* only": legacy("dpo", scr_main, ex_main),
    "dpo: saved policy, exact=all verify dirs": legacy("dpo", scr_main, ex_all),
    "sft: saved policy, exact=verify_chunks/chunk_*": legacy("sft", scr_main, ex_main),
    "sft_qwen: saved policy, exact=verify_chunks_qwen/chunk_*": legacy("sft_qwen", scr_q, ex_qwen),
}
OUT["legacy_replication"] = {k: v for k, v in legacy_rows.items()}
print("### Replication of saved summaries under compute_metrics.py policy\n")
print(md(["variant"] + CORPORA,
         [[k] + [f"{v[c][0]} / {v[c][1]:,}" for c in CORPORA] for k, v in legacy_rows.items()]))

# DPO: greedy candidates counted differently under the strict vs the saved-summary policy
dd = Counter()
for sk, g in greedy["dpo"].items():
    sv = scr_main.get(g["_key"], "missing")
    old = (True if sv in TRIV else (False if sv in INVALID else ex_main.get(g["_key"]) == "pass")) and g["_sav"] > 0
    if g["_ok"] != old:
        where = [Path(p).parent.name for p in glob.glob(str(RES / "verify_chunks*" / "*kernel_verified.jsonl"))
                 if any(r["key"] == g["_key"] for r in read_jsonl(p)[0])] if g["_ok"] else []
        dd[(sk[0], "strict_only" if g["_ok"] else "saved_only", sv, ",".join(sorted(set(where))))] += 1
OUT["dpo_delta"] = {" | ".join(k): v for k, v in dd.items()}
print("### DPO greedy: candidates counted differently (strict vs saved summary)\n")
print(md(["corpus", "direction", "screen verdict", "verify dirs holding pass", "n"],
         [list(k) + [v] for k, v in sorted(dd.items())]))

# strict-policy screen verdict breakdown of reference matches without pass verdict
nopass_em = Counter()
for tag in MODELS:
    for sk, g in greedy[tag].items():
        if g["_em"] and g["_sav"] > 0 and not g["_ok"]:
            nopass_em[tag] += 1
OUT["refmatch_shorter_without_pass"] = dict(nopass_em)
print(f"Greedy reference-matching, shorter candidates lacking a pass verdict: {dict(nopass_em)}\n")

# ------------------------------------------------------------- 2. families
fam_rows, famout = [], {}
fams = ["deletion", "tactic_replacement", "lemma_extraction"]
for c in CORPORA:
    for f in fams:
        sk_cf = [sk for sk in sites if sk[0] == c and sites[sk]["_fam"] == f]
        if not sk_cf:
            continue
        row = [c, f, len(sk_cf)]
        for tag in MODELS:
            k = sum(greedy[tag][sk]["_ok"] for sk in sk_cf)
            sv = sum(greedy[tag][sk]["_sav"] for sk in sk_cf if greedy[tag][sk]["_ok"])
            famout[f"{c}/{f}/{tag}"] = (k, len(sk_cf), sv)
            row.append(f"{k} ({pct(k, len(sk_cf))}; {sv:,} tok)")
        fam_rows.append(row)
# pooled
for f in fams:
    sk_f = [sk for sk in sites if sites[sk]["_fam"] == f]
    row = ["pooled", f, len(sk_f)]
    for tag in MODELS:
        k = sum(greedy[tag][sk]["_ok"] for sk in sk_f)
        row.append(f"{k} ({pct(k, len(sk_f))})")
    fam_rows.append(row)
OUT["families"] = famout
print("## 2. Edit-family breakdown (greedy v+s@1)\n")
print(md(["corpus", "family", "sites"] + list(MODELS), fam_rows))

# control: output "" at every "(no local goal)" site, nothing elsewhere
ctl_rows, ctl = [], {}
for c in CORPORA:
    mk = [sk for sk in sites if sk[0] == c and sites[sk]["_marker"]]
    em = [sk for sk in mk if sites[sk]["reference_replacement"] == ""]
    passed = [sk for sk in mk
              if ckey(dict(sites[sk], replacement="")) in PASS and sites[sk]["_tok_o"] > 0]
    sav = sum(sites[sk]["_tok_o"] for sk in passed)
    n = sum(1 for sk in sites if sk[0] == c)
    ctl[c] = {"marker_sites": len(mk), "delete_matches_reference": len(em),
              "delete_has_pass_verdict": len(passed), "savings_passverified": sav,
              "sites": n}
    ctl_rows.append([c, n, len(mk), len(em), f"{len(passed)} ({pct(len(passed), n)})", f"{sav:,}"])
OUT["delete_control"] = ctl
print("### Trivial control: delete at every `(no local goal)` site\n")
print(md(["corpus", "sites", "marker sites", "delete == reference",
          "delete has saved pass verdict (rate over all sites)", "savings of those"], ctl_rows))

# ------------------------------------------------------------- 3. bootstrap
rng = np.random.default_rng(SEED)
boot = {}


def file_arrays(c, tag):
    files = sorted({sk[1] for sk in sites if sk[0] == c})
    idx = {f: i for i, f in enumerate(files)}
    n = np.zeros(len(files))
    k = np.zeros(len(files))
    for sk, g in greedy[tag].items():
        if sk[0] == c:
            n[idx[sk[1]]] += 1
            k[idx[sk[1]]] += g["_ok"]
    return files, n, k


def boot_weights(nf):
    # multinomial counts of each file in a with-replacement resample of nf files
    return rng.multinomial(nf, np.full(nf, 1.0 / nf), size=NBOOT)


boot_rows, diff_rows = [], []
for c in CORPORA + ["pooled"]:
    cs = CORPORA if c == "pooled" else [c]
    # stratified by corpus for pooled
    W, N, K = [], [], {t: [] for t in ("sft", "sft_qwen", "dpo")}
    for cc in cs:
        files, n, _ = file_arrays(cc, "sft")
        w = boot_weights(len(files))
        W.append(w)
        N.append(n)
        for t in K:
            K[t].append(file_arrays(cc, t)[2])
    W = np.concatenate(W, axis=1)
    N = np.concatenate(N)
    rates = {}
    for t in K:
        kk = np.concatenate(K[t])
        rates[t] = (W @ kk) / (W @ N)
        pt = kk.sum() / N.sum()
        lo, hi = np.percentile(rates[t], [2.5, 97.5])
        boot[f"{c}/{t}"] = (pt, lo, hi)
        boot_rows.append([c, t, pct(int(kk.sum()), int(N.sum())), f"[{100*lo:.1f}, {100*hi:.1f}]"])
    for a, b in (("sft", "sft_qwen"), ("sft", "dpo")):
        kd = np.concatenate(K[a]) - np.concatenate(K[b])
        d = rates[a] - rates[b]
        pt = kd.sum() / N.sum()
        lo, hi = np.percentile(d, [2.5, 97.5])
        p2 = 2 * min((d <= 0).mean(), (d >= 0).mean())
        boot[f"{c}/{a}-{b}"] = (pt, lo, hi, p2)
        diff_rows.append([c, f"{a} - {b}", f"{100*pt:+.1f} pp", f"[{100*lo:+.1f}, {100*hi:+.1f}]",
                          (f"{min(p2, 1.0):.4f}" if p2 > 0 else f"<{1/NBOOT:g}")])
OUT["bootstrap"] = boot
print(f"## 3. File-level bootstrap (resample source files within corpus, {NBOOT} reps, seed {SEED})\n")
print(md(["corpus", "model", "v+s@1", "95% CI"], boot_rows))
print(md(["corpus", "paired difference", "point", "95% CI", "two-sided bootstrap p"], diff_rows))

# ------------------------------------------------------------- 4. EM / novel / beats
em_rows, emout = [], {}
for c in CORPORA:
    sk_c = [sk for sk in sites if sk[0] == c]
    for tag in MODELS:
        g = [greedy[tag][sk] for sk in sk_c]
        em = sum(x["_em"] for x in g)
        emok = sum(x["_em"] and x["_ok"] for x in g)
        nov = sum(x["_ok"] and not x["_em"] for x in g)
        nov4 = sum(any(s["_ok"] and not s["_em"] for s in samples[tag][sk]) for sk in sk_c)
        emout[f"{c}/{tag}"] = (em, emok, nov, nov4, len(sk_c))
        em_rows.append([c, tag, f"{em} ({pct(em, len(sk_c))})", emok,
                        f"{nov} ({pct(nov, len(sk_c))})", f"{nov4} ({pct(nov4, len(sk_c))})"])
OUT["exact_match"] = emout
print("## 4. Exact-match@1 and valid shortenings different from reference\n")
print(md(["corpus", "model", "exact-match@1", "exact-match & pass & shorter",
          "novel v+s@1 (!= ref)", "novel v+s@4 (any sample)"], em_rows))

beats = []
for tag, rows in cands.items():
    for x in rows:
        if x["_ok"] and x["_sav"] > sites[x["_sk"]]["_ref_sav"]:
            beats.append((tag, x["decoding_index"], x["corpus"], x["file"].split("/")[-1],
                          x["start_byte"], x["_sav"], sites[x["_sk"]]["_ref_sav"],
                          x["replacement"][:40].replace("|", "\\|").replace("\n", " ")))
OUT["beats_reference"] = beats
print(f"Candidates (any model, any decoding) pass-verified and saving strictly more than reference: {len(beats)}\n")
if beats:
    print(md(["model", "dec", "corpus", "file", "start", "sav", "ref sav", "replacement"], beats))

# ------------------------------------------------------------- 5. ranker
STAGES = ["rfl", "ring", "abel", "norm_num", "norm_cast", "positivity", "decide", "linarith",
          "omega", "field_simp", "contradiction", "ext", "gcongr", "tauto", "simp?", "exact?"]


def stage(raw):
    t = raw.strip()
    if t.startswith("by "):
        t = t[3:].strip()
    if t.startswith("simp only") or t.startswith("simp?"):
        return STAGES.index("simp?")
    if t.startswith("exact"):
        return STAGES.index("exact?")
    return STAGES.index(t) if t in STAGES else None


rk_rows, rk = [], {}
tot = [0, 0, 0, 0]
for c in CORPORA:
    groups = read_jsonl(EXP / "exp2_ranker" / "data" / f"eval_groups_{c}.jsonl")[0]
    ok = unmapped = ties = multi = 0
    for g in groups:
        st = [stage(x["raw"]) for x in g["candidates"]]
        unmapped += any(s is None for s in st)
        multi += sum(x["is_accepted"] for x in g["candidates"]) != 1
        best = max(s for s in st if s is not None)
        ties += st.count(best) > 1
        pick = st.index(best)
        ok += bool(g["candidates"][pick]["is_accepted"])
    rk[c] = (ok, len(groups), unmapped, ties, multi)
    tot = [a + b for a, b in zip(tot, (ok, len(groups), unmapped, ties))]
    rk_rows.append([c, len(groups), ok, pct(ok, len(groups)), unmapped, ties, multi])
rk_rows.append(["pooled", tot[1], tot[0], pct(tot[0], tot[1]), tot[2], tot[3], ""])
OUT["order_control"] = rk
print("## 5. Search-order-only control (no training)\n")
print(md(["corpus", "groups", "correct top-1", "top-1", "groups w/ unmapped cand", "stage ties",
          "groups w/ !=1 accepted"], rk_rows))

m = json.loads((EXP / "exp2_ranker" / "exp2_metrics.json").read_text())
print(md(["method", "corpus", "groups", "top-1", "pairwise", "MRR"],
         [[meth, c, v[c]["groups"], f"{100*v[c]['top1']:.1f}", f"{100*v[c]['pairwise']:.1f}",
           f"{100*v[c]['mrr']:.1f}"]
          for meth, v in m.items() if isinstance(v, dict) and "pooled" in v
          for c in CORPORA + ["pooled"]]))

# selector table: saved vs strict recomputation
scores = {}
for f in ("selection_scores.jsonl", "selection_scores_frozen.jsonl"):
    for r in read_jsonl(EXP / "exp2_ranker" / f)[0]:
        scores[(f, r["file"], r["start_byte"], r["end_byte"], r["decoding_index"])] = r["score"]
sel_rows, selout = [], {}
for label, tag, sf, jf in (("SFT DeepSeek", "sft", "selection_scores.jsonl", "selection_results.json"),
                           ("frozen DeepSeek", "frozen", "selection_scores_frozen.jsonl",
                            "selection_results_frozen.json")):
    saved = json.loads((EXP / "exp2_ranker" / jf).read_text())
    agg = defaultdict(lambda: defaultdict(float))
    missing = 0
    for sk, g in greedy[tag].items():
        smp = sorted(samples[tag][sk], key=lambda x: x["decoding_index"])
        sv = [x["_sav"] if x["_ok"] else 0 for x in smp]
        for cc in (sk[0], "pooled"):
            a = agg[cc]
            a["greedy"] += g["_sav"] if g["_ok"] else 0
            a["random_of_4"] += sum(sv) / len(sv)
            a["shortest_of_4"] += sv[min(range(len(smp)), key=lambda i: len(smp[i]["replacement"]))]
            sc = [scores.get((sf, x["file"], x["start_byte"], x["end_byte"], x["decoding_index"]))
                  for x in smp]
            if cc == "pooled":
                missing += sum(s is None for s in sc)
            a["ranker_of_4"] += sv[max(range(len(smp)), key=lambda i: sc[i] if sc[i] is not None
                                       else float("-inf"))]
            a["oracle_of_4"] += max(sv)
    selout[label] = {"strict": agg, "saved": saved, "missing_scores": missing}
    for cc in CORPORA + ["pooled"]:
        for pol in ("greedy", "random_of_4", "shortest_of_4", "ranker_of_4", "oracle_of_4"):
            sel_rows.append([label, cc, pol, f"{saved[cc][pol]:,.2f}".rstrip("0").rstrip("."),
                             f"{agg[cc][pol]:,.2f}".rstrip("0").rstrip(".")])
OUT["selection"] = {k: {"strict": {c: dict(v) for c, v in d["strict"].items()},
                        "saved": d["saved"], "missing_scores": d["missing_scores"]}
                    for k, d in selout.items()}
print("### Selector experiment (pooled local savings; saved JSON vs strict recomputation)\n")
print(md(["candidates", "corpus", "policy", "saved", "strict pass-only"], sel_rows))

# ------------------------------------------------------------- 6. integrity table
print("## 6. JSONL integrity\n")
print(md(["file", "records", "unparseable lines", "ends with newline", "bytes"],
         [[a, f"{b:,}", c, d, f"{e:,}"] for a, b, c, d, e in integrity]))

# ------------------------------------------------------------- 7. dataset / exp7
hv = json.loads(HEADLINE_JSON.read_text())
cv = json.loads((EXP / "exp4_corpus_variation" / "corpus_variation.json").read_text())
ds_rows = []
for k, v in cv["corpora"].items():
    fc = v.get("full_corpus") or {}
    ds_rows.append([k, v.get("files_shortened"), v.get("accepted_edits"), v.get("rejected_rows"),
                    f"{fc.get('token_reduction_pct', float('nan')):.2f}" if fc.get("token_reduction_pct") is not None else "n/a",
                    f"{v.get('token_reduction_touched_pct', float('nan')):.2f}",
                    f"{fc.get('accepted_edits_per_1k_tokens', v.get('accepted_edits_per_1k_tokens_touched')):.2f}",
                    v.get("paper_token_reduction_pct", "")])
OUT["dataset"] = {"headline_v4_total": hv["total"],
                  "files_with_savings_sum": sum(v["files_with_savings"] for v in hv["per_corpus"].values())}
print("## 7. Dataset stats (exp4 corpus_variation.json)\n")
print(md(["corpus", "files shortened", "accepted", "rejected", "token red. full %",
          "token red. touched %", "accepted edits /1k tok", "paper %"], ds_rows))
print("headline_v4 total:", hv["total"]["training_pairs"], hv["total"]["rejected_siblings"],
      "files_with_savings sum:", OUT["dataset"]["files_with_savings_sum"])

# arithmetic check of the frontier-prover corpus sums (per-problem saved / original tokens)
seed8 = {"A1": (371, 9105), "A2": (0, 6115), "B1": (0, 12039), "B2": (1702, 27478),
         "B3": (0, 6063), "B4": (230, 8503), "B5": (0, 34371), "B6": (1500, 35816)}
axiom8 = {"A1": (118, 7067), "A2": (72, 5385), "B1": (115, 15590), "B2": (64, 5502),
          "B3": (76, 3552), "B4": (393, 13360), "B5": (128, 16575), "B6": (0, 13076)}
seed11 = dict(seed8, A3=(85, 14345), A4=(378, 14567), A6=(412, 14797))
chk = {}
for name, d in (("seed_matched8", seed8), ("axiom_matched8", axiom8), ("seed_full11", seed11)):
    s, o = sum(v[0] for v in d.values()), sum(v[1] for v in d.values())
    chk[name] = (s, o, 100 * s / o)
OUT["exp7_check"] = chk
print("exp7 sums:", chk)

OUT_JSON.write_text(
    json.dumps(OUT, indent=1, default=str))
