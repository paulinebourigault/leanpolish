#!/usr/bin/env python3
"""Aggregate corpus-level byte, token, and line reductions.

The script combines existing LeanPolish report trees into one headline JSON
using full-corpus denominators. It expects each corpus directory to contain the
standard ``optimization_report.json`` and per-file ``*_report.json`` files.
Environment: CORPUS_ROOT (run directory, default "."). Output path: first CLI argument.
"""
import json, os, sys
ROOT=os.environ.get("CORPUS_ROOT",".")  # LeanPolish run directory holding the corpus report trees
CORPORA=[
  ("mathlib","mathlib_optimization"),
  ("goedel","goedel_optimization"),
  ("putnam_bench","putnam_bench_proofs"),
  ("putnam2025","Putnam2025_AxiomProver"),
]
out={"per_corpus":{}}
print(f"{'corpus':<14} {'files':>6} {'shorter':>7} {'B_orig':>11} {'B_save':>9} {'B%':>6} {'T_orig':>11} {'T_save':>9} {'T%':>6} {'L_orig':>9} {'L_save':>8} {'L%':>6} {'pairs':>6} {'repl':>6} {'dc':>5}")
TOT={k:0 for k in "files shorter Bo Bs To Ts Lo Ls pairs repl dcrm".split()}
for label, sub in CORPORA:
    rep=os.path.join(ROOT,sub,"optimization_report.json")
    if not os.path.exists(rep):
        print(f"# missing: {rep}", file=sys.stderr); continue
    d=json.load(open(rep))
    files_lst=d.get("files",[])
    n=d.get("total_files",len(files_lst))
    bsave=d.get("total_bytes_saved",0)
    repl=d.get("total_replacements",0); dcrm=d.get("total_dead_code_removed",0)
    pairs=d.get("total_training_pairs",0)
    ns=sum(1 for f in files_lst if f.get("bytes_saved",0)>0)
    bo=to=lo=0
    tsave=lsave=0  # sum from per-file reports; optimization_report totals are incomplete
                   # for some corpora (putnam_bench omits the keys; putnam2025 records 0).
    for f in files_lst:
        fp=f["file"]
        bo_f=f.get("bytes_original")
        if bo_f is None:
            try: bo_f=os.path.getsize(fp)
            except: bo_f=0
        bo += bo_f or 0
        # Try `<file>_report.json` first; fall back to `<dir>/problem_report.json`
        # (Putnam2025_AxiomProver/A1/problem.lean -> A1/problem_report.json).
        per=os.path.splitext(fp)[0]+"_report.json"
        if not os.path.exists(per):
            alt=os.path.join(os.path.dirname(fp),"problem_report.json")
            if os.path.exists(alt): per=alt
        if os.path.exists(per):
            try:
                pd=json.load(open(per))
                to += pd.get("tokens_original",0) or 0
                lo += pd.get("lines_original",0) or 0
                tsave += pd.get("tokens_saved",0) or 0
                lsave += pd.get("lines_saved",0) or 0
            except: pass
    bp=bsave/bo*100 if bo else 0
    tp=tsave/to*100 if to else 0
    lp=lsave/lo*100 if lo else 0
    out["per_corpus"][label]=dict(files=n,files_shorter=ns,
      bytes_original=bo,bytes_saved=bsave,bytes_pct=bp,
      tokens_original=to,tokens_saved=tsave,tokens_pct=tp,
      lines_original=lo,lines_saved=lsave,lines_pct=lp,
      training_pairs=pairs,tactic_replacements=repl,dead_code_removed=dcrm)
    print(f"{label:<14} {n:>6} {ns:>7} {bo:>11} {bsave:>9} {bp:>6.2f} {to:>11} {tsave:>9} {tp:>6.2f} {lo:>9} {lsave:>8} {lp:>6.2f} {pairs:>6} {repl:>6} {dcrm:>5}")
    TOT["files"]+=n; TOT["shorter"]+=ns; TOT["Bo"]+=bo; TOT["Bs"]+=bsave
    TOT["To"]+=to; TOT["Ts"]+=tsave; TOT["Lo"]+=lo; TOT["Ls"]+=lsave
    TOT["pairs"]+=pairs; TOT["repl"]+=repl; TOT["dcrm"]+=dcrm
bp=TOT["Bs"]/TOT["Bo"]*100 if TOT["Bo"] else 0
tp=TOT["Ts"]/TOT["To"]*100 if TOT["To"] else 0
lp=TOT["Ls"]/TOT["Lo"]*100 if TOT["Lo"] else 0
out["total"]=dict(files=TOT["files"],files_shorter=TOT["shorter"],
  bytes_original=TOT["Bo"],bytes_saved=TOT["Bs"],bytes_pct=bp,
  tokens_original=TOT["To"],tokens_saved=TOT["Ts"],tokens_pct=tp,
  lines_original=TOT["Lo"],lines_saved=TOT["Ls"],lines_pct=lp,
  training_pairs=TOT["pairs"],tactic_replacements=TOT["repl"],dead_code_removed=TOT["dcrm"])
print(f"{'TOTAL':<14} {TOT['files']:>6} {TOT['shorter']:>7} {TOT['Bo']:>11} {TOT['Bs']:>9} {bp:>6.2f} {TOT['To']:>11} {TOT['Ts']:>9} {tp:>6.2f} {TOT['Lo']:>9} {TOT['Ls']:>8} {lp:>6.2f} {TOT['pairs']:>6} {TOT['repl']:>6} {TOT['dcrm']:>5}")
outpath=os.path.join(os.path.dirname(os.path.abspath(__file__)),"headline_v3.json")
json.dump(out, open(outpath,"w"), indent=2)
print(f"# wrote {outpath}", file=sys.stderr)
