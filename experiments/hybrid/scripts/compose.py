#!/usr/bin/env python3
"""Whole-file composition: apply the best screen-passing (or verified) edit per site,
non-overlapping, to each file; compile with fresh `lake env lean`; if the joint file fails,
find a maximal compiling subset by recursive halving (as leanpolish.py _maximal_sound_subset).

Selection per site: among candidates allowed by --decodings (greedy | all), keep those with
verdict pass in --verdicts (screen rows with screen=='pass' or verify rows with verdict=='pass'),
choose the one with the largest count_appL savings. Across sites: greedy by savings desc,
skipping spans that overlap an already-chosen span.
Outputs <files-root>/<corpus>/<outvariant>/<name>.lean and a JSONL report.
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, json, os, sys, threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from retokenize_appendixL import count_appL
from verify_full import run_lean
from quality_filter import is_quality_upgrade

def apply(src: bytes, edits):
    res, cur = b'', 0
    for e in sorted(edits, key=lambda x: x['start_byte']):
        res += src[cur:e['start_byte']] + e['replacement'].encode(); cur = e['end_byte']
    return res + src[cur:]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', nargs='+', required=True)
    ap.add_argument('--gens', nargs='+', required=True)
    ap.add_argument('--verdicts', nargs='+', required=True)
    ap.add_argument('--decodings', choices=['greedy', 'all'], default='all')
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--variant', default='base')
    ap.add_argument('--outvariant', required=True)
    ap.add_argument('--files-root', default=_os.environ.get('FILES_ROOT', 'files'))
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--jobs', type=int, default=24)
    ap.add_argument('--timeout', type=float, default=1800)
    ap.add_argument('--report', required=True)
    ap.add_argument('--quality-filter', action='store_true',
                    help='only non-deletion edits passing the ported isQualityUpgrade (deletions allowed)')
    args = ap.parse_args()
    sites = {}
    for p in args.sites:
        for l in open(p):
            s = json.loads(l)
            if s['corpus'] == args.corpus and s['variant'] == args.variant:
                sites[s['site_id']] = s
    allowed = defaultdict(set)
    for p in args.gens:
        for l in open(p):
            g = json.loads(l)
            if g['site_id'] not in sites: continue
            allowed[g['site_id']].add(g['greedy'])
            if args.decodings == 'all':
                allowed[g['site_id']].update(g.get('samples', []))
    passing = defaultdict(set)
    for p in args.verdicts:
        for l in open(p):
            v = json.loads(l)
            if v.get('screen') == 'pass' or v.get('verdict') == 'pass':
                passing[v['site_id']].add(v['replacement'])
    by_file = defaultdict(list)
    for sid, s in sites.items():
        best = None
        for c in passing.get(sid, set()) & allowed.get(sid, set()):
            sav = count_appL(s['original']) - count_appL(c)
            if args.quality_filter and c.strip() != '' and not is_quality_upgrade(s['original'], c): continue
            if sav > 0 and (best is None or sav > best[0]): best = (sav, c)
        if best:
            by_file[s['file']].append({'site_id': sid, 'start_byte': s['start_byte'], 'end_byte': s['end_byte'],
                                       'original': s['original'], 'replacement': best[1], 'savings': best[0]})
    outdir = Path(args.files_root) / args.corpus / args.outvariant
    outdir.mkdir(parents=True, exist_ok=True)
    rep = open(args.report, 'w'); lock = threading.Lock()
    files = sorted((Path(args.files_root) / args.corpus / args.variant).glob('*.lean'))
    def ok(src, edits, name):
        tmp = outdir / f'.compose_{os.getpid()}_{threading.get_ident()}_{name}'
        tmp.write_bytes(apply(src, edits))
        try:
            r = run_lean(tmp, args.project, args.timeout)
        finally:
            tmp.unlink(missing_ok=True)
        return (not r.get('timeout')) and r.get('exit_code') == 0 and not r.get('errors') and not r.get('has_sorry')
    def job(f):
        rel = f'{args.corpus}/{args.variant}/{f.name}'
        src = f.read_bytes()
        cands = sorted(by_file.get(rel, []), key=lambda e: (-e['savings'], e['start_byte']))
        chosen = []
        for e in cands:
            if all(e['end_byte'] <= c['start_byte'] or e['start_byte'] >= c['end_byte'] for c in chosen):
                chosen.append(e)
        ncompiles = 0
        base_ok = ok(src, [], f.name); ncompiles += 1
        final = []
        if chosen and base_ok:
            def maximal(acc, cs):
                nonlocal ncompiles
                if not cs: return acc
                ncompiles += 1
                if ok(src, acc + cs, f.name): return acc + cs
                if len(cs) == 1: return acc
                h = len(cs) // 2
                acc = maximal(acc, cs[:h])
                return maximal(acc, cs[h:])
            final = maximal([], chosen)
        out = apply(src, final)
        (outdir / f.name).write_bytes(out)
        rec = {'file': rel, 'base_compiles': base_ok, 'n_candidates_sites': len(cands), 'n_chosen': len(chosen),
               'n_applied': len(final), 'compiles': ncompiles,
               'tokens_base': count_appL(src.decode()), 'tokens_out': count_appL(out.decode()),
               'edits': final}
        with lock:
            rep.write(json.dumps(rec, ensure_ascii=False) + '\n'); rep.flush()
            print(rel, {k: rec[k] for k in ('base_compiles', 'n_chosen', 'n_applied', 'compiles', 'tokens_base', 'tokens_out')}, flush=True)
    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(job, files))
    print('COMPOSE_DONE', flush=True)

if __name__ == '__main__':
    main()
