#!/usr/bin/env python3
"""Independent final re-check: fresh `lake env lean` on every composed output file.
usage: recheck.py OUT.jsonl DIR [DIR...] (dirs relative to $FILES_ROOT, default ./files; env JOBS)"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import sys, json, hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from verify_full import run_lean
root = Path(__import__('os').environ.get('FROOT', _os.environ.get('FILES_ROOT', 'files')))
files = [p for d in sys.argv[2:] for p in sorted((root / d).glob('*.lean')) if not p.name.startswith('.')]
def job(p):
    r = run_lean(p, LEAN_PROJECT, 1800)
    ok = (not r.get('timeout')) and r.get('exit_code') == 0 and not r.get('errors') and not r.get('has_sorry')
    return {'file': str(p.relative_to(root)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'ok': ok,
            'sorry_in_output': r.get('has_sorry'), 'errors': (r.get('errors') or [])[:2], 'timeout': r.get('timeout')}
with ThreadPoolExecutor(int(__import__('os').environ.get('JOBS', '12'))) as ex, open(sys.argv[1], 'w') as f:
    for res in ex.map(job, files):
        f.write(json.dumps(res, ensure_ascii=False) + '\n'); f.flush()
print('RECHECK_DONE')
