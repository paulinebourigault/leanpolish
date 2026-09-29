#!/usr/bin/env python3
"""Run the standard LeanPolish (LeanPolish.lean binary + leanpolish.py in $LEAN_PROJECT, single-file mode,
as in the frontier runs) on a set of input files, concurrently.

For each input <src> (a composed output of another condition) we copy it to
<workdir>/<name>.lean inside the lake project, run
    python3 leanpolish.py <workdir>/<name>.lean --timeout T
and take <name>_shortened.lean if leanpolish.py produced one (it only keeps a shortened file
after its own fresh `lake env lean` post-verification), else the input unchanged.
Final files go to <outdir>/<name>.lean; one JSON row per file to --report with wall time,
LeanPolish candidate checks (accepted+rejected training pairs = in-process elaborations),
and appL tokens before/after.
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from retokenize_appendixL import count_appL  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inputs', nargs='+', required=True)
    ap.add_argument('--workdir', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--report', required=True)
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--timeout', type=int, default=7200)
    ap.add_argument('--jobs', type=int, default=24)
    args = ap.parse_args()
    wd, od = Path(args.workdir).resolve(), Path(args.outdir)
    wd.mkdir(parents=True, exist_ok=True); od.mkdir(parents=True, exist_ok=True)
    done = set()
    if os.path.exists(args.report):
        done = {json.loads(l)['name'] for l in open(args.report)}
    fo = open(args.report, 'a')
    env = dict(os.environ)

    def job(src):
        src = Path(src); name = src.name
        if name in done: return
        dst = wd / name
        shutil.copy(src, dst)
        for x in (wd / (dst.stem + '_shortened.lean'), wd / (dst.stem + '_report.json')):
            x.unlink(missing_ok=True)
        t0 = time.time()
        try:
            p = subprocess.run(['python3', 'leanpolish.py', str(dst), '--timeout', str(args.timeout)],
                               cwd=args.project, capture_output=True, text=True, env=env,
                               timeout=args.timeout + 1800)
            rc, tail = p.returncode, (p.stdout or '')[-1500:]
        except subprocess.TimeoutExpired:
            rc, tail = 'driver_timeout', ''
        wall = time.time() - t0
        sh = wd / (dst.stem + '_shortened.lean')
        rep = wd / (dst.stem + '_report.json')
        r = json.load(open(rep)) if rep.exists() else {}
        final = sh if sh.exists() else dst
        shutil.copy(final, od / name)
        tin, tout = count_appL(src.read_text()), count_appL(final.read_text())
        pairs = r.get('training_pairs', [])
        row = {'name': name, 'src': str(src), 'rc': rc, 'wall_s': round(wall, 1), 'shortened': sh.exists(),
               'verified': r.get('verified'), 'tokens_in': tin, 'tokens_out': tout,
               'lp_candidate_checks': len(pairs),
               'lp_accepted': sum(1 for q in pairs if q.get('outcome') == 'accepted'),
               'log_tail': tail[-600:]}
        fo.write(json.dumps(row) + '\n'); fo.flush()
        print(time.strftime('%H:%M:%S'), name, rc, f'{wall:.0f}s', tin, '->', tout, flush=True)

    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(job, args.inputs))
    print('LP_DONE', flush=True)


if __name__ == '__main__':
    main()
