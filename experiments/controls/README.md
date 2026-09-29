# Controls for the verified hybrid

Controls that separate the contribution of the trained editor, of LLM rewriting, and of re-running
LeanPolish (paper §5, Table 4, "Symbolic only", "Neural only" and "Composed pipelines" rows):

* **C1, frozen hybrid.** The trained editor of Algorithm 2 is replaced by frozen DeepSeek-Prover-V2-7B with the
  fixed four-demonstration prompt of `experiments/fewshot`; sites, decoding (greedy + 4 samples), screen and
  composition are those of `experiments/hybrid`.
* **C2, LLM whole-proof rewrite.** A frozen model (DeepSeek-Prover-V2-7B or Qwen2.5-Coder-32B-Instruct) rewrites each
  proof-carrying declaration (16 samples, T=0.7; the first 4 form k=4); alone, after LeanPolish (release or clean
  rerun), or followed by LeanPolish.
* **Clean rerun.** The same LeanPolish binary re-run on the original files without resource contention.
* **C3, alternation.** Rounds of LeanPolish followed by the trained editor, starting from the hybrid output.

Sets: PutnamBench-verified (19 files that compile under Lean/Mathlib v4.21.0; 24-file mirror also reported),
Putnam 2025 AxiomProver (12 files), and miniF2F-100 (`scripts/minif2f_subsample100.txt`,
`random.Random(0).sample(sorted(stems), 100)`). Primary counter: Python port of `countLeanTokens`.
A file without a verified output counts as its original.

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `gen_c1_fewshot.py` | C1 generation (vLLM) with the few-shot prompt; imports `experiments/fewshot/gen_fewshot.py`; demos in `fewshot_demos.json`. |
| `c2_build_sites.py` | C2 rewrite units: one per proof-carrying top-level declaration. |
| `gen_c2_whole.py` | C2 generation; rejects changed statements and `sorry` / `admit` / `axiom` / `native_decide` / `decide := true`. |
| `c2_screen.py` | C2 REPL screen (declaration splice), reusing `screen_sites.py` of `experiments/hybrid`. |
| `c1_c2_compose.sh` | Screen + whole-file composition for C1 (`c1`) and C2 (`c2`). |
| `run_leanpolish.py` | Run LeanPolish (`leanpolish.py` in `$LEAN_PROJECT`) on a set of files; report tokens, wall time, candidate checks. |
| `lp_rerun.sh` | Clean rerun of LeanPolish alone on the three sets. |
| `post_c2.sh` | LLM rewrite -> LeanPolish. |
| `c3_round.sh` | One alternation round (LeanPolish -> sites -> trained editor -> screen -> compose). |
| `analyze_controls.py`, `make_tables.py` | Aggregate into `metrics.json`; render `tables.md`. |

Environment: `CONTROLS_WORKDIR` (working directory with `files/<corpus>/{orig,base}/` and `files100/minif2f/`;
default `.`), `LEAN_PROJECT`, `REPL_BIN`, `MODEL`, `ADAPTER`, `JOBS`.

```bash
S=experiments/controls/scripts
python3 $S/gen_c1_fewshot.py --model deepseek-ai/DeepSeek-Prover-V2-7B --sites sites_putnam2025_base.jsonl --out gens/c1ds.jsonl
bash $S/c1_c2_compose.sh c1 putnam2025 sites_putnam2025_base.jsonl gens/c1ds.jsonl c1ds_putnam2025
python3 $S/c2_build_sites.py --files-root files --corpus putnam_verified --variant orig --out sites/c2_units_putnam_verified_orig.jsonl
python3 $S/gen_c2_whole.py --model deepseek-ai/DeepSeek-Prover-V2-7B --units sites/c2_units_putnam_verified_orig.jsonl --out gens/c2ds_pv
bash $S/c1_c2_compose.sh c2 putnam_verified sites/c2_units_putnam_verified_orig.jsonl gens/c2ds_pv c2ds_pv orig
bash $S/post_c2.sh c2ds_pv putnam_verified k16 4
bash $S/lp_rerun.sh
ADAPTER=adapters/deepseek bash $S/c3_round.sh putnam_verified 1     # input: files/putnam_verified/c3_r0 = hybrid output
python3 $S/analyze_controls.py --root . --bt <hybrid workdir> --out metrics.json && python3 $S/make_tables.py metrics.json > tables.md
```

Generations, screen verdicts, compose reports and all output files are in the dataset tarball
`experiments/hybrid_controls` at <https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>.

## Results (`results/`)

`metrics.json` (whole-file tokens under three counters, per-condition cost, C2 candidate statistics) and
`tables.md` (all conditions and counters). Key numbers (% whole-file reduction, Lean-aware counter), as in Table 4:

| Method | AxiomProver (12) | PutnamBench (19) | miniF2F-99 |
|---|---:|---:|---:|
| LeanPolish, release run | 1.31 | 6.14 | 20.02 |
| LeanPolish, clean rerun | 1.41 | 11.91 | 20.52 |
| LLM whole-proof rewrite, frozen | 1.04 (k=4) | 2.76 | 12.52 |
| Hybrid, frozen few-shot | 3.66 | 9.31 | 23.14 |
| Hybrid, frozen few-shot, filter | 3.66 | 9.30 | 23.13 |
| LeanPolish (release) -> frozen LLM rewrite | 2.34 (k=4) | 7.88 | 27.58 |
| LeanPolish (clean) -> frozen LLM rewrite | --- | 12.85 | 27.11 |
| Frozen LLM rewrite -> LeanPolish | 2.53 (k=4) | 10.36 | 27.99 |
| LeanPolish <-> trained editor, alternated | 5.05 (two rounds) | 20.25 (three rounds) | --- |

miniF2F-99 = the 100-file subset minus one linter-baseline artifact (`scripts/minif2f_99.txt`, values in `results/minif2f_99.md`); `tables.md` also gives 100-file values. LLM rewrites use k=16 samples unless stated. Frozen few-shot hybrid with greedy decoding only on AxiomProver: 3.17
(trained editor: 3.42). Qwen2.5-Coder-32B rewrites: 1–14% of strictly shorter rewrites compile (`tables.md`, C2 cost table).
The frozen editor's AxiomProver edit mix (397 of 414 applied edits are deletions) is computed from the compose reports in the dataset tarball.
