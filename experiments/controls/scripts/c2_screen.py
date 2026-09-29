#!/usr/bin/env python3
"""CPU-budgeted screen for C2 whole-proof candidates (declaration-splice lane of the hybrid's
screen_sites.py; FileEnv is imported unchanged from experiments/hybrid/scripts/screen_sites.py).

One REPL per work unit boots the file once (chunk-by-chunk with env chaining) and then
re-elaborates the declaration with each candidate spliced in.

--early-stop (reduces CPU cost): per unit, candidates are tried in order of decreasing
appL savings and testing stops as soon as the selections compose.py makes for both k=16 (best
passing candidate among all 16 samples) and k=4 (best passing among the first 4 samples) are
determined. The compose selections are therefore identical to exhaustive screening; only the
"fraction of rewrites that fail" statistic is then computed on the tested subset (flagged in the
output rows by exhaustive=false).
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, json, os, sys, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from screen_sites import FileEnv  # noqa: E402
from retokenize_appendixL import count_appL  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', required=True)
    ap.add_argument('--gens', required=True, help='k16 gens (greedy = sample 0, samples = 1..15)')
    ap.add_argument('--files-root', required=True)
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--repl', default=REPL_BIN)
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--split', type=int, default=1, help='work units per file')
    ap.add_argument('--early-stop', action='store_true')
    ap.add_argument('--decl-timeout', type=float, default=900)
    ap.add_argument('--tac-timeout', type=float, default=60)
    ap.add_argument('--file-timeout', type=float, default=5400)
    args = ap.parse_args()
    sites = {json.loads(l)['site_id']: json.loads(l) for l in open(args.sites)}
    gens = {}
    for l in open(args.gens):
        g = json.loads(l)
        if g['site_id'] in sites:
            gens[g['site_id']] = [g['greedy']] + g.get('samples', [])
    done = set()
    if os.path.exists(args.out):
        done = {json.loads(l)['site_id'] for l in open(args.out)}
    by_file = defaultdict(list)
    for sid, s in sites.items():
        if sid in gens and sid not in done:
            by_file[s['file']].append(s)
    units = []
    for f, ss in by_file.items():
        ss.sort(key=lambda x: x['start_byte'])
        for j in range(args.split):
            if ss[j::args.split]: units.append((f, ss[j::args.split]))
    units.sort(key=lambda u: -os.path.getsize(os.path.join(args.files_root, u[0])))
    print(f'[c2screen] files={len(by_file)} units={len(units)} sites={sum(len(v) for v in by_file.values())}', flush=True)
    lock = threading.Lock(); fo = open(args.out, 'a')

    def job(u):
        f, ss = u; t0 = time.time(); rows = []
        try:
            fe = FileEnv(os.path.join(args.files_root, f), args)
        except Exception as ex:
            for st in ss:
                rows.append({'site_id': st['site_id'], 'replacement': None, 'screen': 'file_boot_fail', 'err': repr(ex)[:200]})
            fe = None
        if fe is not None:
            for st in ss:
                o = st['original']; to = count_appL(o)
                samp = gens[st['site_id']]
                first = {}
                for i, c in enumerate(samp):
                    first.setdefault(c, i)
                cands = [c for c in first if c.strip() != o.strip() and count_appL(c) < to]
                cands.sort(key=lambda c: (count_appL(c), first[c]))   # most savings first
                i = fe.chunk_of(st['start_byte'], st['end_byte'])
                best16 = best4 = None
                for c in cands:
                    if args.early_stop and best16 is not None and (best4 is not None or first[c] >= 4):
                        continue
                    if i is None: v = 'no_chunk'
                    elif not fe.chunk_ok[i]: v = 'chunk_baseline_fail'
                    else:
                        try: v = fe.try_splice(i, st['start_byte'], st['end_byte'], c)
                        except Exception: v = 'error'
                    rows.append({'site_id': st['site_id'], 'replacement': c, 'screen': v, 'how': 'decl',
                                 'sample_index': first[c], 'exhaustive': not args.early_stop})
                    if v == 'pass':
                        if best16 is None: best16 = c
                        if best4 is None and first[c] < 4: best4 = c
                if not cands:
                    rows.append({'site_id': st['site_id'], 'replacement': None, 'screen': 'no_shorter_candidate'})
            fe.close()
        with lock:
            for r in rows: fo.write(json.dumps(r, ensure_ascii=False) + '\n')
            fo.flush()
            print(time.strftime('%H:%M:%S'), f, len(ss), 'units', sum(r['screen'] == 'pass' for r in rows), 'pass',
                  len(rows), 'rows', f'{time.time()-t0:.0f}s', flush=True)

    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(job, units))
    print('SCREEN_DONE', flush=True)


if __name__ == '__main__':
    main()
