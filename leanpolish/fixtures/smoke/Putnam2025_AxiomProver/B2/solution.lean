import Mathlib

open Set Real MeasureTheory Interval intervalIntegral Measure

/-- f(1) > 0 for a strictly increasing nonnegative function -/
lemma f_one_pos
    (f : ℝ → ℝ)
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    0 < f 1 := by
  by_contra h
  push_neg at h
  have h1 : f 1 = 0 := le_antisymm h (hf_nonneg 1 (by simp [Icc, le_refl]))
  have h0_mem : (0 : ℝ) ∈ Icc (0 : ℝ) 1 := by simp [Icc, le_refl]
  have h1_mem : (1 : ℝ) ∈ Icc (0 : ℝ) 1 := by simp [Icc, le_refl]
  have hlt : f 0 < f 1 := hf_mono h0_mem h1_mem (by norm_num : (0 : ℝ) < 1)
  have hge : 0 ≤ f 0 := hf_nonneg 0 h0_mem
  linarith

/-- The integral of f over [0,1] is positive -/
lemma int_f_pos
    (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    0 < ∫ x in (0:ℝ)..1, f x := by
  have hf1_pos : 0 < f 1 := f_one_pos f hf_mono hf_nonneg
  apply integral_pos (by norm_num : (0 : ℝ) < 1) hf_cont
  · intro x hx
    exact hf_nonneg x (Ioc_subset_Icc_self hx)
  · exact ⟨1, right_mem_Icc.mpr (by norm_num), hf1_pos⟩

/-- The integral of f² over [0,1] is positive -/
lemma int_f2_pos
    (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    0 < ∫ x in (0:ℝ)..1, (f x) ^ 2 := by
  have hf1_pos : 0 < f 1 := f_one_pos f hf_mono hf_nonneg
  have hf2_cont : ContinuousOn (fun x => (f x) ^ 2) (Icc 0 1) := hf_cont.pow 2
  apply integral_pos (by norm_num : (0 : ℝ) < 1) hf2_cont
  · intro x hx
    exact sq_nonneg (f x)
  · refine ⟨1, right_mem_Icc.mpr (by norm_num), ?_⟩
    exact sq_pos_of_pos hf1_pos

/-- The symmetric integrand f(x)f(y)(x-y)(f(x)-f(y)) -/
def psi (f : ℝ → ℝ) : ℝ × ℝ → ℝ :=
  fun p => f p.1 * f p.2 * (p.1 - p.2) * (f p.1 - f p.2)

/-- The helper function theta(x,y) = x * f(x) * f(y) * (f(x) - f(y)) -/
def theta (f : ℝ → ℝ) : ℝ × ℝ → ℝ :=
  fun p => p.1 * f p.1 * f p.2 * (f p.1 - f p.2)

/-- Algebraic identity: the integrand difference equals theta -/
lemma integrand_diff_eq_theta (f : ℝ → ℝ) (p : ℝ × ℝ) :
    f p.2 * (p.1 * (f p.1)^2) - (p.1 * f p.1) * (f p.2)^2 = theta f p := by
  simp only [theta]
  ring

/-- theta(x,y) + theta(y,x) = psi(x,y) -/
lemma theta_sum_eq_psi (f : ℝ → ℝ) (p : ℝ × ℝ) :
    theta f p + theta f (p.2, p.1) = psi f p := by
  simp only [theta, psi]
  ring

/-- Convert interval integrals to set integrals -/
lemma interval_eq_set (g : ℝ → ℝ) :
    ∫ x in (0:ℝ)..1, g x = ∫ x in Icc 0 1, g x := by
  rw [intervalIntegral.integral_of_le (by norm_num : (0 : ℝ) ≤ 1)]
  rw [integral_Icc_eq_integral_Ioc]

/-- psi is continuous on I × I when f is continuous on I -/
lemma psi_continuousOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    ContinuousOn (psi f) (Icc 0 1 ×ˢ Icc 0 1) := by
  unfold psi
  apply ContinuousOn.mul
  · apply ContinuousOn.mul
    · apply ContinuousOn.mul
      · exact hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)
      · exact hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)
    · exact continuousOn_fst.sub continuousOn_snd
  · apply ContinuousOn.sub
    · exact hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)
    · exact hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)

/-- psi is integrable on the product set -/
lemma psi_integrableOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    IntegrableOn (psi f) (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume) := by
  have hcompact : IsCompact (Icc (0 : ℝ) 1 ×ˢ Icc (0 : ℝ) 1) :=
    isCompact_Icc.prod isCompact_Icc
  exact (psi_continuousOn f hf_cont).integrableOn_compact hcompact

/-- theta is continuous on I × I when f is continuous on I -/
lemma theta_continuousOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    ContinuousOn (theta f) (Icc 0 1 ×ˢ Icc 0 1) := by
  unfold theta
  apply ContinuousOn.mul
  · apply ContinuousOn.mul
    · apply ContinuousOn.mul
      · exact continuousOn_fst
      · exact hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)
    · exact hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)
  · apply ContinuousOn.sub
    · exact hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)
    · exact hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)

/-- theta is integrable on the product set -/
lemma theta_integrableOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    IntegrableOn (theta f) (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume) :=
  (theta_continuousOn f hf_cont).integrableOn_compact (isCompact_Icc.prod isCompact_Icc)

/-- theta ∘ swap is integrable on the product set -/
lemma theta_swap_integrableOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    IntegrableOn (fun p => theta f (p.2, p.1)) (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume) := by
  have hcompact : IsCompact (Icc (0 : ℝ) 1 ×ˢ Icc (0 : ℝ) 1) := isCompact_Icc.prod isCompact_Icc
  have h := theta_continuousOn f hf_cont
  have hswap_cont : ContinuousOn (Prod.swap : ℝ × ℝ → ℝ × ℝ) (Icc 0 1 ×ˢ Icc 0 1) :=
    continuous_swap.continuousOn
  have hswap_maps : MapsTo (Prod.swap : ℝ × ℝ → ℝ × ℝ) (Icc 0 1 ×ˢ Icc 0 1) (Icc 0 1 ×ˢ Icc 0 1) := by
    intro p hp
    simp only [Prod.swap, mem_prod] at hp ⊢
    exact ⟨hp.2, hp.1⟩
  exact (h.comp hswap_cont hswap_maps).integrableOn_compact hcompact

/-- Continuity for the first integrand -/
lemma integrand1_continuousOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    ContinuousOn (fun p : ℝ × ℝ => f p.2 * (p.1 * (f p.1)^2)) (Icc 0 1 ×ˢ Icc 0 1) := by
  apply ContinuousOn.mul
  · exact hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)
  · apply ContinuousOn.mul continuousOn_fst
    exact (hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)).pow 2

/-- Continuity for the second integrand -/
lemma integrand2_continuousOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    ContinuousOn (fun p : ℝ × ℝ => (p.1 * f p.1) * (f p.2)^2) (Icc 0 1 ×ˢ Icc 0 1) := by
  apply ContinuousOn.mul
  · apply ContinuousOn.mul continuousOn_fst
    exact hf_cont.comp continuousOn_fst (fun p hp => (mem_prod.mp hp).1)
  · exact (hf_cont.comp continuousOn_snd (fun p hp => (mem_prod.mp hp).2)).pow 2

/-- Integrability for the first integrand -/
lemma integrand1_integrableOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    IntegrableOn (fun p : ℝ × ℝ => f p.2 * (p.1 * (f p.1)^2)) (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume) :=
  (integrand1_continuousOn f hf_cont).integrableOn_compact (isCompact_Icc.prod isCompact_Icc)

/-- Integrability for the second integrand -/
lemma integrand2_integrableOn (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    IntegrableOn (fun p : ℝ × ℝ => (p.1 * f p.1) * (f p.2)^2) (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume) :=
  (integrand2_continuousOn f hf_cont).integrableOn_compact (isCompact_Icc.prod isCompact_Icc)

/-- First product of integrals equals a double integral -/
lemma prod1_eq_double (f : ℝ → ℝ) (_hf_cont : ContinuousOn f (Icc 0 1)) :
    (∫ x in Icc 0 1, f x) * (∫ x in Icc 0 1, x * (f x)^2) =
    ∫ p in (Icc 0 1 ×ˢ Icc 0 1), f p.2 * (p.1 * (f p.1)^2) ∂(volume.prod volume) := by
  rw [mul_comm]
  have := setIntegral_prod_mul (L := ℝ) (fun x : ℝ => x * (f x)^2) (fun y : ℝ => f y)
            (Icc (0:ℝ) 1) (Icc (0:ℝ) 1) (μ := volume) (ν := volume)
  simp only at this
  convert this.symm using 2
  ext p
  ring

/-- Second product of integrals equals a double integral -/
lemma prod2_eq_double (f : ℝ → ℝ) (_hf_cont : ContinuousOn f (Icc 0 1)) :
    (∫ x in Icc 0 1, x * f x) * (∫ x in Icc 0 1, (f x)^2) =
    ∫ p in (Icc 0 1 ×ˢ Icc 0 1), (p.1 * f p.1) * (f p.2)^2 ∂(volume.prod volume) := by
  have := setIntegral_prod_mul (L := ℝ) (fun x : ℝ => x * f x) (fun y : ℝ => (f y)^2)
            (Icc (0:ℝ) 1) (Icc (0:ℝ) 1) (μ := volume) (ν := volume)
  simp only at this
  exact this.symm

/-- The difference of products equals the theta integral -/
lemma diff_eq_theta_integral (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    (∫ x in Icc 0 1, f x) * (∫ x in Icc 0 1, x * (f x)^2) -
    (∫ x in Icc 0 1, x * f x) * (∫ x in Icc 0 1, (f x)^2) =
    ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f p ∂(volume.prod volume) := by
  rw [prod1_eq_double f hf_cont, prod2_eq_double f hf_cont]
  rw [← integral_sub (integrand1_integrableOn f hf_cont) (integrand2_integrableOn f hf_cont)]
  have hmeas : MeasurableSet (Icc (0 : ℝ) 1 ×ˢ Icc (0 : ℝ) 1) := measurableSet_Icc.prod measurableSet_Icc
  refine setIntegral_congr_fun hmeas ?_
  intro p _
  exact integrand_diff_eq_theta f p

/-- Swapping integration order on a symmetric domain gives the same result -/
lemma setIntegral_swap (g : ℝ × ℝ → ℝ)
    (_hg : IntegrableOn g (Icc 0 1 ×ˢ Icc 0 1) (volume.prod volume)) :
    ∫ z in (Icc 0 1 ×ˢ Icc 0 1), g (z.2, z.1) ∂(volume.prod volume) =
    ∫ z in (Icc 0 1 ×ˢ Icc 0 1), g z ∂(volume.prod volume) := by
  have hswap : MeasurableEmbedding (Prod.swap : ℝ × ℝ → ℝ × ℝ) :=
    MeasurableEquiv.measurableEmbedding (MeasurableEquiv.prodComm : ℝ × ℝ ≃ᵐ ℝ × ℝ)
  have hS_symm : (Prod.swap : ℝ × ℝ → ℝ × ℝ) ⁻¹' (Icc 0 1 ×ˢ Icc 0 1) = Icc 0 1 ×ˢ Icc 0 1 := by
    ext p; simp only [mem_preimage, Prod.swap, mem_prod, mem_Icc]
    exact ⟨fun ⟨h1, h2⟩ => ⟨h2, h1⟩, fun ⟨h1, h2⟩ => ⟨h2, h1⟩⟩
  have h1 : ∫ z in (Icc 0 1 ×ˢ Icc 0 1), g z ∂(Measure.map Prod.swap (volume.prod volume)) =
            ∫ w in Prod.swap ⁻¹' (Icc 0 1 ×ˢ Icc 0 1), g (Prod.swap w) ∂(volume.prod volume) :=
    hswap.setIntegral_map g _
  rw [prod_swap] at h1
  have h2 : ∫ w in (Prod.swap : ℝ × ℝ → ℝ × ℝ) ⁻¹' (Icc 0 1 ×ˢ Icc 0 1), g (Prod.swap w) ∂(volume.prod volume) =
            ∫ w in (Icc 0 1 ×ˢ Icc 0 1), g (Prod.swap w) ∂(volume.prod volume) := by
    apply setIntegral_congr_set
    exact Filter.EventuallyEq.of_eq hS_symm
  rw [h2] at h1
  have h3 : (fun z : ℝ × ℝ => g (z.2, z.1)) = (fun z => g (Prod.swap z)) := rfl
  simp_rw [h3]
  exact h1.symm

/-- 2 * ∫∫ theta = ∫∫ psi -/
lemma two_theta_eq_psi (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    2 * ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f p ∂(volume.prod volume) =
    ∫ p in (Icc 0 1 ×ˢ Icc 0 1), psi f p ∂(volume.prod volume) := by
  have h_theta := theta_integrableOn f hf_cont
  have h_theta_swap := theta_swap_integrableOn f hf_cont
  have hmeas : MeasurableSet (Icc (0 : ℝ) 1 ×ˢ Icc (0 : ℝ) 1) := measurableSet_Icc.prod measurableSet_Icc
  have h1 : ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f p ∂(volume.prod volume) +
            ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f (p.2, p.1) ∂(volume.prod volume) =
            ∫ p in (Icc 0 1 ×ˢ Icc 0 1), psi f p ∂(volume.prod volume) := by
    rw [← integral_add h_theta h_theta_swap]
    refine setIntegral_congr_fun hmeas ?_
    intro p _
    exact theta_sum_eq_psi f p
  have h2 : ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f (p.2, p.1) ∂(volume.prod volume) =
            ∫ p in (Icc 0 1 ×ˢ Icc 0 1), theta f p ∂(volume.prod volume) := by
    exact setIntegral_swap (theta f) h_theta
  rw [h2] at h1
  linarith

/-- psi is nonnegative on I × I for strictly increasing nonnegative f -/
lemma psi_nonneg (f : ℝ → ℝ) (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x)
    (p : ℝ × ℝ) (hp : p ∈ Icc 0 1 ×ˢ Icc 0 1) :
    0 ≤ psi f p := by
  simp only [psi]
  have hp1 : p.1 ∈ Icc (0 : ℝ) 1 := (mem_prod.mp hp).1
  have hp2 : p.2 ∈ Icc (0 : ℝ) 1 := (mem_prod.mp hp).2
  have hf1 : 0 ≤ f p.1 := hf_nonneg p.1 hp1
  have hf2 : 0 ≤ f p.2 := hf_nonneg p.2 hp2
  have hmono : 0 ≤ (p.1 - p.2) * (f p.1 - f p.2) := by
    rcases lt_trichotomy p.1 p.2 with h | h | h
    · have hf_lt : f p.1 < f p.2 := hf_mono hp1 hp2 h
      have h1 : p.1 - p.2 ≤ 0 := le_of_lt (sub_neg_of_lt h)
      have h2 : f p.1 - f p.2 ≤ 0 := le_of_lt (sub_neg_of_lt hf_lt)
      have : -(p.1 - p.2) * -(f p.1 - f p.2) = (p.1 - p.2) * (f p.1 - f p.2) := by ring
      rw [← this]
      apply mul_nonneg <;> linarith
    · simp [h]
    · have hf_gt : f p.1 > f p.2 := hf_mono hp2 hp1 h
      exact mul_nonneg (le_of_lt (sub_pos_of_lt h)) (le_of_lt (sub_pos_of_lt hf_gt))
  have hprod : 0 ≤ f p.1 * f p.2 := mul_nonneg hf1 hf2
  calc f p.1 * f p.2 * (p.1 - p.2) * (f p.1 - f p.2)
      = (f p.1 * f p.2) * ((p.1 - p.2) * (f p.1 - f p.2)) := by ring
    _ ≥ 0 := mul_nonneg hprod hmono

/-- psi is nonneg almost everywhere on the restricted measure -/
lemma psi_nonneg_ae (f : ℝ → ℝ)
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    ∀ᵐ p ∂(volume.prod volume).restrict (Icc 0 1 ×ˢ Icc 0 1), 0 ≤ psi f p := by
  have hmeas : MeasurableSet (Icc (0 : ℝ) 1 ×ˢ Icc (0 : ℝ) 1) :=
    measurableSet_Icc.prod measurableSet_Icc
  filter_upwards [ae_restrict_mem hmeas] with p hp
  exact psi_nonneg f hf_mono hf_nonneg p hp

/-- There exists a neighborhood of 1 where f is strictly positive -/
lemma f_pos_near_one (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    ∃ (δ : ℝ), 0 < δ ∧ δ ≤ 1/2 ∧ ∀ x ∈ Ioo (1 - δ) 1, 0 < f x := by
  have hf1 : 0 < f 1 := f_one_pos f hf_mono hf_nonneg
  have h1_mem : (1 : ℝ) ∈ Icc (0 : ℝ) 1 := by simp [Icc]
  have hcont := hf_cont 1 h1_mem
  rw [ContinuousWithinAt, Metric.tendsto_nhdsWithin_nhds] at hcont
  obtain ⟨δ₀, hδ₀_pos, hδ₀⟩ := hcont (f 1 / 2) (half_pos hf1)
  set δ := min δ₀ (1/2) with hδ_def
  use δ
  refine ⟨lt_min hδ₀_pos (by norm_num : (0 : ℝ) < 1/2), min_le_right δ₀ (1/2), ?_⟩
  intro x hx
  have hxmem : x ∈ Icc (0 : ℝ) 1 := by
    constructor
    · have := hx.1
      have hpos : 0 < δ := lt_min hδ₀_pos (by norm_num : (0 : ℝ) < 1/2)
      have hle : δ ≤ 1/2 := min_le_right δ₀ (1/2)
      linarith
    · exact le_of_lt hx.2
  have hdist : dist x 1 < δ₀ := by
    rw [Real.dist_eq, abs_sub_comm]
    rw [abs_of_nonneg (by linarith [hx.2] : 0 ≤ 1 - x)]
    have h1 : 1 - x < δ := by linarith [hx.1, hx.2]
    have h2 : δ ≤ δ₀ := min_le_left δ₀ (1/2)
    linarith
  have := hδ₀ hxmem hdist
  rw [Real.dist_eq] at this
  have hf_close : |f x - f 1| < f 1 / 2 := this
  have := abs_sub_lt_iff.mp hf_close
  linarith

/-- The support of psi intersected with I × I has positive measure.
    Specifically, psi is positive where x ≠ y and f(x), f(y) > 0. -/
lemma psi_support_pos (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    0 < (volume.prod volume) (Function.support (psi f) ∩ (Icc 0 1 ×ˢ Icc 0 1)) := by
  obtain ⟨δ, hδ_pos, hδ_le, hf_pos⟩ := f_pos_near_one f hf_cont hf_mono hf_nonneg
  set S := Ioo (1 - δ) (1 - δ/2) ×ˢ Ioo (1 - δ/2) 1 with hS_def
  have hS_subset_support : S ⊆ Function.support (psi f) := by
    intro p hp
    rw [Function.mem_support]
    simp only [psi, ne_eq]
    have hp1 : p.1 ∈ Ioo (1 - δ) (1 - δ/2) := (mem_prod.mp hp).1
    have hp2 : p.2 ∈ Ioo (1 - δ/2) 1 := (mem_prod.mp hp).2
    have hp1' : p.1 ∈ Ioo (1 - δ) 1 := ⟨hp1.1, by linarith [hp1.2]⟩
    have hp2' : p.2 ∈ Ioo (1 - δ) 1 := ⟨by linarith [hp2.1, hδ_pos], hp2.2⟩
    have hfp1 : 0 < f p.1 := hf_pos p.1 hp1'
    have hfp2 : 0 < f p.2 := hf_pos p.2 hp2'
    have hxy : p.1 < p.2 := by linarith [hp1.2, hp2.1]
    have hp1_mem : p.1 ∈ Icc (0 : ℝ) 1 := ⟨by linarith [hp1.1, hδ_le], le_of_lt (by linarith [hp1.2])⟩
    have hp2_mem : p.2 ∈ Icc (0 : ℝ) 1 := ⟨by linarith [hp2.1, hδ_le, hδ_pos], le_of_lt hp2.2⟩
    have hfxy : f p.1 < f p.2 := hf_mono hp1_mem hp2_mem hxy
    have h1 : f p.1 * f p.2 > 0 := mul_pos hfp1 hfp2
    have h2 : (p.1 - p.2) * (f p.1 - f p.2) > 0 := by
      have : p.1 - p.2 < 0 := sub_neg_of_lt hxy
      have : f p.1 - f p.2 < 0 := sub_neg_of_lt hfxy
      have : -(p.1 - p.2) * -(f p.1 - f p.2) = (p.1 - p.2) * (f p.1 - f p.2) := by ring
      rw [← this]
      apply mul_pos <;> linarith
    have : f p.1 * f p.2 * (p.1 - p.2) * (f p.1 - f p.2) > 0 := by
      calc f p.1 * f p.2 * (p.1 - p.2) * (f p.1 - f p.2)
          = (f p.1 * f p.2) * ((p.1 - p.2) * (f p.1 - f p.2)) := by ring
        _ > 0 := mul_pos h1 h2
    linarith
  have hS_subset_I : S ⊆ Icc 0 1 ×ˢ Icc 0 1 := by
    intro p hp
    have hp1 : p.1 ∈ Ioo (1 - δ) (1 - δ/2) := (mem_prod.mp hp).1
    have hp2 : p.2 ∈ Ioo (1 - δ/2) 1 := (mem_prod.mp hp).2
    exact mem_prod.mpr ⟨⟨by linarith [hp1.1, hδ_le], le_of_lt (by linarith [hp1.2])⟩,
                         ⟨by linarith [hp2.1, hδ_le, hδ_pos], le_of_lt hp2.2⟩⟩
  have hS_subset : S ⊆ Function.support (psi f) ∩ (Icc 0 1 ×ˢ Icc 0 1) :=
    subset_inter hS_subset_support hS_subset_I
  have hS_meas : (volume.prod volume) S = ENNReal.ofReal (δ/2) * ENNReal.ofReal (δ/2) := by
    rw [Measure.prod_prod]
    congr 1
    · rw [volume_Ioo]
      congr 1
      ring
    · rw [volume_Ioo]
      congr 1
      ring
  have hpos : 0 < δ/2 := by linarith
  have hne : ENNReal.ofReal (δ/2) ≠ 0 := by
    rw [ne_eq, ENNReal.ofReal_eq_zero]
    linarith
  have hS_pos : 0 < (volume.prod volume) S := by
    rw [hS_meas]
    exact ENNReal.mul_pos hne hne
  exact lt_of_lt_of_le hS_pos (measure_mono hS_subset)

/-- The double integral of psi over I × I is positive -/
lemma psi_integral_pos (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    0 < ∫ p in (Icc 0 1 ×ˢ Icc 0 1), psi f p ∂(volume.prod volume) := by
  have hae := psi_nonneg_ae f hf_mono hf_nonneg
  have hint := psi_integrableOn f hf_cont
  have h_support := psi_support_pos f hf_cont hf_mono hf_nonneg
  rw [setIntegral_pos_iff_support_of_nonneg_ae hae hint]
  exact h_support

/-- The key algebraic identity: the product difference equals half the double integral of psi.
    (∫f)(∫xf²) - (∫xf)(∫f²) = (1/2) ∫∫ f(x)f(y)(x-y)(f(x)-f(y)) dx dy -/
lemma key_identity (f : ℝ → ℝ) (hf_cont : ContinuousOn f (Icc 0 1)) :
    (∫ x in (0:ℝ)..1, f x) * (∫ x in (0:ℝ)..1, x * (f x) ^ 2) -
    (∫ x in (0:ℝ)..1, x * f x) * (∫ x in (0:ℝ)..1, (f x) ^ 2) =
    (1/2) * ∫ p in (Icc 0 1 ×ˢ Icc 0 1), psi f p ∂(volume.prod volume) := by
  simp_rw [interval_eq_set]
  rw [diff_eq_theta_integral f hf_cont]
  have h := two_theta_eq_psi f hf_cont
  linarith

/-- The main cross-multiplication inequality:
    (∫ f)(∫ xf²) > (∫ xf)(∫ f²)
    which is equivalent to (1/2) ∫∫ f(x)f(y)(x-y)(f(x)-f(y)) dx dy > 0 -/
lemma main_inequality
    (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    (∫ x in (0:ℝ)..1, f x) * (∫ x in (0:ℝ)..1, x * (f x) ^ 2) >
    (∫ x in (0:ℝ)..1, x * f x) * (∫ x in (0:ℝ)..1, (f x) ^ 2) := by
  have h_key := key_identity f hf_cont
  have h_psi_pos := psi_integral_pos f hf_cont hf_mono hf_nonneg
  linarith

/--
Let $f: [0,1] \to [0, \infty)$ be strictly increasing and continuous.
Let $R$ be the region bounded by $x = 0$, $x = 1$, $y = 0$, and $y = f(x)$.
Let $x_1$ be the $x$-coordinate of the centroid of $R$.
Let $x_2$ be the $x$-coordinate of the centroid of the solid generated by rotating $R$ about the $x$-axis.
Prove that $x_1 < x_2$.
-/
theorem putnam_2025_b2
    (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Icc 0 1))
    (hf_mono : StrictMonoOn f (Icc 0 1))
    (hf_nonneg : ∀ x ∈ Icc (0 : ℝ) 1, 0 ≤ f x) :
    (∫ x in (0:ℝ)..1, x * f x) / (∫ x in (0:ℝ)..1, f x) <
    (∫ x in (0:ℝ)..1, x * (f x) ^ 2) / (∫ x in (0:ℝ)..1, (f x) ^ 2) := by
  have h_int_f_pos : 0 < ∫ x in (0:ℝ)..1, f x := int_f_pos f hf_cont hf_mono hf_nonneg
  have h_int_f2_pos : 0 < ∫ x in (0:ℝ)..1, (f x) ^ 2 := int_f2_pos f hf_cont hf_mono hf_nonneg
  have h_main : (∫ x in (0:ℝ)..1, f x) * (∫ x in (0:ℝ)..1, x * (f x) ^ 2) >
                (∫ x in (0:ℝ)..1, x * f x) * (∫ x in (0:ℝ)..1, (f x) ^ 2) :=
    main_inequality f hf_cont hf_mono hf_nonneg
  rw [div_lt_div_iff₀ h_int_f_pos h_int_f2_pos]
  linarith
