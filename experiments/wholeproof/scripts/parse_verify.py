#!/usr/bin/env python3
"""Parse whole-proof generations into candidate FILES, gate them, and verify each unique gated
candidate with a fresh `lake env lean <file>` (Lean 4.21 + Mathlib v4.21.0, project $LEAN_PROJECT).
Env: LEAN_PROJECT (default <root>/leanpolish), TMP_DIR for candidate files (default ./tmp).

Parsing (per sample):
  simple prompt: last ```lean block of the answer (text after `</think>` if present); an unclosed
    fence at finish_reason=length -> 'truncated' (rejected). If the candidate has no `import`
    line but the original does, the original preamble (everything before the first top-level
    declaration/docstring/namespace) is prepended ('header_restored').
  c2 prompt: the hybrid-controls C2 parse (declaration located by keyword+name, statement must
    match), spliced back into the original file at the unit's byte span.
Gates (reject, never compiled):
  * every theorem/lemma of the original must be present in the candidate with the same name and a
    whitespace-normalised identical statement (text from the keyword up to the first `:=`);
  * no new occurrences of sorry/admit/axiom/native_decide/implemented_by/extern/unsafe/
    `decide := true` (a token is forbidden unless the original already contains it);
  * candidate must be strictly shorter than the original in Appendix-L tokens (else it cannot
    change the keep-shortest result; counted as 'not_shorter').
Verification: rc == 0, no line containing 'error', and no "declaration uses 'sorry'".
Compile results are cached by sha256 of the candidate bytes (verdicts/compile_cache.jsonl).
Output: verdicts/<name>.jsonl, one row per item: per-sample status + appL + verdict, plus
best_k4 / best_k16 (shortest verified, else original).
"""
import argparse, concurrent.futures as cf, hashlib, json, os, re, subprocess, sys, tempfile, threading, time
from pathlib import Path
_HERE = Path(__file__).resolve().parent
_ROOT = Path(os.environ.get('LEANPOLISH_ROOT', _HERE.parents[2]))
sys.path[:0] = [str(_HERE), str(_ROOT / 'leanpolish')]
from retokenize_appendixL import count_appL

LP = os.environ.get('LEAN_PROJECT', str(_ROOT / 'leanpolish'))
TMP = os.environ.get('TMP_DIR', os.path.abspath('tmp'))
FORBID = ('sorry', 'admit', 'axiom', 'native_decide', 'implemented_by', 'extern', 'unsafe')
DECL = re.compile(r'^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec)\s+)*(theorem|lemma)\s+([^\s(:{\[⦃]+)', re.M)
TOPDECL = re.compile(r'^(?:/--|@\[|(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*'
                     r'(?:theorem|lemma|example|def|instance|abbrev|structure|inductive|class|namespace|section|variable)\b)', re.M)

DEFDECL = re.compile(r'^(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*'
                     r'(?:def|abbrev|instance|structure|inductive|class)\b', re.M)


def strip_comments(t):
    """Remove Lean block comments (incl. docstrings, nested) and `--` line comments."""
    out, i, depth, n = [], 0, 0, len(t)
    while i < n:
        if t.startswith('/-', i):
            depth += 1; i += 2; continue
        if depth and t.startswith('-/', i):
            depth -= 1; i += 2; continue
        if depth:
            i += 1; continue
        if t.startswith('--', i):
            j = t.find('\n', i); i = n if j < 0 else j; continue
        out.append(t[i]); i += 1
    return ''.join(out)


def appl_nc(t):
    return count_appL(strip_comments(t))


def norm(s):
    return ' '.join(s.split())


def statements(text):
    out = {}
    for m in DECL.finditer(text):
        rest = text[m.start():]
        cut = rest.find(':=')
        nxt = DECL.search(text, m.end())
        if cut < 0 or (nxt and m.start() + cut > nxt.start()):
            cut = (nxt.start() - m.start()) if nxt else len(rest)
        out.setdefault(m.group(2), []).append(norm(rest[:cut]))
    return out


def code_block(text):
    t = text.split('</think>', 1)[1] if '</think>' in text else text
    blocks = re.findall(r'```[A-Za-z0-9_]*[ \t]*\n(.*?)```', t, flags=re.S)
    if blocks:
        return blocks[-1], False
    m = re.search(r'```[A-Za-z0-9_]*[ \t]*\n', t)
    if not m:
        return None, False
    return t[m.end():], True


def parse_simple(raw, finish, orig):
    code, unclosed = code_block(raw)
    if code is None:
        return None, 'no_code'
    if unclosed and finish == 'length':
        return None, 'truncated'
    why = 'ok'
    if not re.search(r'^import\s', code, re.M) and re.search(r'^import\s', orig, re.M):
        m = TOPDECL.search(orig)
        if m is None:  # no declaration in the original (commented-out stub files): keep its preamble lines
            m = re.search(r'\n(?!import|open|set_option|\s*$)', orig)
        code = (orig[:m.start()] if m else orig) + '\n' + code.lstrip('\n')
        why = 'ok_header_restored'
    return code.rstrip() + '\n', why


def parse_c2(raw, finish, orig, u):
    code, unclosed = code_block(raw)
    if code is None:
        return None, 'no_code'
    if unclosed and finish == 'length':
        return None, 'truncated'
    first = u['original'].split('\n', 1)[0].strip()
    key = ' '.join(first.split()[:2])
    idx = code.find(key)
    if idx < 0:
        return None, 'decl_not_found'
    cand = code[idx:].rstrip()
    b = orig.encode()
    return (b[:u['start_byte']] + cand.encode() + b[u['end_byte']:]).decode(), 'ok'


def gate(cand, orig):
    so, sc = statements(orig), statements(cand)
    for name, sigs in so.items():
        if name not in sc or not all(x in sc[name] for x in sigs):
            return 'statement_changed'
    # definitions (e.g. PutnamBench `abbrev ..._solution`) must be kept verbatim (whitespace-normalised)
    nc = norm(cand)
    for m in DEFDECL.finditer(orig):
        nxt = TOPDECL.search(orig, m.end())
        if norm(orig[m.start():nxt.start() if nxt else len(orig)]) not in nc:
            return 'definition_changed'
    for w in FORBID:
        pat = r'(?<![A-Za-z0-9_])' + re.escape(w) + r'(?![A-Za-z0-9_])'
        if len(re.findall(pat, cand)) > len(re.findall(pat, orig)):
            return 'forbidden:' + w
    if 'decide := true' in cand and 'decide := true' not in orig:
        return 'forbidden:decide:=true'
    return None


_lock = threading.Lock()


def compile_file(text, timeout):
    with tempfile.NamedTemporaryFile('w', suffix='.lean', dir=TMP, delete=False) as f:
        f.write(text); fn = f.name
    t0 = time.time()
    try:
        p = subprocess.run(['lake', 'env', 'lean', fn], cwd=LP, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, 'PATH': os.path.expanduser('~/.elan/bin') + ':' + os.environ['PATH']})
        out = p.stdout + p.stderr
        ok = p.returncode == 0 and not re.search(r'(^|:)\s*error', out, re.M) and "declaration uses 'sorry'" not in out
        v = 'pass' if ok else 'fail'
        msg = out[-800:]
    except subprocess.TimeoutExpired:
        v, msg = 'timeout', ''
    finally:
        os.unlink(fn)
    return v, round(time.time() - t0, 1), msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--items', nargs='+', required=True)
    ap.add_argument('--gens', required=True)
    ap.add_argument('--mode', choices=['simple', 'c2'], default='simple')
    ap.add_argument('--out', required=True)
    ap.add_argument('--jobs', type=int, default=12)
    ap.add_argument('--timeout', type=int, default=600)
    ap.add_argument('--max-samples', type=int, default=16, help='only the first N samples are parsed/verified')
    ap.add_argument('--cache', default='verdicts/compile_cache.jsonl')
    args = ap.parse_args()
    os.makedirs(TMP, exist_ok=True)
    items = {}
    for p in args.items:
        for l in open(p):
            it = json.loads(l); items[it['id']] = it
    gens = [json.loads(l) for l in open(args.gens)]
    cache = {}
    if os.path.exists(args.cache):
        for l in open(args.cache):
            r = json.loads(l); cache[r['sha']] = r
    rows, pending = [], {}
    for g in gens:
        it = items[g['id']]; orig = it['text']; o_tok = count_appL(orig); o_nc = appl_nc(orig)
        samples = []
        for raw, fin in list(zip(g['raw'], g['finish']))[:args.max_samples]:
            if args.mode == 'simple':
                cand, why = parse_simple(raw, fin, orig)
            else:
                cand, why = parse_c2(raw, fin, orig, it['unit'])
            s = {'parse': why}
            if cand is not None:
                if cand.strip() == orig.strip():
                    s['status'] = 'identical'
                else:
                    r = gate(cand, orig)
                    if r:
                        s['status'] = r
                    else:
                        s['appL'] = count_appL(cand); s['appL_nc'] = appl_nc(cand)
                        if s['appL'] >= o_tok:
                            s['status'] = 'not_shorter'
                        else:
                            s['status'] = 'compile'
                            s['sha'] = hashlib.sha256(cand.encode()).hexdigest()
                            if s['sha'] not in cache:
                                pending[s['sha']] = cand
            else:
                s['status'] = why
            samples.append(s)
        rows.append({'id': g['id'], 'max_samples': args.max_samples, 'orig_appL': o_tok, 'orig_appL_nc': o_nc, 'samples': samples, 'gen_tokens': g['gen_tokens'],
                     'prompt_tokens': g['prompt_tokens'], 'cands': {}})
    print(f'[verify] {len(rows)} items, {len(pending)} new unique compiles, {len(cache)} cached', flush=True)
    t0 = time.time(); done = 0
    with open(args.cache, 'a') as fc, cf.ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(compile_file, t, args.timeout): sha for sha, t in pending.items()}
        for fu in cf.as_completed(futs):
            sha = futs[fu]; v, dt, msg = fu.result()
            r = {'sha': sha, 'verdict': v, 'secs': dt, 'msg': msg, 'text': pending[sha]}
            cache[sha] = r
            with _lock:
                fc.write(json.dumps(r, ensure_ascii=False) + '\n'); fc.flush()
            done += 1
            if done % 25 == 0:
                print(f'[verify] {done}/{len(pending)} {time.time() - t0:.0f}s', flush=True)
    with open(args.out, 'w') as fo:
        for r in rows:
            for s in r['samples']:
                if s['status'] == 'compile':
                    c = cache[s['sha']]
                    s['verdict'] = c['verdict']; s['compile_s'] = c['secs']
            for k in (4, 16):
                ok = [(s['appL'], s['appL_nc']) for s in r['samples'][:k] if s.get('verdict') == 'pass']
                b = min(ok) if ok else (r['orig_appL'], r['orig_appL_nc'])
                r[f'best_k{k}'], r[f'best_nc_k{k}'] = b
            del r['cands']
            fo.write(json.dumps(r) + '\n')
    print('[verify] done', time.time() - t0, flush=True)


if __name__ == '__main__':
    main()
