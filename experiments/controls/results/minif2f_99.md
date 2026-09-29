# miniF2F-99 (paper Table 4, miniF2F column)

The random 100-file miniF2F subset (`scripts/minif2f_subsample100.txt`) contains one linter-baseline
artifact (`algebra_sqineq_unitcircatbpabsamblt1_linter`). The paper removes it, so every miniF2F row of
Table 4 uses the same 99 files (`scripts/minif2f_99.txt`). Denominator: 38,040 tokens (Lean-aware counter,
`leanpolish/lean_counter.py`). `results/tables.md` also reports the 100-file values.

| Condition | Reduction (%), 99 files |
|---|---|
| LeanPolish, release run | 20.02 |
| LeanPolish, clean rerun | 20.52 |
| LeanPolish (clean) iterated to a fixed point | 29.76 |
| LLM whole-proof rewrite, frozen (k=16) | 12.52 |
| LLM rewrite, trained on LeanPolish pairs (k=16) | 16.36 |
| Hybrid, frozen few-shot / filter | 23.14 / 23.13 |
| Hybrid, trained DeepSeek / filter | 22.41 / 21.37 |
| LeanPolish (release) -> frozen LLM rewrite | 27.58 |
| LeanPolish (release) -> trained LLM rewrite | 27.13 |
| LeanPolish (clean) -> frozen LLM rewrite | 27.11 |
| frozen LLM rewrite -> LeanPolish | 27.99 |
