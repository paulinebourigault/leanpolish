| Corpus | Method | k | **Red. A** | Red. B (appL) | files improved (A) | gen tokens | GPU-s | unique compiles | compile pass | samples verified |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| miniF2F-100 (99 files; A 38,040 tok) | LeanPolish alone | - | **20.02%** | 20.53% | 91 | - | CPU only | - | - | - |
| miniF2F-100 | Frozen, SFT prompt (whole file) | 4 | **4.34%** | 4.66% | 7 | 258,511 | 279 | 17 | 59% | 3% |
| miniF2F-100 | Frozen, SFT prompt (whole file) | 16 | **6.83%** | 7.31% | 13 | 1,040,052 | 1041 | 54 | 61% | 3% |
| miniF2F-100 | Frozen, C2 prompt (theorem, spliced) | 4 | **10.16%** | 12.47% | 28 | 245,197 | 274 | 67 | 87% | 17% |
| miniF2F-100 | Frozen, C2 prompt (theorem, spliced) | 16 | **12.52%** | 15.02% | 38 | 998,947 | 1036 | 174 | 86% | 16% |
| miniF2F-100 | LeanPolish-SFT optimizer | 4 | **12.76%** | 13.52% | 82 | 249,456 | 287 | 165 | 87% | 62% |
| miniF2F-100 | LeanPolish-SFT optimizer | 16 | **16.36%** | 17.66% | 87 | 1,004,206 | 1029 | 404 | 88% | 62% |
| miniF2F-100 | LeanPolish, then SFT optimizer | 4 | **24.66%** | 25.25% | 95 | 214,320 | 237 | 90 | 76% | 22% |
| miniF2F-100 | LeanPolish, then SFT optimizer | 16 | **27.13%** | 27.73% | 95 | 854,621 | 865 | 254 | 72% | 21% |
| miniF2F-100 | per-file min(SFT optimizer, LeanPolish) | 4 | **22.54%** | | SFT<LP on 15, LP<SFT on 49 | | | | | |
| miniF2F-100 | per-file min(SFT optimizer, LeanPolish) | 16 | **23.88%** | | SFT<LP on 25, LP<SFT on 37 | | | | | |
| PutnamBench-verified (19 files; A 22,116 tok) | LeanPolish alone | - | **6.14%** | 5.80% | 15 | - | CPU only | - | - | - |
| PutnamBench-verified | Frozen, SFT prompt (whole file) | 4 | **1.23%** | 1.31% | 5 | 146,666 | 156 | 11 | 55% | 10% |
| PutnamBench-verified | Frozen, SFT prompt (whole file) | 16 | **1.92%** | 1.98% | 6 | 580,586 | 581 | 45 | 36% | 10% |
| PutnamBench-verified | Frozen, C2 prompt (theorem, spliced) | 4 | **1.23%** | 1.88% | 4 | 142,456 | 154 | 13 | 54% | 10% |
| PutnamBench-verified | Frozen, C2 prompt (theorem, spliced) | 16 | **3.05%** | 4.15% | 6 | 564,261 | 585 | 50 | 44% | 10% |
| PutnamBench-verified | LeanPolish-SFT optimizer | 4 | **1.74%** | 1.66% | 9 | 140,035 | 157 | 45 | 27% | 20% |
| PutnamBench-verified | LeanPolish-SFT optimizer | 16 | **5.53%** | 5.28% | 13 | 548,646 | 562 | 128 | 30% | 23% |
| PutnamBench-verified | LeanPolish, then SFT optimizer | 4 | **6.79%** | 6.38% | 16 | 128,617 | 142 | 42 | 24% | 17% |
| PutnamBench-verified | LeanPolish, then SFT optimizer | 16 | **8.36%** | 7.85% | 17 | 511,185 | 518 | 115 | 30% | 17% |
| PutnamBench-verified | per-file min(SFT optimizer, LeanPolish) | 4 | **6.32%** | | SFT<LP on 4, LP<SFT on 13 | | | | | |
| PutnamBench-verified | per-file min(SFT optimizer, LeanPolish) | 16 | **7.39%** | | SFT<LP on 8, LP<SFT on 10 | | | | | |
| Putnam2025-AxiomProver (12 files; A 133,686 tok) | LeanPolish alone | - | **1.31%** | 1.06% | 10 | - | CPU only | - | - | - |
| Putnam2025-AxiomProver | Frozen, SFT prompt (whole file) | 4 | **0.00%** | 0.00% | 0 | 5,272 | 48 | 0 | - | 0% |
| Putnam2025-AxiomProver | LeanPolish-SFT optimizer | 4 | **0.00%** | 0.00% | 0 | 105,433 | 412 | 4 | 0% | 0% |
| Putnam2025-AxiomProver | LeanPolish, then SFT optimizer | 4 | **1.31%** | 1.06% | 10 | 101,552 | 386 | 6 | 17% | 8% |
| Putnam2025-AxiomProver | per-file min(SFT optimizer, LeanPolish) | 4 | **1.31%** | | SFT<LP on 0, LP<SFT on 10 | | | | | |
