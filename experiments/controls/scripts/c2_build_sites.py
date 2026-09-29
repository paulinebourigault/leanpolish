#!/usr/bin/env python3
"""C2 "LLM-only whole-proof compressor": one rewrite unit per proof-carrying top-level
declaration of the ORIGINAL file (for the single-theorem PutnamBench / miniF2F files this is
the whole proof; for the multi-lemma AxiomProver files it is every lemma/theorem body).

Units come from the same top-level command splitter used by the hybrid screen
(experiments/hybrid/scripts/screen_sites.chunk_file). The unit span starts at the declaration keyword
(leading doc comments / attributes stay outside) and ends at the last non-whitespace byte
of the command. Output rows use the hybrid "site" schema so that the unchanged
screen_sites.py (declaration-splice REPL lane) and compose.py (joint fresh-`lake env lean`
application + maximal compiling subset) can be reused.
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, json, random, re, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
from screen_sites import chunk_file  # noqa: E402

DECL_RE = re.compile(r'^(?:(?:private|protected|noncomputable|nonrec|unsafe|partial)\s+)*'
                     r'(theorem|lemma|example|def|instance|abbrev)\b', re.M)


def units_for(path: Path, corpus, variant, ctx_chars):
    text = path.read_text(); b = text.encode()
    out = []
    for a, z in chunk_file(text):
        body = b[a:z].decode('utf-8', 'ignore')
        m = DECL_RE.search(body)
        if not m or m.group(1) in ('def', 'instance', 'abbrev'):
            continue   # only proofs (theorem/lemma/example) are rewritten
        decl = body[m.start():].rstrip()
        if ':=' not in decl:
            continue
        s = a + len(body[:m.start()].encode()); e = s + len(decl.encode())
        assert b[s:e].decode() == decl
        sig = decl.split(':=', 1)[0]
        ctx = b[:s].decode('utf-8', 'ignore')
        if len(ctx) > ctx_chars:
            head = ctx.split('\n\n', 1)[0][:800]
            ctx = head + '\n\n-- … (earlier declarations omitted) …\n\n' + ctx[-(ctx_chars - len(head)):]
        out.append({'corpus': corpus, 'variant': variant, 'file': f'{corpus}/{variant}/{path.name}',
                    'start_byte': s, 'end_byte': e, 'original': decl, 'signature': sig,
                    'context': ctx, 'kind': 'decl',
                    'site_id': f'{corpus}/{variant}/{path.stem}:{s}:{e}'})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--files-root', required=True)
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--variant', default='orig')
    ap.add_argument('--only-list', help='file with stems to keep (e.g. miniF2F subsample)')
    ap.add_argument('--ctx-chars', type=int, default=3000)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    files = sorted(Path(args.files_root, args.corpus, args.variant).glob('*.lean'))
    if args.only_list:
        keep = set(open(args.only_list).read().split())
        files = [f for f in files if f.stem in keep]
    n = 0
    with open(args.out, 'w') as fo:
        for f in files:
            for u in units_for(f, args.corpus, args.variant, args.ctx_chars):
                fo.write(json.dumps(u, ensure_ascii=False) + '\n'); n += 1
    print(args.corpus, len(files), 'files', n, 'units')


if __name__ == '__main__':
    main()
