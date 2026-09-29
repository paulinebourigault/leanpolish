# Verified hybrid (Algorithm 2)

LeanPolish shortens each file first; a trained local editor then proposes a replacement at
every remaining tactic site of the shortened file. Proposals are pre-screened in the Lean REPL,
the best passing edit per site is applied jointly, and every output file is compiled with a
fresh `lake env lean` (recursive halving keeps the largest compiling subset). Paper: §5,
Table 4 ("Hybrid" and "Local editor alone" rows), seed-robustness statement in §4.
The paper refers to `scripts/pipeline.sh` as `beyond_teacher/scripts/pipeline.sh`.

## Scripts (`scripts/`)

| Script | Role |
|---|---|
| `make_bases.py` | Build `files/<corpus>/{orig,base}/` (original and LeanPolish-shortened trees) from the released data. |
| `extract_sites.py` | Tactic sites of a file tree via the Lean REPL, with the SFT prompt for each site. |
| `gen_sites.py` | vLLM generation with a LoRA adapter: greedy + `--k` samples (T=0.6, top-p 0.95, seed 42). |
| `pipeline.sh` | REPL screen (`screen_sites.py`) then whole-file composition (`compose.py`): greedy / all / all + specificity filter. |
| `screen_sites.py` | REPL pre-screen (goals-after must match the original); not the final verdict. |
| `compose.py` | Joint application of the best passing edits; fresh `lake env lean`; maximal compiling subset. |
| `make_verify_input.py`, `verify_full.py` | Site-level exact verification of screen passes (splice + fresh compile). |
| `recheck.py` | Independent fresh-process re-check of every composed output file. |
| `quality_filter.py` | Python port of LeanPolish's `isQualityUpgrade` (specificity filter). |
| `analyze.py` | Aggregate sites / screen / verify / compose into `metrics.json`. |
| `unified_hybrid.py` | Whole-file reductions on the unified metric basis (`experiments/metrics`) -> `unified_hybrid.json`. |
| `seeds_eval.py`, `make_seeds_md.py` | Greedy valid-and-shorter on the 1,406 held-out sites for one checkpoint; seed table. |

Token counters (`lean_counter.py`, `retokenize_appendixL.py`) are imported from `leanpolish/`.

## Running

Environment: `LEAN_PROJECT` (Lake project with Mathlib built; default `<release>/leanpolish`),
`REPL_BIN` (leanprover-community/repl binary), `HYBRID_WORKDIR` (working directory; default `.`),
`LEANPOLISH_ROOT` (release root; inferred from the script location). Script-specific inputs:
`RUN_ROOT` / `EVAL_ROOT` (`make_bases.py`: unpacked dataset and held-out eval sources),
`METRICS_DIR` (`unified_hybrid.py`; default `experiments/metrics`), `SFT_RESULTS`
(`seeds_eval.py`: archived held-out verdicts; default `results_data/exp1_sft_dpo`),
`SEEDS_DIR` (`make_seeds_md.py`; default `results/seeds`), `FILES_ROOT` and `JOBS` (`recheck.py`).

```bash
S=experiments/hybrid/scripts; export HYBRID_WORKDIR=$PWD/work; cd $HYBRID_WORKDIR
RUN_ROOT=<unpacked dataset> EVAL_ROOT=<eval sources> python3 $S/make_bases.py files
python3 $S/extract_sites.py --files-root files --corpus putnam2025 --variant base --out sites_putnam2025_base.jsonl
python3 $S/gen_sites.py --adapter adapters/deepseek --sites sites_putnam2025_base.jsonl --out gens/putnam2025_base.jsonl
bash $S/pipeline.sh putnam2025 base 16 6          # screen + compose -> files/putnam2025/hybrid_{greedy,all,all_qf}/
python3 $S/recheck.py recheck_putnam2025.jsonl putnam2025/hybrid_all
python3 $S/analyze.py && python3 $S/unified_hybrid.py
```

Use `--variant orig` for the neural-alone lanes, `gen_sites.py --k 16` for best-of-17, and
`--base Qwen/Qwen2.5-Coder-7B-Instruct` with the Qwen adapter for the Qwen rows.

Large inputs and outputs (sites, generations, screen and verify verdicts, compose reports, all
output files, `examples_all.json`) are in the dataset tarball `experiments/beyond_teacher` at
<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>; the LoRA adapters are under `adapters/`.

## Results (`results/`)

`metrics.json` (site- and file-level aggregates), `unified_hybrid.json`, `final_table.md` (all lanes, both
counters), `seeds/*.json` + `seeds.md` (three training seeds per model), `examples_10.json` (sample edits).

Whole-file token reduction (%), Lean-aware counter, as in Table 4:

| Method | AxiomProver (12) | PutnamBench (19) | miniF2F |
|---|---:|---:|---:|
| LeanPolish, release run | 1.31 | 6.14 | 20.02 (miniF2F-99) |
| Local editor alone (trained) | 2.51 | 3.10 | --- |
| Hybrid, trained DeepSeek | 3.65 | 9.02 | 22.41 (miniF2F-99); 21.74 (all 351) |
| Hybrid, trained DeepSeek, filter | 2.38 | 8.04 | 21.37 (miniF2F-99) |
| Hybrid, trained Qwen | 4.00 | 11.38 | 23.76 (all 351) |

Hybrid rows are best of greedy and four samples. Greedy only (AxiomProver): 3.42. On AxiomProver,
753 of the editor's 776 accepted edits (97%) use tactics on LeanPolish's menu, and 526 of
those 753 are rejected by its specificity filter (`metrics.json`, `menu` / `teacher_miss_reasons_in_menu`).
Three training seeds per model differ by at most 1.4 points (standard deviation) on any held-out source (`seeds.md`).
