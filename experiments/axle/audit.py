#!/usr/bin/env python3
"""Soundness audit of every final file in the AXLE / LeanPolish comparison.

For each condition and file whose final text differs from the original:
  1. statement gate: every theorem/lemma of the original is present with the same name and a
     whitespace-normalised identical statement (keyword up to the first `:=`), and no theorem is added;
  2. forbidden tokens: no new sorry/admit/axiom/native_decide/implemented_by/extern/unsafe;
  3. fresh process: `lake env lean` on the file with `#print axioms <name>` appended for every
     theorem; pass iff rc 0, no error, no `sorry`, and every printed axiom is in
     {propext, Classical.choice, Quot.sound}.
Writes results/audit.json.
Usage: REPLICATION_DATA=<unpacked replication tarball> python3 audit.py [jobs]
  LEAN_PROJECT: Lake project used for the checks (default: <repository>/leanpolish)
"""
import concurrent.futures as cf, json, os, re, subprocess, sys, tempfile
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1]))
DATA = Path(os.environ['REPLICATION_DATA'])
LP = str(os.environ.get('LEAN_PROJECT', ROOT / 'leanpolish'))
PB = [Path(l.strip()).stem for l in open(ROOT / 'experiments/metrics/file_lists/putnam_verified.txt') if l.strip()]
SETS = {'minif2f': (DATA / 'inputs/minif2f', lambda n: not n.endswith('_linter')),
        'putnam_verified': (DATA / 'inputs/putnam_verified', lambda n: n in PB),
        'putnam2025': (DATA / 'inputs/putnam2025', lambda n: True)}
CONDS = {'AXLE': DATA / 'axle/outputs/original', 'LP_fixed_point': DATA / 'lp_fixed_point',
         'LP_fp_then_AXLE': DATA / 'axle/outputs/lp_fixed_point', 'AXLE_then_LP_fp': DATA / 'axle/then_leanpolish'}
DECL = re.compile(r'^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec)\s+)*(theorem|lemma)\s+([^\s(:{\[⦃]+)', re.M)
FORBID = ('sorry', 'admit', 'axiom', 'native_decide', 'implemented_by', 'extern', 'unsafe')
OK_AX = {'propext', 'Classical.choice', 'Quot.sound'}


def strip_comments(t):
    t = re.sub(r'/-.*?-/', '', t, flags=re.S)
    return re.sub(r'--[^\n]*', '', t)


def statements(t):
    t = strip_comments(t); out = {}
    for m in DECL.finditer(t):
        j = t.find(':=', m.end())
        out[m.group(2)] = ' '.join(t[m.start():j].split())
    return out


def final_path(cond, corpus, name):
    return CONDS[cond] / corpus / f'{name}.lean'


def audit(job):
    cond, corpus, name, orig = job
    p = final_path(cond, corpus, name)
    if not p.exists():
        return job[:3], {'status': 'no_output (input kept)'}
    t = p.read_text()
    if t.strip() == orig.strip():
        return job[:3], {'status': 'unchanged'}
    so, sn = statements(orig), statements(t)
    if so != sn:
        return job[:3], {'status': 'STATEMENT_MISMATCH', 'missing': sorted(set(so) - set(sn)), 'diff': sorted(k for k in so if k in sn and so[k] != sn[k])}
    co, cn = strip_comments(orig), strip_comments(t)
    for w in FORBID:
        if len(re.findall(rf'\b{w}\b', cn)) > len(re.findall(rf'\b{w}\b', co)):
            return job[:3], {'status': f'FORBIDDEN:{w}'}
    src = t + '\n' + ''.join(f'\n#print axioms {n}' for n in sn)
    with tempfile.NamedTemporaryFile('w', suffix='.lean', dir='/tmp', delete=False) as f:
        f.write(src); tmp = f.name
    try:
        r = subprocess.run(['lake', 'env', 'lean', tmp], cwd=LP, capture_output=True, text=True, timeout=3000)
        out = r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return job[:3], {'status': 'TIMEOUT'}
    finally:
        Path(tmp).unlink(missing_ok=True)
    axioms = set(re.findall(r"depends on axioms: \[([^\]]*)\]", out))
    used = {a.strip() for s in axioms for a in s.split(',') if a.strip()}
    n_print = out.count('depends on axioms') + out.count('does not depend on any axioms')
    ok = r.returncode == 0 and not re.search(r'\berror\b', out) and 'sorry' not in out and used <= OK_AX and n_print == len(sn)
    return job[:3], {'status': 'PASS' if ok else 'FAIL', 'axioms': sorted(used), 'n_theorems': len(sn), 'tail': '' if ok else out[-400:]}


def main():
    jobs = []
    for corpus, (od, keep) in SETS.items():
        for f in sorted(od.glob('*.lean')):
            if not keep(f.stem): continue
            for cond in CONDS:
                if cond == 'AXLE_then_LP_fp' and corpus == 'putnam2025': continue
                jobs.append((cond, corpus, f.stem, f.read_text()))
    res = {}
    with cf.ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 4) as ex:
        for k, v in ex.map(audit, jobs):
            res['|'.join(k)] = v; print(*k, v['status'], flush=True)
    (HERE / 'results').mkdir(exist_ok=True)
    json.dump(res, open(HERE / 'results' / 'audit.json', 'w'), indent=1)
    import collections
    print(collections.Counter((k.split('|')[0], v['status']) for k, v in res.items()))


if __name__ == '__main__':
    main()
