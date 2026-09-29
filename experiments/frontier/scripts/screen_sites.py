#!/usr/bin/env python3
"""REPL declaration-level screen for generated candidates (fast pre-filter; NOT the final verdict).

Per file: one REPL process elaborates the file with allTactics (proofState ids), then for
each site replays the ORIGINAL fragment on its proofState to get the reference goals-after,
and replays every unique candidate (strictly shorter under count_appL, != original).
Candidate screen-passes iff: no error message, no sorry, goals-after list identical
(pretty-printed) to the original's. Deletions ("" / <DELETE>) cannot be replayed:
they are rejected if the original closes a goal (fewer goals after), otherwise marked
'needs_compile'. Final verdicts come from verify_full.py (fresh `lake env lean`).
"""
import argparse, json, os, re, subprocess, threading, queue, time, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import defaultdict
import os
_HERE = Path(__file__).resolve().parent
_ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
# local variants first, then shared hybrid scripts, then the shared token counters
sys.path[:0] = [str(_HERE), str(_ROOT / 'experiments' / 'hybrid' / 'scripts'), str(_ROOT / 'leanpolish')]
LEAN_PROJECT = os.environ.get('LEAN_PROJECT', str(_ROOT / 'leanpolish'))
WORK_DIR = os.environ.get('WORK_DIR', 'work')
REPL_BIN = os.environ.get('REPL_BIN', 'repl')
from retokenize_appendixL import count_appL

class Repl:
    def __init__(self, project, repl):
        self.p = subprocess.Popen(['lake', 'env', repl], cwd=project, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
    def _reader(self):
        buf = []
        for line in self.p.stdout:
            if line.strip() == '' and buf:
                self.q.put(''.join(buf)); buf = []
            elif line.strip():
                buf.append(line)
        if buf: self.q.put(''.join(buf))
        self.q.put(None)
    def send(self, obj, timeout):
        self.p.stdin.write(json.dumps(obj) + '\n\n'); self.p.stdin.flush()
        try:
            txt = self.q.get(timeout=timeout)
        except queue.Empty:
            return {'_timeout': True}
        if txt is None:
            return {'_dead': True}
        try:
            return json.loads(txt)
        except Exception:
            return {'_parse_error': txt[:300]}
    def kill(self):
        try: self.p.kill()
        except Exception: pass

def is_err(res):
    if any(k in res for k in ('_timeout', '_dead', '_parse_error')): return True
    if 'message' in res and 'env' not in res: return True
    for m in res.get('messages', []) or []:
        if m.get('severity') == 'error': return True
        if 'declaration uses \'sorry\'' in (m.get('data') or ''): return True
    if res.get('sorries'): return True
    return False

BOUND_OK = re.compile(r"^(?:[A-Za-z@#]|/-)")

def chunk_file(text: str):
    """Split a Lean file into top-level commands: boundaries at column-0 lines that start a
    command (letter, @[, #, /- doc). Comment/attribute-only chunks merge into the next one.
    Returns list of (start_byte, end_byte)."""
    b = text.encode()
    offs, acc = [], 0
    lines = text.split('\n')
    for ln in lines:
        offs.append(acc); acc += len(ln.encode()) + 1
    # ignore column-0 lines inside block comments (e.g. Aristotle's
    # multi-line file header), which otherwise become bogus chunk boundaries
    in_comment, depth = [], 0
    for ln in lines:
        in_comment.append(depth > 0)
        j = 0
        while j < len(ln):
            if ln.startswith('/-', j): depth += 1; j += 2
            elif ln.startswith('-/', j) and depth > 0: depth -= 1; j += 2
            elif depth == 0 and ln.startswith('--', j): break
            else: j += 1
    bounds = [0]
    for i, ln in enumerate(lines):
        if i == 0 or in_comment[i]: continue
        if BOUND_OK.match(ln) and not ln.startswith('import '):
            bounds.append(offs[i])
    bounds.append(len(b))
    chunks = []
    pend = None
    for a, z in zip(bounds, bounds[1:]):
        if pend is not None: a = pend; pend = None
        body = b[a:z].decode('utf-8', 'ignore')
        stripped = re.sub(r'/-.*?-/', '', body, flags=re.S)
        stripped = re.sub(r'--[^\n]*', '', stripped).strip()
        if (stripped == '' or re.fullmatch(r'(@\[[^\]]*\]\s*)+', stripped)) and z != len(b):
            pend = a; continue
        chunks.append((a, z))
    return chunks

def _byte_conv(text):
    lines = text.split('\n'); starts, acc = [], 0
    for ln in lines:
        starts.append(acc); acc += len(ln.encode()) + 1
    return lambda pos: starts[pos['line'] - 1] + len(lines[pos['line'] - 1][:pos['column']].encode())

class FileEnv:
    """Elaborates a file chunk-by-chunk (top-level commands) in one REPL with env chaining and
    allTactics, so proof states see all earlier declarations of the file."""
    def __init__(self, path, args):
        self.args = args
        self.src = Path(path).read_bytes()
        self.chunks = chunk_file(self.src.decode())
        self.boot()
    def boot(self):
        self.r = Repl(self.args.project, self.args.repl)
        self.env_before, self.chunk_ok, self.ps = [], [], {}
        env = None
        for (a, z) in self.chunks:
            self.env_before.append(env)
            text = self.src[a:z].decode('utf-8', 'ignore')
            cmd = {'cmd': text, 'allTactics': True}
            if env is not None: cmd['env'] = env
            res = self.r.send(cmd, timeout=self.args.file_timeout)
            if '_timeout' in res or '_dead' in res or 'env' not in res:
                raise RuntimeError(f'chunk boot failed: {str(res)[:200]}')
            self.chunk_ok.append(not is_err(res))
            conv = _byte_conv(text)
            for t in res.get('tactics', []):
                k = (a + conv(t['pos']), a + conv(t['endPos']))
                if k not in self.ps: self.ps[k] = t['proofState']
            env = res['env']
    def chunk_of(self, s, e):
        for i, (a, z) in enumerate(self.chunks):
            if a <= s and e <= z: return i
        return None
    def _send(self, cmd, timeout):
        res = self.r.send(cmd, timeout=timeout)
        if '_timeout' in res or '_dead' in res:
            self.r.kill(); self.boot()
        return res
    def try_splice(self, i, s, e, rep):
        a, z = self.chunks[i]
        text = (self.src[a:s] + rep.encode() + self.src[e:z]).decode('utf-8', 'ignore')
        cmd = {'cmd': text}
        if self.env_before[i] is not None: cmd['env'] = self.env_before[i]
        res = self._send(cmd, self.args.decl_timeout)
        if '_timeout' in res: return 'timeout'
        return 'fail' if is_err(res) else 'pass'
    def try_tactic(self, ps, tac):
        res = self._send({'tactic': tac, 'proofState': ps}, self.args.tac_timeout)
        return res
    def close(self): self.r.kill()

def screen_file(fname, sites, cands_by_site, args):
    out = []
    path = os.path.join(args.files_root, fname)
    try:
        fe = FileEnv(path, args)
    except Exception as ex:
        for st in sites:
            for c in cands_by_site.get(st['site_id'], []):
                out.append({'site_id': st['site_id'], 'replacement': c, 'screen': 'file_boot_fail'})
        return out
    for st in sites:
        cands = sorted(cands_by_site.get(st['site_id'], []))
        if not cands: continue
        s, e = st['start_byte'], st['end_byte']
        i = fe.chunk_of(s, e)
        ps = fe.ps.get((s, e))
        ogoals, ores = None, None
        if ps is not None and i is not None and fe.chunk_ok[i]:
            ores = fe.try_tactic(ps, st['original'])
            if not is_err(ores): ogoals = ores.get('goals', [])
        for c in cands:
            if i is None: v, how = 'no_chunk', '-'
            elif not fe.chunk_ok[i]: v, how = 'chunk_baseline_fail', '-'
            elif ogoals is not None and c.strip() != '':
                how = 'tactic'
                cres = fe.try_tactic(ps, c)
                if '_timeout' in cres: v = 'timeout'
                elif is_err(cres): v = 'fail'
                elif cres.get('goals', []) != ogoals: v = 'fail_goals_differ'
                else: v = 'pass'
            elif ogoals is not None and c.strip() == '' and len(ogoals) < st.get('n_goals_before', 1):
                v, how = 'fail_delete_closing', 'tactic'
            else:
                how = 'decl'
                try: v = fe.try_splice(i, s, e, c)
                except Exception: v = 'error'
            out.append({'site_id': st['site_id'], 'replacement': c, 'screen': v, 'how': how})
    fe.close()
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sites', nargs='+', required=True)
    ap.add_argument('--gens', nargs='+', required=True)
    ap.add_argument('--files-root', default=os.path.join(WORK_DIR, 'files'))
    ap.add_argument('--project', default=LEAN_PROJECT)
    ap.add_argument('--repl', default=REPL_BIN)
    ap.add_argument('--jobs', type=int, default=28)
    ap.add_argument('--tac-timeout', type=float, default=45)
    ap.add_argument('--decl-timeout', type=float, default=300)
    ap.add_argument('--file-timeout', type=float, default=3600)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-split', type=int, default=6)
    ap.add_argument('--cands-per-worker', type=int, default=150)
    args = ap.parse_args()
    sites = {}
    for p in args.sites:
        for l in open(p):
            s = json.loads(l); sites[s['site_id']] = s
    cands = defaultdict(set)
    for p in args.gens:
        for l in open(p):
            g = json.loads(l)
            s = sites.get(g['site_id'])
            if s is None: continue
            for c in [g['greedy']] + g.get('samples', []):
                if c == s['original'] or c.strip() == s['original'].strip(): continue
                if count_appL(c) >= count_appL(s['original']): continue
                cands[g['site_id']].add(c)
    done = set()
    if os.path.exists(args.out):
        for l in open(args.out):
            done.add(json.loads(l)['site_id'])
    by_file = defaultdict(list)
    for sid, s in sites.items():
        if sid in cands and sid not in done:
            by_file[s['file']].append(s)
    units = []
    for f, ss in by_file.items():
        ss.sort(key=lambda x: x['start_byte'])
        nc = sum(len(cands[x['site_id']]) for x in ss)
        k = max(1, min(args.max_split, nc // args.cands_per_worker))
        for j in range(k):
            units.append((f, ss[j::k]))
    units.sort(key=lambda u: -sum(len(cands[x['site_id']]) for x in u[1]))
    print(f'[screen] files={len(by_file)} units={len(units)} sites={sum(len(v) for v in by_file.values())} '
          f'cands={sum(len(cands[x["site_id"]]) for v in by_file.values() for x in v)}', flush=True)
    lock = threading.Lock()
    fo = open(args.out, 'a')
    def job(u):
        f, ss = u
        t0 = time.time()
        try:
            rows = screen_file(f, ss, cands, args)
        except Exception as ex:
            rows = [{'site_id': x['site_id'], 'replacement': c, 'screen': f'error:{ex!r}'[:200]}
                    for x in ss for c in cands[x['site_id']]]
        with lock:
            for r in rows: fo.write(json.dumps(r, ensure_ascii=False) + '\n')
            fo.flush()
            npass = sum(r['screen'] == 'pass' for r in rows)
            print(time.strftime('%H:%M:%S'), f'{f} rows={len(rows)} pass={npass} {time.time()-t0:.0f}s', flush=True)
    with ThreadPoolExecutor(args.jobs) as ex:
        list(ex.map(job, units))
    print('SCREEN_DONE', flush=True)

if __name__ == '__main__':
    main()
