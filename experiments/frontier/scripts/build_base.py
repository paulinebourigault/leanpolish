#!/usr/bin/env python3
"""After the LeanPolish teacher runs: build the hybrid base tree and teacher-edit map.

For each file <corpus>/lp/<X>.lean:
  base = <X>_shortened.lean if LeanPolish emitted a (fresh-kernel post-verified) one,
         else the unmodified original (teacher found nothing / failed -> credited zero).
Writes <files>/<corpus>/base/<X>.lean and teacher_edits.json with, per file, the
regions of the BASE file that LeanPolish changed (difflib opcodes on lines -> byte spans; replaced/
inserted spans as [j1,j2), pure deletions as zero-width points). Sites overlapping these
regions are excluded from the neural lane ("sites LeanPolish left untouched").
Also records appL token counts (retokenize_appendixL.count_appL).
"""
import difflib, json, sys
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

# usage: build_base.py <files_root> corpus/NAME ...   (only files whose teacher run has finished)
F = Path(sys.argv[1])
TE = F.parent / 'teacher_edits.json'
out = json.load(open(TE)) if TE.exists() else {}
for key in sys.argv[2:]:
        corpus, name = key.split('/')
        (F / corpus / 'base').mkdir(parents=True, exist_ok=True)
        orig = F / corpus / 'orig' / f'{name}.lean'
        sh = F / corpus / 'lp' / f'{name}_shortened.lean'
        rep = F / corpus / 'lp' / f'{name}_report.json'
        o = orig.read_bytes()
        b = sh.read_bytes() if sh.exists() else o
        (F / corpus / 'base' / f'{name}.lean').write_bytes(b)
        # line-level diff (byte-level difflib is quadratic on these files); regions are the
        # base-file byte spans of changed lines (conservative: whole lines are excluded)
        ol, bl = o.split(b'\n'), b.split(b'\n')
        boff = [0]
        for ln in bl:
            boff.append(boff[-1] + len(ln) + 1)
        sm = difflib.SequenceMatcher(None, ol, bl, autojunk=False)
        regions = [(tag, i1, i2, boff[j1], max(boff[j1], boff[j2] - 1) if j2 > j1 else boff[j1])
                   for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != 'equal']
        r = json.loads(rep.read_text()) if rep.exists() else {}
        out[f'{corpus}/{name}'] = {
            'teacher_output': sh.exists(),
            'teacher_report': {k: r.get(k) for k in ('verified', 'tokens_original', 'tokens_shortened',
                                                    'tactic_replacements', 'dead_code_removed', 'error')},
            'n_teacher_training_pairs': len(r.get('training_pairs', [])),
            'appL_orig': count_appL(o.decode()), 'appL_base': count_appL(b.decode()),
            'bytes_orig': len(o), 'bytes_base': len(b),
            'base_regions': [[j1, j2, tag] for tag, i1, i2, j1, j2 in regions],
        }
        v = out[f'{corpus}/{name}']
        print(corpus, name, 'teacher_out' if sh.exists() else 'NO_OUTPUT',
              v['appL_orig'], '->', v['appL_base'], f"saved {v['appL_orig'] - v['appL_base']}",
              f"({100 * (v['appL_orig'] - v['appL_base']) / v['appL_orig']:.2f}%)", 'regions', len(regions))
json.dump(out, open(TE, 'w'), indent=1)
