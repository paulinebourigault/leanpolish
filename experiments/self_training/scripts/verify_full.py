#!/usr/bin/env python3
"""Final verification (verify_pair.py logic): splice replacement into the file at
[start_byte,end_byte) after checking the original bytes match, write the spliced file next
to the source, run a fresh `lake env lean`, verdict pass iff exit 0, no error lines and no
NEW sorry vs the baseline (baseline = unmodified file, must compile cleanly).
Input: jsonl rows with site_id, file (relative to --files-root), start_byte, end_byte,
original, replacement. Resumable (keyed by sha1(site_id+replacement)).
"""
import argparse, hashlib, json, os, re, subprocess, time, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ERROR_LINE_RE = re.compile(r"^[^:]+:\d+:\d+:\s*error:\s*(.+)$", re.MULTILINE)
SORRY_RE = re.compile(r"\b(sorry|sorryAx)\b")

def run_lean(path, project, timeout):
    rel = os.path.relpath(path, project); t0 = time.monotonic()
    try:
        p = subprocess.Popen(['lake', 'env', 'lean', rel], cwd=project, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
        so, se = p.communicate(timeout=timeout)
        p.stdout, p.stderr = so, se
    except subprocess.TimeoutExpired:
        try: os.killpg(p.pid, 9)  # also kill the lean child
        except Exception: pass
        p.communicate()
        return {'timeout': True, 'wall_ms': int(1000 * (time.monotonic() - t0))}
    out = (p.stdout or '') + '\n' + (p.stderr or '')
    return {'timeout': False, 'exit_code': p.returncode, 'errors': ERROR_LINE_RE.findall(out),
            'has_sorry': bool(SORRY_RE.search(out)), 'wall_ms': int(1000 * (time.monotonic() - t0))}

def key(r):
    return hashlib.sha1((r['site_id'] + '\x00' + r['replacement']).encode()).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--inp', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--files-root', default=os.environ.get('FILES_ROOT', 'files'))
    ap.add_argument('--project', default=os.environ.get('LEAN_PROJECT', os.path.join(os.environ.get('LEANPOLISH_ROOT', os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))), 'leanpolish')))
    ap.add_argument('--jobs', type=int, default=30)
    ap.add_argument('--timeout', type=float, default=900)
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.inp)]
    done = set()
    if os.path.exists(args.out):
        done = {json.loads(l)['key'] for l in open(args.out)}
    pending = [r for r in rows if key(r) not in done]
    print(f'[verify] {len(rows)} rows, {len(pending)} pending', flush=True)
    base_cache, base_lock = {}, {}
    glock = threading.Lock()
    def baseline(src):
        with glock:
            lk = base_lock.setdefault(src, threading.Lock())
        with lk:
            if src not in base_cache:
                base_cache[src] = run_lean(src, args.project, args.timeout)
            return base_cache[src]
    fo = open(args.out, 'a'); cnt = {}
    def job(r):
        src = Path(args.files_root) / r['file']
        b = src.read_bytes()
        out = {'key': key(r), 'site_id': r['site_id'], 'replacement': r['replacement']}
        if b[r['start_byte']:r['end_byte']].decode('utf-8', errors='replace') != r['original']:
            out['verdict'] = 'splice_mismatch'
        else:
            br = baseline(src)
            if br.get('timeout') or br.get('exit_code') != 0 or br.get('errors'):
                out['verdict'] = 'baseline_broken'
            else:
                sp = b[:r['start_byte']] + r['replacement'].encode() + b[r['end_byte']:]
                tmp = src.with_name(f".verify_{out['key'][:12]}_{src.name}")
                tmp.write_bytes(sp)
                try:
                    res = run_lean(tmp, args.project, args.timeout)
                finally:
                    tmp.unlink(missing_ok=True)
                out['wall_ms'] = res.get('wall_ms')
                if res.get('timeout'): out['verdict'] = 'timeout'
                elif res['has_sorry'] and not br['has_sorry']: out['verdict'] = 'introduces_sorry'
                elif res['exit_code'] != 0 or res['errors']:
                    out['verdict'] = 'fail'; out['first_error'] = (res['errors'][:1] or [''])[0][:200]
                else: out['verdict'] = 'pass'
        with glock:
            fo.write(json.dumps(out, ensure_ascii=False) + '\n'); fo.flush()
            cnt[out['verdict']] = cnt.get(out['verdict'], 0) + 1
            if sum(cnt.values()) % 25 == 0: print(time.strftime('%H:%M:%S'), cnt, flush=True)
    # group by file to warm baselines evenly
    pending.sort(key=lambda r: r['file'])
    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(job, pending))
    print('VERIFY_DONE', cnt, flush=True)

if __name__ == '__main__':
    main()
