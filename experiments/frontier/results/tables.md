
#### Editor `deepseek:main`, counter A = countLeanTokens port (primary)

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 5,064 | 15 (0.30%) | 62 (1.22%) [+47] | 62 (1.22%) [+47] | 26 (0.51%) [+11] | 26 (0.51%) [+11] |
| aristotle/P5 | 9,501 | 0 (0.00%) (no teacher output) | 119 (1.25%) [+119] | 119 (1.25%) [+119] | 90 (0.95%) [+90] | 90 (0.95%) [+90] |
| seed/A1 | 9,105 | 370 (4.06%) | 469 (5.15%) [+99] | 492 (5.40%) [+122] | 391 (4.29%) [+21] | 396 (4.35%) [+26] |
| seed/A2 | 6,115 | 400 (6.54%) | 627 (10.25%) [+227] | 699 (11.43%) [+299] | 515 (8.42%) [+115] | 587 (9.60%) [+187] |
| seed/A4 | 14,567 | 378 (2.59%) | 755 (5.18%) [+377] | 783 (5.38%) [+405] | 563 (3.86%) [+185] | 582 (4.00%) [+204] |
| seed/A6 | 14,797 | 457 (3.09%) | 708 (4.78%) [+251] | 722 (4.88%) [+265] | 534 (3.61%) [+77] | 537 (3.63%) [+80] |
| seed/B2 | 27,478 | 1,702 (6.19%) | 2,250 (8.19%) [+548] | 2,309 (8.40%) [+607] | 1,944 (7.07%) [+242] | 1,984 (7.22%) [+282] |
| seed/B4 | 8,503 | 214 (2.52%) | 318 (3.74%) [+104] | 322 (3.79%) [+108] | 249 (2.93%) [+35] | 251 (2.95%) [+37] |
| **Total** | **95,130** | **3,536 (3.72%)** | **5,308 (5.58%)** [+1,772] | **5,508 (5.79%)** [+1,972] | **4,312 (4.53%)** [+776] | **4,453 (4.68%)** [+917] |

#### Editor `deepseek:main`, counter B = count_appL

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 7,596 | 13 (0.17%) | 50 (0.66%) [+37] | 50 (0.66%) [+37] | 20 (0.26%) [+7] | 20 (0.26%) [+7] |
| aristotle/P5 | 11,742 | 0 (0.00%) (no teacher output) | 83 (0.71%) [+83] | 83 (0.71%) [+83] | 58 (0.49%) [+58] | 58 (0.49%) [+58] |
| seed/A1 | 8,489 | 344 (4.05%) | 434 (5.11%) [+90] | 450 (5.30%) [+106] | 365 (4.30%) [+21] | 369 (4.35%) [+25] |
| seed/A2 | 5,553 | 346 (6.23%) | 524 (9.44%) [+178] | 590 (10.62%) [+244] | 424 (7.64%) [+78] | 490 (8.82%) [+144] |
| seed/A4 | 13,872 | 352 (2.54%) | 680 (4.90%) [+328] | 706 (5.09%) [+354] | 520 (3.75%) [+168] | 537 (3.87%) [+185] |
| seed/A6 | 14,521 | 455 (3.13%) | 700 (4.82%) [+245] | 714 (4.92%) [+259] | 528 (3.64%) [+73] | 531 (3.66%) [+76] |
| seed/B2 | 24,668 | 1,578 (6.40%) | 2,034 (8.25%) [+456] | 2,089 (8.47%) [+511] | 1,779 (7.21%) [+201] | 1,819 (7.37%) [+241] |
| seed/B4 | 7,769 | 214 (2.75%) | 313 (4.03%) [+99] | 319 (4.11%) [+105] | 246 (3.17%) [+32] | 250 (3.22%) [+36] |
| **Total** | **94,210** | **3,302 (3.50%)** | **4,818 (5.11%)** [+1,516] | **5,001 (5.31%)** [+1,699] | **3,940 (4.18%)** [+638] | **4,074 (4.32%)** [+772] |

Pipeline counts (`deepseek:main`):

| File | sites | sites w/ shorter cand | unique shorter cands | screen pass | verify pass | kept joint raw G+16 | of which filter-ok | kept joint filter G+16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 256 | 184 | 407 | 12 | 8 | 7 | 3 | 3 |
| aristotle/P5 | 552 | 343 | 659 | 41 | 19 | 16 | 8 | 8 |
| seed/A1 | 319 | 256 | 592 | 59 | 59 | 45 | 8 | 8 |
| seed/A2 | 282 | 202 | 434 | 75 | 74 | 60 | 27 | 27 |
| seed/A4 | 708 | 527 | 993 | 142 | 142 | 120 | 47 | 47 |
| seed/A6 | 470 | 368 | 692 | 79 | 79 | 61 | 14 | 14 |
| seed/B2 | 930 | 750 | 1510 | 229 | 229 | 182 | 62 | 62 |
| seed/B4 | 338 | 241 | 593 | 41 | 41 | 35 | 10 | 10 |

All final files verified (fresh `lake env lean`, no error, no sorry): True

#### Editor `deepseek:ext`, counter A = countLeanTokens port (primary)

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 5,064 | 15 (0.30%) | 68 (1.34%) [+53] | 69 (1.36%) [+54] | 32 (0.63%) [+17] | 33 (0.65%) [+18] |
| seed/A1 | 9,105 | 370 (4.06%) | 497 (5.46%) [+127] | 559 (6.14%) [+189] | 418 (4.59%) [+48] | 461 (5.06%) [+91] |
| seed/A2 | 6,115 | 400 (6.54%) | 642 (10.50%) [+242] | 719 (11.76%) [+319] | 527 (8.62%) [+127] | 604 (9.88%) [+204] |
| seed/A4 | 14,567 | 378 (2.59%) | 805 (5.53%) [+427] | 867 (5.95%) [+489] | 601 (4.13%) [+223] | 646 (4.43%) [+268] |
| seed/A6 | 14,797 | 457 (3.09%) | 775 (5.24%) [+318] | 797 (5.39%) [+340] | 572 (3.87%) [+115] | 587 (3.97%) [+130] |
| seed/B4 | 8,503 | 214 (2.52%) | 436 (5.13%) [+222] | 463 (5.45%) [+249] | 315 (3.70%) [+101] | 320 (3.76%) [+106] |
| **Total** | **58,151** | **1,834 (3.15%)** | **3,223 (5.54%)** [+1,389] | **3,474 (5.97%)** [+1,640] | **2,465 (4.24%)** [+631] | **2,651 (4.56%)** [+817] |

#### Editor `deepseek:ext`, counter B = count_appL

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 7,596 | 13 (0.17%) | 52 (0.68%) [+39] | 53 (0.70%) [+40] | 22 (0.29%) [+9] | 23 (0.30%) [+10] |
| seed/A1 | 8,489 | 344 (4.05%) | 459 (5.41%) [+115] | 516 (6.08%) [+172] | 389 (4.58%) [+45] | 433 (5.10%) [+89] |
| seed/A2 | 5,553 | 346 (6.23%) | 537 (9.67%) [+191] | 608 (10.95%) [+262] | 436 (7.85%) [+90] | 507 (9.13%) [+161] |
| seed/A4 | 13,872 | 352 (2.54%) | 726 (5.23%) [+374] | 784 (5.65%) [+432] | 554 (3.99%) [+202] | 597 (4.30%) [+245] |
| seed/A6 | 14,521 | 455 (3.13%) | 763 (5.25%) [+308] | 785 (5.41%) [+330] | 562 (3.87%) [+107] | 577 (3.97%) [+122] |
| seed/B4 | 7,769 | 214 (2.75%) | 417 (5.37%) [+203] | 446 (5.74%) [+232] | 302 (3.89%) [+88] | 309 (3.98%) [+95] |
| **Total** | **57,800** | **1,724 (2.98%)** | **2,954 (5.11%)** [+1,230] | **3,192 (5.52%)** [+1,468] | **2,265 (3.92%)** [+541] | **2,446 (4.23%)** [+722] |

Pipeline counts (`deepseek:ext`):

| File | sites | sites w/ shorter cand | unique shorter cands | screen pass | verify pass | kept joint raw G+16 | of which filter-ok | kept joint filter G+16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 256 | 184 | 407 | 12 | 10 | 9 | 5 | 5 |
| seed/A1 | 319 | 256 | 592 | 59 | 75 | 55 | 18 | 18 |
| seed/A2 | 282 | 202 | 434 | 75 | 81 | 66 | 32 | 32 |
| seed/A4 | 708 | 527 | 993 | 142 | 158 | 132 | 55 | 55 |
| seed/A6 | 470 | 368 | 692 | 79 | 102 | 80 | 27 | 27 |
| seed/B4 | 338 | 241 | 593 | 41 | 69 | 58 | 21 | 21 |

All final files verified (fresh `lake env lean`, no error, no sorry): True

#### Editor `qwen:main`, counter A = countLeanTokens port (primary)

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 5,064 | 15 (0.30%) | 32 (0.63%) [+17] | 32 (0.63%) [+17] | 26 (0.51%) [+11] | 26 (0.51%) [+11] |
| seed/A1 | 9,105 | 370 (4.06%) | 488 (5.36%) [+118] | 509 (5.59%) [+139] | 413 (4.54%) [+43] | 415 (4.56%) [+45] |
| seed/A2 | 6,115 | 400 (6.54%) | 634 (10.37%) [+234] | 652 (10.66%) [+252] | 532 (8.70%) [+132] | 534 (8.73%) [+134] |
| seed/A4 | 14,567 | 378 (2.59%) | 875 (6.01%) [+497] | 966 (6.63%) [+588] | 742 (5.09%) [+364] | 747 (5.13%) [+369] |
| seed/A6 | 14,797 | 457 (3.09%) | 762 (5.15%) [+305] | 771 (5.21%) [+314] | 582 (3.93%) [+125] | 582 (3.93%) [+125] |
| seed/B4 | 8,503 | 214 (2.52%) | 301 (3.54%) [+87] | 304 (3.58%) [+90] | 237 (2.79%) [+23] | 240 (2.82%) [+26] |
| **Total** | **58,151** | **1,834 (3.15%)** | **3,092 (5.32%)** [+1,258] | **3,234 (5.56%)** [+1,400] | **2,532 (4.35%)** [+698] | **2,544 (4.37%)** [+710] |

#### Editor `qwen:main`, counter B = count_appL

| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |
|---|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 7,596 | 13 (0.17%) | 26 (0.34%) [+13] | 26 (0.34%) [+13] | 20 (0.26%) [+7] | 20 (0.26%) [+7] |
| seed/A1 | 8,489 | 344 (4.05%) | 453 (5.34%) [+109] | 464 (5.47%) [+120] | 386 (4.55%) [+42] | 388 (4.57%) [+44] |
| seed/A2 | 5,553 | 346 (6.23%) | 526 (9.47%) [+180] | 543 (9.78%) [+197] | 436 (7.85%) [+90] | 437 (7.87%) [+91] |
| seed/A4 | 13,872 | 352 (2.54%) | 786 (5.67%) [+434] | 852 (6.14%) [+500] | 678 (4.89%) [+326] | 681 (4.91%) [+329] |
| seed/A6 | 14,521 | 455 (3.13%) | 748 (5.15%) [+293] | 755 (5.20%) [+300] | 568 (3.91%) [+113] | 568 (3.91%) [+113] |
| seed/B4 | 7,769 | 214 (2.75%) | 295 (3.80%) [+81] | 299 (3.85%) [+85] | 233 (3.00%) [+19] | 237 (3.05%) [+23] |
| **Total** | **57,800** | **1,724 (2.98%)** | **2,834 (4.90%)** [+1,110] | **2,939 (5.08%)** [+1,215] | **2,321 (4.02%)** [+597] | **2,331 (4.03%)** [+607] |

Pipeline counts (`qwen:main`):

| File | sites | sites w/ shorter cand | unique shorter cands | screen pass | verify pass | kept joint raw G+16 | of which filter-ok | kept joint filter G+16 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| aristotle/P3 | 256 | 185 | 468 | 10 | 5 | 5 | 3 | 3 |
| seed/A1 | 319 | 255 | 568 | 55 | 54 | 40 | 5 | 5 |
| seed/A2 | 282 | 208 | 370 | 84 | 83 | 57 | 23 | 23 |
| seed/A4 | 708 | 529 | 1153 | 175 | 175 | 131 | 59 | 56 |
| seed/A6 | 470 | 367 | 850 | 95 | 95 | 68 | 16 | 16 |
| seed/B4 | 338 | 240 | 553 | 45 | 45 | 27 | 5 | 5 |

All final files verified (fresh `lake env lean`, no error, no sorry): True

#### Examples of jointly-kept neural edits (DeepSeek, raw G+16; sorted by appL savings; Seed-Prover files only, since Aristotle files are not redistributed)


Filter-compliant:

- `seed/A2` (saves A 31, appL 29; budget g16)
  - goal: `h2 : ∀ (t : ℝ), -π / 2 ≤ t ∧ t ≤ π / 2 → cos t ≤ 1 - 4 / π ^ 2 * t ^ 2 x : ℝ hx : x ∈ Icc 0 π h3 : 0 ≤ x h4 : x ≤ π h5 : -π / 2 ≤ x - π / 2 h6 : x - π / 2 ≤ π / 2 h7 : -π / 2 ≤ x - π / 2 ∧ x - π / 2 ≤ π / 2 ⊢ sin x ≤ 4 / π ^ 2 * x * (π - x)`
  - original: `have h8 : Real.cos (x - π / 2) ≤ 1 - (4 / π ^ 2) * (x - π / 2) ^ 2 := h2 (x - π / 2) h7`
  - neural edit: `have h8 := h2 (x - π / 2) h7`
- `seed/A2` (saves A 27, appL 27; budget g16)
  - goal: `a : ℝ h : ∀ x ∈ Icc 0 π, a * x * (π - x) ≤ sin x z : ℝ hz_pos : 0 < z hz_lt_pi : z < π h_x_pos : 0 < π - z h_x_nonneg : 0 ≤ π - z h_x_in_Icc : π - z ∈ Icc 0 π ⊢ a * (π - z) < 1`
  - original: `have h_main : a * ((π - z)) * (π - (π - z)) ≤ sin (π - z) := h (π - z) h_x_in_Icc`
  - neural edit: `have h_main := h (π - z) h_x_in_Icc`
- `seed/A6` (saves A 26, appL 26; budget g4)
  - goal: `b : ℕ → ℤ lemma5_mod_powers_of_2 : ∀ s ≥ 1, ∀ (n : ℕ), (b (n + 2 ^ s) - b n) % 2 ^ (s + 1) = 0 k : ℕ hk : k ≥ 1 i : ℕ ⊢ (4 * b (i + 2 ^ k) + 1) % 2 ^ (k + 3) = (4 * b i + 1) % 2 ^ (k + 3)`
  - original: `have h1 : (b (i + 2 ^ k) - b i) % (2 ^ (k + 1)) = 0 := lemma5_mod_powers_of_2 k hk i`
  - neural edit: `have h1 := lemma5_mod_powers_of_2 k hk i`
- `seed/A4` (saves A 17, appL 17; budget g4)
  - goal: `case a.«_@».Mathlib.Data.Matrix.Defs._hyg.155.«0».«0» α h : ℝ h21 : α = 2 * Real.pi * 508 / 2025 h22 : h > 0 h23 : h ^ 2 + Real.cos α = 0 x : Fin 2025 → ℝ := fun i => Real.cos (↑↑i * α) y : Fin 2025 → ℝ := fun i => Real.sin (↑↑i * α) z : Fin 2025 → ℝ := fun x => h A : Fin 2025 → Matrix (Fin 3) (Fin 3) ℝ := fun i r s => match r, s with | 0, 0 => x i * x i | 0, 1 => x i * y i | 0, …`
  - original: `simp [A, u, xi, yi, h_val, x, y, z]`
  - neural edit: `norm_cast`
- `seed/A4` (saves A 17, appL 17; budget g4)
  - goal: `case a.«_@».Mathlib.Data.Matrix.Defs._hyg.155.«0».«0» α h : ℝ h21 : α = 2 * Real.pi * 508 / 2025 h22 : h > 0 h23 : h ^ 2 + Real.cos α = 0 x : Fin 2025 → ℝ := fun i => Real.cos (↑↑i * α) y : Fin 2025 → ℝ := fun i => Real.sin (↑↑i * α) z : Fin 2025 → ℝ := fun x => h A : Fin 2025 → Matrix (Fin 3) (Fin 3) ℝ := fun i r s => match r, s with | 0, 0 => x i * x i | 0, 1 => x i * y i | 0, …`
  - original: `simp [A, v, xj, yj, h_val, x, y, z]`
  - neural edit: `norm_cast`

Rejected by the isQualityUpgrade port:

- `seed/A6` (saves A 30, appL 30; budget g4)
  - goal: `k : ℕ hk : k ≥ 1 h2 : 2 * (k + 1) ≥ k + 3 h3 : 2 ^ (k + 3) ∣ 2 ^ (2 * (k + 1)) h_main : (1 + 2 ^ (k + 1)) * (1 + 2 ^ (k + 1)) = 1 + 2 ^ (k + 2) + 2 ^ (2 * (k + 1)) h7 : ∀ (a b : ℤ), 2 ^ (k + 3) ∣ b → (a + b) % 2 ^ (k + 3) = a % 2 ^ (k + 3) ⊢ (1 + 2 ^ (k + 2) + 2 ^ (2 * (k + 1))) % 2 ^ (k + 3) = (1 + 2 ^ (k + 2)) % 2 ^ (k + 3)`
  - original: `exact h7 (1 + 2 ^ (k + 2) : ℤ) (2 ^ (2 * (k + 1)) : ℤ) h3`
  - neural edit: `tauto`
- `seed/A6` (saves A 21, appL 21; budget g4)
  - goal: `case succ.intro.intro.intro g : ℕ → ℤ → ℤ hg1 : ∀ (t : ℤ), g 0 t = t hg2 : ∀ (n : ℕ) (t : ℤ), g (n + 1) t = 2 * g n t ^ 2 + g n t + 1 n : ℕ ih : ∀ (s h : ℤ), h % 2 = 0 → ∃ q, q % 2 = 1 ∧ q % 4 = 1 ∧ g n (s + h) - g n s = h * q s h : ℤ h_h : h % 2 = 0 q : ℤ hq1 : q % 2 = 1 hq2 : q % 4 = 1 x : ℤ := g n s hx : x = g n s y : ℤ := g n (s + h) h_eq : y - x = h * q hy : y = g n (s + h) h_eq2 : y - x = h …`
  - original: `refine' ⟨q * (2 * (x + y) + 1), h6, h7, h_main⟩`
  - neural edit: `tauto`
- `seed/A6` (saves A 12, appL 12; budget g4)
  - goal: `g : ℕ → ℤ → ℤ h_lemma_A : ∀ (n : ℕ) (s h : ℤ), h % 2 = 0 → ∃ q, q % 2 = 1 ∧ q % 4 = 1 ∧ g n (s + h) - g n s = h * q m : ℕ h : ∀ (t : ℤ), ∃ b, g (2 ^ m) t = t + 2 ^ (m + 1) + 2 ^ (m + 2) * b h_add : ∀ (n m : ℕ) (t : ℤ), g (n + m) t = g n (g m t) t b : ℤ hb : g (2 ^ m) t = t + 2 ^ (m + 1) + 2 ^ (m + 2) * b s : ℤ := g (2 ^ m) t h2 : s = t + 2 ^ (m + 1) + 2 ^ (m + 2) * b h_val : ℤ := s - t h3 : h_val …`
  - original: `exact h_add (2 ^ m) (2 ^ m) t`
  - neural edit: `tauto`
- `seed/A2` (saves A 11, appL 11; budget g4)
  - goal: `case left lemma2_ineq : ∀ x ∈ Icc 0 π, sin x ≥ 1 / π * x * (π - x) lemma5_ineq : ∀ x ∈ Icc 0 π, sin x ≤ 4 / π ^ 2 * x * (π - x) optimality_lower : ∀ (a : ℝ), (∀ x ∈ Icc 0 π, a * x * (π - x) ≤ sin x) → a ≤ 1 / π optimality_upper : ∀ (b : ℝ), (∀ x ∈ Icc 0 π, b * x * (π - x) ≥ sin x) → b ≥ 4 / π ^ 2 h11 : 1 / π ∈ {a | ∀ x ∈ Icc 0 π, a * x * (π - x) ≤ sin x} h12 : ∀ a ∈ {a | ∀ x ∈ Icc 0 π, a * x * (π …`
  - original: `exact ⟨h11, fun a ha => h12 a ha⟩`
  - neural edit: `tauto`
- `seed/A2` (saves A 11, appL 11; budget g4)
  - goal: `lemma2_ineq : ∀ x ∈ Icc 0 π, sin x ≥ 1 / π * x * (π - x) lemma5_ineq : ∀ x ∈ Icc 0 π, sin x ≤ 4 / π ^ 2 * x * (π - x) optimality_lower : ∀ (a : ℝ), (∀ x ∈ Icc 0 π, a * x * (π - x) ≤ sin x) → a ≤ 1 / π optimality_upper : ∀ (b : ℝ), (∀ x ∈ Icc 0 π, b * x * (π - x) ≥ sin x) → b ≥ 4 / π ^ 2 h21 : 4 / π ^ 2 ∈ {b | ∀ x ∈ Icc 0 π, b * x * (π - x) ≥ sin x} b : ℝ hb : b ∈ {b | ∀ x ∈ Icc 0 π, b * x * (π - x …`
  - original: `exact optimality_upper b (fun x hx => hb x hx)`
  - neural edit: `tauto`
