#!/usr/bin/env python3
"""Extract neural-editor sites on the teacher-shortened (base) files.

Reuses ../hybrid/scripts/extract_sites.py (REPL allTactics; same site criteria and exactly the
SFT prompt template), then drops sites overlapping any region LeanPolish changed
(teacher_edits.json), i.e. keeps only tactic sites LeanPolish left untouched.
"""
import argparse, json, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import os
_HERE = Path(__file__).resolve().parent
_ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
# local variants first, then shared hybrid scripts, then the shared token counters
sys.path[:0] = [str(_HERE), str(_ROOT / 'experiments' / 'hybrid' / 'scripts'), str(_ROOT / 'leanpolish')]
LEAN_PROJECT = os.environ.get('LEAN_PROJECT', str(_ROOT / 'leanpolish'))
WORK_DIR = os.environ.get('WORK_DIR', 'work')
REPL_BIN = os.environ.get('REPL_BIN', 'repl')
import extract_sites as ES


def touches(s, e, regions):
    for j1, j2, tag in regions:
        if j2 > j1:
            if s < j2 and j1 < e:
                return True
        elif s < j1 < e:          # deletion point strictly inside the site
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--files-root', default=os.path.join(WORK_DIR, 'files'))
    ap.add_argument('--teacher-edits', default=os.path.join(WORK_DIR, 'teacher_edits.json'))
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--repl', default=REPL_BIN)
    ap.add_argument('--raw-dir', default=os.path.join(WORK_DIR, 'repl_raw'))
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    te = json.load(open(args.teacher_edits))
    pending = []
    for key in te:
        corpus, name = key.split('/')
        if args.only and name not in args.only and key not in args.only:
            continue
        pending.append((corpus, Path(args.files_root, corpus, 'base', name + '.lean')))

    def job(x):
        corpus, f = x
        try:
            return corpus, f, ES.sites_for(f, corpus, 'base', args)
        except Exception as ex:
            return corpus, f, ([], {'error': repr(ex)[:300]}, -1)

    allsites, summary = [], {}
    with ThreadPoolExecutor(args.jobs) as ex:
        for corpus, f, (sites, stats, nerr) in ex.map(job, pending):
            regions = te[f'{corpus}/{f.stem}']['base_regions']
            kept = [s for s in sites if not touches(s['start_byte'], s['end_byte'], regions)]
            stats['file_errors'] = nerr
            stats['teacher_touched_excluded'] = len(sites) - len(kept)
            stats['kept_untouched'] = len(kept)
            summary[f'{corpus}/{f.stem}'] = stats
            allsites.extend(kept)
            print(corpus, f.stem, stats, flush=True)
    with open(args.out, 'w') as fo:
        for s in allsites:
            fo.write(json.dumps(s, ensure_ascii=False) + '\n')
    json.dump(summary, open(args.out + '.summary.json', 'w'), indent=1)
    print('TOTAL sites', len(allsites))


if __name__ == '__main__':
    main()
