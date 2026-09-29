# Whole-file token reduction: hybrid and neural-alone lanes

File lists: `experiments/metrics/file_lists/{putnam2025,putnam_verified,minif2f}.txt` (12 / 19 / 351 files). **Counter A** (Python port of LeanPolish's `countLeanTokens`) is primary; **[counter B = `count_appL`]** is in brackets. Reductions are measured against the original corpus; unshortened files count as 0 saved. Computed by `scripts/analyze.py` and `scripts/unified_hybrid.py` (`unified_hybrid.json`).

Every hybrid or neural cell is a set of whole files that compiled: for each file the selected edits (one per site, non-overlapping) were applied together and compiled with a fresh `lake env lean`; on failure, recursive halving kept the largest compiling subset. Every output file was then re-checked independently (`recheck.py`).

"Hybrid" = LeanPolish output plus the trained editor at every remaining REPL tactic site of the shortened file. "Neural alone" = the trained editor on the original files. "Filter-compliant" = only edits that pass the Python port of LeanPolish's `isQualityUpgrade` (deletions allowed).

## AxiomProver (Putnam 2025) (12 files)

| Lane | Tokens A [B] | Saved A [B] | Reduction A [B] |
|---|---:|---:|---:|
| Original | 133,686 [137,805] | 0 [0] | **0.00%** [0.00%] |
| LeanPolish alone | 131,940 [136,347] | 1,746 [1,458] | **1.31%** [1.06%] |
| Neural alone, DeepSeek SFT, greedy (original files) | 130,650 [135,552] | 3,036 [2,253] | **2.27%** [1.63%] |
| Neural alone, DeepSeek SFT, best-of-5 | 130,334 [135,294] | 3,352 [2,511] | **2.51%** [1.82%] |
| Neural alone, DeepSeek SFT, best-of-5, filter-compliant | 132,052 [136,590] | 1,634 [1,215] | **1.22%** [0.88%] |
| Hybrid, DeepSeek SFT, greedy | 129,120 [134,244] | 4,566 [3,561] | **3.42%** [2.58%] |
| Hybrid, DeepSeek SFT, best-of-5 (greedy+4) | 128,807 [133,992] | 4,879 [3,813] | **3.65%** [2.77%] |
| Hybrid, DeepSeek SFT, best-of-5, filter-compliant | 130,500 [135,275] | 3,186 [2,530] | **2.38%** [1.84%] |
| Hybrid, DeepSeek SFT, best-of-17 (greedy+16) | 128,454 [133,723] | 5,232 [4,082] | **3.91%** [2.96%] |
| Hybrid, Qwen2.5-Coder SFT, greedy | 128,701 [133,950] | 4,985 [3,855] | **3.73%** [2.80%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5 | 128,342 [133,679] | 5,344 [4,126] | **4.00%** [2.99%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5, filter-compliant | 130,023 [134,941] | 3,663 [2,864] | **2.74%** [2.08%] |

## PutnamBench-verified (19 files)

| Lane | Tokens A [B] | Saved A [B] | Reduction A [B] |
|---|---:|---:|---:|
| Original | 22,116 [23,059] | 0 [0] | **0.00%** [0.00%] |
| LeanPolish alone | 20,757 [21,721] | 1,359 [1,338] | **6.14%** [5.80%] |
| Neural alone, DeepSeek SFT, greedy (original files) | 21,458 [22,472] | 658 [587] | **2.98%** [2.55%] |
| Neural alone, DeepSeek SFT, best-of-5 | 21,431 [22,445] | 685 [614] | **3.10%** [2.66%] |
| Neural alone, DeepSeek SFT, best-of-5, filter-compliant | 21,654 [22,668] | 462 [391] | **2.09%** [1.70%] |
| Hybrid, DeepSeek SFT, greedy | 20,151 [21,183] | 1,965 [1,876] | **8.88%** [8.14%] |
| Hybrid, DeepSeek SFT, best-of-5 (greedy+4) | 20,122 [21,154] | 1,994 [1,905] | **9.02%** [8.26%] |
| Hybrid, DeepSeek SFT, best-of-5, filter-compliant | 20,337 [21,369] | 1,779 [1,690] | **8.04%** [7.33%] |
| Hybrid, DeepSeek SFT, best-of-17 (greedy+16) | 20,082 [21,114] | 2,034 [1,945] | **9.20%** [8.43%] |
| Hybrid, Qwen2.5-Coder SFT, greedy | 19,686 [20,716] | 2,430 [2,343] | **10.99%** [10.16%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5 | 19,599 [20,631] | 2,517 [2,428] | **11.38%** [10.53%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5, filter-compliant | 19,801 [20,833] | 2,315 [2,226] | **10.47%** [9.65%] |

## miniF2F (351 files)

| Lane | Tokens A [B] | Saved A [B] | Reduction A [B] |
|---|---:|---:|---:|
| Original | 140,040 [138,382] | 0 [0] | **0.00%** [0.00%] |
| LeanPolish alone | 112,421 [111,079] | 27,619 [27,303] | **19.72%** [19.73%] |
| Hybrid, DeepSeek SFT, greedy | 109,783 [108,813] | 30,257 [29,569] | **21.61%** [21.37%] |
| Hybrid, DeepSeek SFT, best-of-5 (greedy+4) | 109,595 [108,641] | 30,445 [29,741] | **21.74%** [21.49%] |
| Hybrid, DeepSeek SFT, best-of-5, filter-compliant | 110,994 [109,920] | 29,046 [28,462] | **20.74%** [20.57%] |
| Hybrid, Qwen2.5-Coder SFT, greedy | 107,173 [106,425] | 32,867 [31,957] | **23.47%** [23.09%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5 | 106,761 [106,063] | 33,279 [32,319] | **23.76%** [23.35%] |
| Hybrid, Qwen2.5-Coder SFT, best-of-5, filter-compliant | 108,111 [107,287] | 31,929 [31,095] | **22.80%** [22.47%] |

Not run: neural alone on miniF2F; best-of-17 on miniF2F and for Qwen.
