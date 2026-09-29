#!/usr/bin/env python3
"""Re-run experiments/fewshot/compute_fewshot_metrics.py (unmodified) with the countLeanTokens port.
Input: FEWSHOT_DATA (dir with verdicts_fewshot.jsonl and the generations; HF experiments/fewshot).
Output: results/fewshot_metrics_port.json, results/fewshot_results_port.md.
Caveat: candidates that are port-shorter but were appL-not-shorter never got a Lean verdict -> 'pending' (=0)."""
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1]))
SRC = ROOT / 'experiments' / 'fewshot' / 'compute_fewshot_metrics.py'
code = SRC.read_text()
old = 'from retokenize_appendixL import count_appL  # noqa: E402'
assert code.count(old) == 1
code = code.replace(old, 'sys.path.insert(0, %r)\n' % str(ROOT / 'leanpolish') +
                         'from lean_counter import count_lean_tokens as count_appL  # PORT')
F = Path(os.environ.get('FEWSHOT_DATA', ROOT / 'experiments' / 'fewshot' / 'data'))
sys.argv = ['x', '--cands', str(F / 'cands_fewshot_deepseek.jsonl'), str(F / 'cands_fewshot_qwen.jsonl'),
            '--verdicts', str(F / 'verdicts_fewshot.jsonl'), '--out', str(HERE / 'results' / 'fewshot_metrics_port.json'),
            '--md', str(HERE / 'results' / 'fewshot_results_port.md')]
exec(compile(code, str(SRC), 'exec'), {'__file__': str(SRC), '__name__': '__main__'})
