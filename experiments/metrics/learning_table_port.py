#!/usr/bin/env python3
"""Re-run recompute_numbers.py (unmodified on disk) with count_appL swapped for the
countLeanTokens port. Both the savings AND the 'shorter' success condition (_sav > 0) use the port.
Same inputs as recompute_numbers.py (RESULTS_DIR). Output: results/recompute_numbers_port.json."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
SRC = HERE / 'recompute_numbers.py'
code = SRC.read_text()
old_imp = 'from retokenize_appendixL import count_appL  # noqa: E402'
old_out = 'OUT_JSON.write_text('
assert code.count(old_imp) == 1 and code.count(old_out) == 1
code = code.replace(old_imp, 'from lean_counter import count_lean_tokens as count_appL  # PORT')
code = code.replace(old_out, '(HERE / "results" / "recompute_numbers_port.json").write_text(')
g = {'__file__': str(SRC), '__name__': '__main__'}
exec(compile(code, str(SRC), 'exec'), g)
