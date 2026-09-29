#!/usr/bin/env python3
"""Joint application of individually verified neural edits on the teacher-shortened files.

Lanes: sampling budget {g4: greedy + first 4 of the T=0.6 samples, g16: greedy + 16 samples}
x {raw, filt: edit passes the Python port of LeanPolish's isQualityUpgrade; deletions are
not tactic substitutions and pass}. Per lane and file: among individually `pass`
candidates, pick the best (max appL savings) per site, resolve overlapping sites greedily by
savings, apply all jointly to the base file, fresh `lake env lean` (no error, no sorry);
on failure, leanpolish.py's _maximal_sound_subset bisect (same fresh-kernel oracle).
The final file of every lane is re-verified once more (the bisect already verified it; this
is the written artifact). Writes final/<lane>/<corpus>/<name>.lean and combine.json.
"""
import argparse, json, os, re, subprocess, sys, threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
_HERE = Path(__file__).resolve().parent
_ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
# local variants first, then shared hybrid scripts, then the shared token counters
sys.path[:0] = [str(_HERE), str(_ROOT / 'experiments' / 'hybrid' / 'scripts'), str(_ROOT / 'leanpolish')]
LEAN_PROJECT = os.environ.get('LEAN_PROJECT', str(_ROOT / 'leanpolish'))
WORK_DIR = os.environ.get('WORK_DIR', 'work')
REPL_BIN = os.environ.get('REPL_BIN', 'repl')
from retokenize_appendixL import count_appL
from quality_filter import is_quality_upgrade

ERR = re.compile(r":\d+:\d+:\s*error", re.M)
SORRY = re.compile(r"declaration uses 'sorry'")


def compile_ok(text, like: Path, project, timeout):
    tmp = like.with_name(f'.combine_{os.getpid()}_{threading.get_ident()}_{like.name}')
    tmp.write_text(text)
    try:
        p = subprocess.run(['lake', 'env', 'lean', str(tmp.resolve())], cwd=project,
                           capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or '') + (p.stderr or '')
        return p.returncode == 0 and not ERR.search(out) and not SORRY.search(out)
    except subprocess.TimeoutExpired:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def apply_edits(text, edits):
    data = text.encode()
    for e in sorted(edits, key=lambda e: -e['start_byte']):
        data = data[:e['start_byte']] + e['replacement'].encode() + data[e['end_byte']:]
    return data.decode()


def maximal_sound_subset(text, edits, ok):
    # identical algorithm to leanpolish.py::_maximal_sound_subset
    if not edits:
        return []
    if ok(apply_edits(text, edits)):
        return list(edits)
    if len(edits) == 1:
        return []
    mid = len(edits) // 2
    left = maximal_sound_subset(text, edits[:mid], ok)
    right = maximal_sound_subset(text, edits[mid:], ok)
    if left and right and ok(apply_edits(text, left + right)):
        return left + right
    return left if sum(e['savings'] for e in left) >= sum(e['savings'] for e in right) else right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', required=True)
    ap.add_argument('--gens', required=True)
    ap.add_argument('--verdicts', required=True)
    ap.add_argument('--teacher-edits', default=os.path.join(WORK_DIR, 'teacher_edits.json'))
    ap.add_argument('--files-root', default=os.path.join(WORK_DIR, 'files'))
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--final-root', default=os.path.join(WORK_DIR, 'final'))
    ap.add_argument('--timeout', type=int, default=3600)
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    sites = {json.loads(l)['site_id']: json.loads(l) for l in open(args.sites)}
    budget = {}  # (site_id, cand) -> 'g4' if reachable within greedy+4 else 'g16'
    for l in open(args.gens):
        g = json.loads(l)
        for i, c in enumerate([g['greedy']] + g.get('samples', [])):
            k = (g['site_id'], c)
            b = 'g4' if i <= 4 else 'g16'
            if budget.get(k) != 'g4':
                budget[k] = b
    verd = {}
    for l in open(args.verdicts):
        r = json.loads(l)
        verd[(r['site_id'], r['replacement'])] = r['verdict']
    te = json.load(open(args.teacher_edits))
    passed = defaultdict(list)  # file -> edits
    for (sid, cand), v in verd.items():
        if v != 'pass' or sid not in sites:
            continue
        s = sites[sid]
        passed[s['file']].append({
            'site_id': sid, 'file': s['file'], 'start_byte': s['start_byte'], 'end_byte': s['end_byte'],
            'original': s['original'], 'replacement': cand, 'goal': s['goal'],
            'savings': count_appL(s['original']) - count_appL(cand),
            'budget': budget.get((sid, cand), 'g16'),
            'quality_ok': (cand.strip() == '') or is_quality_upgrade(s['original'], cand),
            'deletion': cand.strip() == ''})
    lanes = [('g4', 'raw'), ('g4', 'filt'), ('g16', 'raw'), ('g16', 'filt')]
    jobs = []
    for key, info in te.items():
        if args.only and key not in args.only:
            continue
        corpus, name = key.split('/')
        fkey = f'{corpus}/base/{name}.lean'
        for lane in lanes:
            jobs.append((key, fkey, lane))
    results = {}

    def job(x):
        key, fkey, (bud, flt) = x
        base = Path(args.files_root, fkey)
        text = base.read_text()
        cands = [e for e in passed.get(fkey, []) if (bud == 'g16' or e['budget'] == 'g4')
                 and (flt == 'raw' or e['quality_ok'])]
        best = {}
        for e in cands:
            if e['site_id'] not in best or e['savings'] > best[e['site_id']]['savings']:
                best[e['site_id']] = e
        chosen = []
        for e in sorted(best.values(), key=lambda e: (-e['savings'], e['start_byte'])):
            if all(e['end_byte'] <= c['start_byte'] or c['end_byte'] <= e['start_byte'] for c in chosen):
                chosen.append(e)
        chosen.sort(key=lambda e: e['start_byte'])
        ok = lambda t: compile_ok(t, base, args.project, args.timeout)
        kept = maximal_sound_subset(text, chosen, ok) if chosen else []
        final = apply_edits(text, kept)
        final_ok = ok(final) if kept else True
        if not final_ok:
            kept, final = [], text
        lane = f'{bud}_{flt}'
        outp = Path(args.final_root, lane, key + '.lean')
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(final)
        return key, lane, {'n_individually_verified_edits': len(cands),
                           'n_sites_with_verified_edit': len(best), 'n_nonoverlapping': len(chosen),
                           'n_kept_joint': len(kept), 'appL_final': count_appL(final),
                           'final_verified': final_ok, 'kept': kept}

    with ThreadPoolExecutor(len(jobs)) as ex:
        for key, lane, r in ex.map(job, jobs):
            results.setdefault(key, {})[lane] = r
            print(key, lane, {k: v for k, v in r.items() if k != 'kept'}, flush=True)
    json.dump({'results': results, 'all_passed': {k: v for k, v in passed.items()}},
              open(args.out, 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
