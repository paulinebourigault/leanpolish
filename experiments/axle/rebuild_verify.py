#!/usr/bin/env python3
"""Rebuild AXLE outputs into full files and verify them in a fresh Lean process.

The final file keeps the input's own header verbatim (everything before the first top-level
declaration) and takes AXLE's text from that declaration on; so removed `set_option linter`
lines and AXLE's header override never count as savings. Each changed file is checked with
`lake env lean` (Lean 4.21.0, Mathlib v4.21.0); a file that fails, or a failed AXLE request, keeps
the input. Writes <REPLICATION_DATA>/axle/outputs/<variant>/<corpus>/<name>.lean and
axle/score_<variant>.json.
Usage: rebuild_verify.py <variant> <corpus>:<input dir> ... [--jobs 4]
  LEAN_PROJECT: Lake project used for the checks (default: <repository>/leanpolish)
"""
import argparse, concurrent.futures as cf, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens as cA  # noqa: E402
HERE = Path(os.environ['REPLICATION_DATA']) / 'axle'     # raw/, outputs/, score_*.json live here
LP = Path(os.environ.get('LEAN_PROJECT', ROOT / 'leanpolish'))
TOPDECL = re.compile(r'^(?:/--|@\[|(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*'
                     r'(?:theorem|lemma|example|def|instance|abbrev|structure|inductive|class|namespace|section|variable)\b)', re.M)


def rebuild(orig, axle_text):
    mo, ma = TOPDECL.search(orig), TOPDECL.search(axle_text)
    if not mo or not ma:
        return None
    return orig[:mo.start()] + axle_text[ma.start():]


def check(text, timeout):
    with tempfile.NamedTemporaryFile('w', suffix='.lean', dir='/tmp', delete=False) as f:
        f.write(text); p = f.name
    t = time.time()
    try:
        r = subprocess.run(['lake', 'env', 'lean', p], cwd=LP, capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
        ok = r.returncode == 0 and not re.search(r'error', out) and "declaration uses 'sorry'" not in out
    except subprocess.TimeoutExpired:
        ok, out = False, 'TIMEOUT'
    Path(p).unlink(missing_ok=True)
    return ok, time.time() - t, out[-500:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant'); ap.add_argument('specs', nargs='+'); ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--timeout', type=int, default=2400)
    a = ap.parse_args()
    todo = []
    for spec in a.specs:
        corpus, d = spec.split(':', 1)
        for f in sorted(Path(d).glob('*.lean')):
            todo.append((corpus, f))
    res = {}

    def one(job):
        corpus, f = job
        orig = f.read_text()
        raw = HERE / 'raw' / a.variant / corpus / (f.stem + '.json')
        row = {'corpus': corpus, 'name': f.stem, 'tok_in': cA(orig), 'tok_out': cA(orig), 'status': 'unchanged'}
        if not raw.exists():
            row['status'] = 'no_response'
        else:
            d = json.loads(raw.read_text())
            row['axle_wall_s'] = d.get('client_wall_s'); row['stats'] = d.get('simplification_stats')
            if not d.get('ok'):
                row['status'] = 'axle_error'
            else:
                new = rebuild(orig, d.get('content', ''))
                if new is None:
                    row['status'] = 'rebuild_failed'
                elif new.strip() != orig.strip() and cA(new) < cA(orig):
                    ok, s, tail = check(new, a.timeout)
                    row.update(verify_s=s, verified=ok)
                    if ok:
                        row['tok_out'] = cA(new); row['status'] = 'shortened'
                        o = HERE / 'outputs' / a.variant / corpus / f.name
                        o.parent.mkdir(parents=True, exist_ok=True); o.write_text(new)
                    else:
                        row['status'] = 'failed_verify'; row['tail'] = tail
        print(corpus, f.stem, row['status'], row['tok_in'], row['tok_out'], flush=True)
        return f'{corpus}/{f.stem}', row

    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for k, row in ex.map(one, todo):
            res[k] = row
    (HERE / f'score_{a.variant}.json').write_text(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
