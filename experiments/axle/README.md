# Comparison with AXLE's `simplify_theorems`

LeanPolish and a deletion-based simplifier on the same inputs and the same Lean version (4.21.0).
AXLE's `simplify_theorems` removes unused tactics and `have`s until nothing changes. We run it on the
original proofs and on LeanPolish's fixed-point outputs, and we run LeanPolish to a fixed point on
AXLE's outputs.

## Scripts

| Script | Role |
|---|---|
| `run_axle.py` | call the AXLE service on a folder of files and save each full response |
| `rebuild_verify.py` | restore the original header, check every changed file with a fresh `lake env lean` |
| `compare.py` | reduction table from the saved files (offline) -> `results/table.json` |
| `audit.py` | statement, forbidden-token, fresh-process and `#print axioms` audit of every final file -> `results/audit.json` |

```bash
export REPLICATION_DATA=/path/to/replication        # unpacked experiments/replication.tar.gz
python3 compare.py                                   # offline, seconds
python3 audit.py 4                                   # needs the Lake project in leanpolish/
```

The inputs, AXLE's raw responses, the rebuilt outputs and the LeanPolish files are in the
`experiments/replication` tarball of the dataset
<https://huggingface.co/datasets/leanpolish-anon/lean-proof-compression>.

## Results (whole-corpus token reduction, %)

| Method | miniF2F-99 | PutnamBench-19 | AxiomProver-12 |
|---|---:|---:|---:|
| LeanPolish fixed point | 29.76 | 16.07 | 1.76 |
| AXLE | 27.12 | 25.56 | 0.00 |
| LeanPolish fixed point -> AXLE | **35.88** | **28.46** | 1.76 |
| AXLE -> LeanPolish fixed point | 33.97 | 28.14 | 1.76 |

* AXLE removes more on PutnamBench, almost entirely dead code; LeanPolish removes more on miniF2F;
  the two together give the largest reductions on both.
* AxiomProver is not a comparison: AXLE returns all 12 files unchanged, and for 7 of them its
  response reports that the simplification failed and was reverted (also for one miniF2F file).
* The Goedel-Prover-V2 inputs switch Lean's linters off in their header. AXLE then makes no edit, so
  these lines are removed from the text sent to AXLE and the original header is restored before
  counting.
* Audit: all 395 changed final files pass (fresh compile, identical theorem statements, no new
  `sorry` / `admit` / `axiom` / `native_decide`, only `propext`, `Classical.choice`, `Quot.sound`).
