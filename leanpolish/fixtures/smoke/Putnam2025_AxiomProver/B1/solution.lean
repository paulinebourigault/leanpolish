import Mathlib

open Affine EuclideanGeometry

/-- Three distinct points on a circle (sphere in 2D) centered at O with positive radius are noncollinear.
    This is because a line intersects a circle in at most 2 points.
    Proof strategy: Assume collinear, then all 3 points lie on a line.
    The line intersects the circle in at most 2 points, contradicting that A, B, C are distinct. -/
lemma three_points_on_sphere_noncollinear
    (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (_hr : 0 < r)
    (A B C : EuclideanSpace ℝ (Fin 2))
    (hA : dist A O = r) (hB : dist B O = r) (hC : dist C O = r)
    (hAB : A ≠ B) (hBC : B ≠ C) (hAC : A ≠ C) :
    ¬Collinear ℝ ({A, B, C} : Set (EuclideanSpace ℝ (Fin 2))) := by
  intro hcol
  rcases hcol.wbtw_or_wbtw_or_wbtw with hw | hw | hw
  · have hsbtw : Sbtw ℝ A B C := ⟨hw, hAB.symm, hBC⟩
    have h := hsbtw.dist_lt_max_dist O
    rw [hA, hC, max_self] at h
    exact (hB.symm ▸ h).false
  · have hsbtw : Sbtw ℝ B C A := ⟨hw, hBC.symm, hAC.symm⟩
    have h := hsbtw.dist_lt_max_dist O
    rw [hB, hA, max_self] at h
    exact (hC.symm ▸ h).false
  · have hsbtw : Sbtw ℝ C A B := ⟨hw, hAC, hAB⟩
    have h := hsbtw.dist_lt_max_dist O
    rw [hC, hB, max_self] at h
    exact (hA.symm ▸ h).false

/-- If three points on a circle (centered at O) have the same color c,
    and these points form a valid 2-simplex, then O has color c.
    Proof: The three points are noncollinear (on a circle), so they form a simplex.
    Their circumcenter is O (center of the circle). By the problem hypothesis,
    the circumcenter has the same color as the vertices. -/
lemma circumcenter_color_of_three_same_color_on_sphere
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (_hr : 0 < r)
    (A B C : EuclideanSpace ℝ (Fin 2))
    (hA : dist A O = r) (hB : dist B O = r) (hC : dist C O = r)
    (hAB : A ≠ B) (hBC : B ≠ C) (hAC : A ≠ C)
    (c : Bool) (hcA : color A = c) (hcB : color B = c) (hcC : color C = c) :
    color O = c := by
  have hCosph : Cospherical ({A, B, C} : Set (EuclideanSpace ℝ (Fin 2))) := by
    rw [cospherical_def]
    exact ⟨O, r, fun p hp => by
      simp only [Set.mem_insert_iff, Set.mem_singleton_iff] at hp
      rcases hp with rfl | rfl | rfl
      · exact hA
      · exact hB
      · exact hC⟩
  have hAffInd : AffineIndependent ℝ ![A, B, C] :=
    hCosph.affineIndependent_of_ne hAB hAC hBC
  let s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2 := ⟨![A, B, C], hAffInd⟩
  have hSpanTop : affineSpan ℝ (Set.range s.points) = ⊤ := by
    have hCard : Fintype.card (Fin 3) = Module.finrank ℝ (EuclideanSpace ℝ (Fin 2)) + 1 := by
      simp only [Fintype.card_fin, finrank_euclideanSpace]
    exact hAffInd.affineSpan_eq_top_iff_card_eq_finrank_add_one.mpr hCard
  have hO_mem : O ∈ affineSpan ℝ (Set.range s.points) := by rw [hSpanTop]; trivial
  have hDist : ∀ i : Fin 3, dist (s.points i) O = r := by
    intro i
    fin_cases i <;> simp [s, Matrix.cons_val_zero, Matrix.cons_val_one, hA, hB, hC]
  have hO_circum : O = s.circumcenter := s.eq_circumcenter_of_dist_eq hO_mem hDist
  have hpts0 : s.points 0 = A := by simp [s, Matrix.cons_val_zero]
  have hpts1 : s.points 1 = B := by simp [s, Matrix.cons_val_one, Matrix.head_cons]
  have hpts2 : s.points 2 = C := by
    show (![C]) 0 = C
    simp only [Matrix.cons_val_fin_one]
  have hSameColor : ∀ i j : Fin 3, color (s.points i) = color (s.points j) := by
    intro i j
    fin_cases i <;> fin_cases j <;> simp [hpts0, hpts1, hpts2, hcA, hcB, hcC]
  have hCircumColor := h s hSameColor
  rw [← hO_circum, hpts0] at hCircumColor
  rw [hCircumColor, hcA]

/-- Helper: convert a pair to EuclideanSpace -/
noncomputable def myToEuclidean (x y : ℝ) : EuclideanSpace ℝ (Fin 2) :=
  ![x, y]

/-- The parameterization function for sphere_infinite proofs -/
noncomputable def sphereParam (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (θ : ℝ) : EuclideanSpace ℝ (Fin 2) :=
  O + r • myToEuclidean (Real.cos θ) (Real.sin θ)

/-- Helper lemma: the unit vector has norm 1 -/
lemma norm_myToEuclidean_cos_sin (θ : ℝ) : ‖myToEuclidean (Real.cos θ) (Real.sin θ)‖ = 1 := by
  unfold myToEuclidean
  simp only [EuclideanSpace.norm_eq]
  conv_lhs =>
    arg 1
    arg 2
    ext i
    rw [show (![Real.cos θ, Real.sin θ] : EuclideanSpace ℝ (Fin 2)) i = ![Real.cos θ, Real.sin θ] i from rfl]
  simp only [Fin.sum_univ_two]
  simp only [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]
  rw [Real.norm_eq_abs, Real.norm_eq_abs, sq_abs, sq_abs, Real.cos_sq_add_sin_sq, Real.sqrt_one]

/-- Check that points are on the sphere -/
lemma sphereParam_on_sphere (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r) (θ : ℝ) :
    dist (sphereParam O r θ) O = r := by
  unfold sphereParam
  rw [dist_eq_norm]
  simp only [add_sub_cancel_left]
  rw [norm_smul, Real.norm_eq_abs, abs_of_pos hr, norm_myToEuclidean_cos_sin, mul_one]

/-- Helper for angle uniqueness -/
lemma Real.sin_int_mul_two_pi' (n : ℤ) : Real.sin (n * (2 * Real.pi)) = 0 := by
  have h : (n : ℝ) * (2 * Real.pi) = (2 * n : ℤ) * Real.pi := by push_cast; ring
  rw [h, Real.sin_int_mul_pi]

/-- If cos and sin agree on (0, 2π), the angles are equal -/
lemma cos_sin_eq_of_Ioo {θ₁ θ₂ : ℝ} (h1 : θ₁ ∈ Set.Ioo 0 (2 * Real.pi)) (h2 : θ₂ ∈ Set.Ioo 0 (2 * Real.pi))
    (hcos : Real.cos θ₁ = Real.cos θ₂) (hsin : Real.sin θ₁ = Real.sin θ₂) : θ₁ = θ₂ := by
  have hcos_c : Complex.cos θ₁ = Complex.cos θ₂ := by
    rw [← Complex.ofReal_cos, ← Complex.ofReal_cos, hcos]
  rw [Complex.cos_eq_cos_iff] at hcos_c
  obtain ⟨k, hk | hk⟩ := hcos_c
  · have hk_real : (θ₂ : ℝ) = 2 * k * Real.pi + θ₁ := by
      have := congrArg Complex.re hk
      simp only [Complex.add_re, Complex.mul_re, Complex.ofReal_re, Complex.ofReal_im,
        mul_zero, sub_zero] at this
      convert this using 1
      simp
    rw [Set.mem_Ioo] at h1 h2
    have hpi := Real.pi_pos
    have hbound : -2 * Real.pi < 2 * k * Real.pi ∧ 2 * k * Real.pi < 2 * Real.pi := by
      constructor <;> linarith
    have hk_zero : k = 0 := by
      rcases Int.lt_trichotomy k 0 with hk_neg | hk_zero | hk_pos
      · have hk_le : (k : ℝ) ≤ -1 := by
          have := Int.le_sub_one_of_lt hk_neg
          simp only [sub_self] at this
          exact_mod_cast this
        have : 2 * (k : ℝ) * Real.pi ≤ -2 * Real.pi := by nlinarith
        linarith [hbound.1]
      · exact hk_zero
      · have hk_ge : (k : ℝ) ≥ 1 := by exact_mod_cast hk_pos
        have : 2 * (k : ℝ) * Real.pi ≥ 2 * Real.pi := by nlinarith
        linarith [hbound.2]
    simp [hk_zero] at hk_real
    linarith
  · have hk_real : (θ₂ : ℝ) = 2 * k * Real.pi - θ₁ := by
      have := congrArg Complex.re hk
      simp only [Complex.sub_re, Complex.mul_re, Complex.ofReal_re, Complex.ofReal_im,
        mul_zero, sub_zero] at this
      convert this using 1
      simp
    rw [Set.mem_Ioo] at h1 h2
    have hpi := Real.pi_pos
    have hsin_eq : Real.sin (2 * k * Real.pi - θ₁) = Real.sin θ₁ := by
      rw [← hk_real, hsin]
    have h2kpi : 2 * (k : ℝ) * Real.pi = (k : ℤ) * (2 * Real.pi) := by ring
    rw [Real.sin_sub, h2kpi, Real.sin_int_mul_two_pi', Real.cos_int_mul_two_pi] at hsin_eq
    simp at hsin_eq
    have hsin_zero : Real.sin θ₁ = 0 := by linarith
    have hθ₁_pi : θ₁ = Real.pi := by
      have := Real.sin_eq_zero_iff.mp hsin_zero
      obtain ⟨n, hn⟩ := this
      have hbound' : 0 < (n : ℝ) * Real.pi ∧ (n : ℝ) * Real.pi < 2 * Real.pi := by
        rw [hn]; exact ⟨h1.1, h1.2⟩
      have hn_pos : (n : ℝ) > 0 := by nlinarith
      have hn_lt_2 : (n : ℝ) < 2 := by nlinarith
      have hn_one : n = 1 := by
        have hn_ge_1 : n ≥ 1 := by
          by_contra h; push_neg at h
          have h' : n ≤ 0 := by omega
          have : (n : ℝ) ≤ 0 := by exact_mod_cast h'
          linarith
        have hn_le_1 : n ≤ 1 := by
          by_contra h; push_neg at h
          have : (n : ℝ) ≥ 2 := by exact_mod_cast h
          linarith
        omega
      rw [hn_one] at hn; simp at hn; exact hn.symm
    have hsin_zero_2 : Real.sin θ₂ = 0 := hsin ▸ hsin_zero
    have hθ₂_pi : θ₂ = Real.pi := by
      have := Real.sin_eq_zero_iff.mp hsin_zero_2
      obtain ⟨n, hn⟩ := this
      have hbound' : 0 < (n : ℝ) * Real.pi ∧ (n : ℝ) * Real.pi < 2 * Real.pi := by
        rw [hn]; exact ⟨h2.1, h2.2⟩
      have hn_pos : (n : ℝ) > 0 := by nlinarith
      have hn_lt_2 : (n : ℝ) < 2 := by nlinarith
      have hn_one : n = 1 := by
        have hn_ge_1 : n ≥ 1 := by
          by_contra h; push_neg at h
          have h' : n ≤ 0 := by omega
          have : (n : ℝ) ≤ 0 := by exact_mod_cast h'
          linarith
        have hn_le_1 : n ≤ 1 := by
          by_contra h; push_neg at h
          have : (n : ℝ) ≥ 2 := by exact_mod_cast h
          linarith
        omega
      rw [hn_one] at hn; simp at hn; exact hn.symm
    rw [hθ₁_pi, hθ₂_pi]

/-- Injectivity of the parameterization on (0, 2π) -/
lemma sphereParam_injective_on_Ioo (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r) :
    Set.InjOn (sphereParam O r) (Set.Ioo 0 (2 * Real.pi)) := by
  intro θ₁ hθ₁ θ₂ hθ₂ h
  unfold sphereParam at h
  have h' : r • myToEuclidean (Real.cos θ₁) (Real.sin θ₁) = r • myToEuclidean (Real.cos θ₂) (Real.sin θ₂) := by
    have := congrArg (· - O) h
    simp only [add_sub_cancel_left] at this
    exact this
  have hr_ne : r ≠ 0 := ne_of_gt hr
  have h'' := smul_right_injective (EuclideanSpace ℝ (Fin 2)) hr_ne h'
  unfold myToEuclidean at h''
  have hcos : Real.cos θ₁ = Real.cos θ₂ := by
    have := congrFun h'' 0
    simp only [Matrix.cons_val_zero] at this
    exact this
  have hsin : Real.sin θ₁ = Real.sin θ₂ := by
    have := congrFun h'' 1
    simp only [Matrix.cons_val_one, Matrix.head_cons] at this
    exact this
  exact cos_sin_eq_of_Ioo hθ₁ hθ₂ hcos hsin

/-- The antipodal point of G on circle_R is at distance r from R -/
lemma antipodal_on_circle (R G : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (_hr : 0 < r) (hRG : dist R G = r) :
    dist ((2 : ℝ) • R - G) R = r := by
  rw [dist_eq_norm]
  have h : (2 : ℝ) • R - G - R = R - G := by
    simp only [two_smul, sub_sub]
    abel
  rw [h]
  rw [norm_sub_rev, ← dist_eq_norm, dist_comm]
  exact hRG

/-- The antipodal point of G on circle_R is at distance 2r from G -/
lemma antipodal_far_from_G (R G : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (_hr : 0 < r) (hRG : dist R G = r) :
    dist ((2 : ℝ) • R - G) G = 2 * r := by
  rw [dist_eq_norm]
  have h : (2 : ℝ) • R - G - G = (2 : ℝ) • (R - G) := by
    simp only [smul_sub, two_smul]
    abel
  rw [h]
  rw [norm_smul, Real.norm_eq_abs, abs_of_pos (by norm_num : (0:ℝ) < 2)]
  rw [← dist_eq_norm]
  rw [hRG]

/-- An open set in ℝ containing a point in [0, 2π) has infinite intersection with (0, 2π) -/
lemma open_set_intersect_Ioo_infinite
    (U : Set ℝ) (hU : IsOpen U) (θ₀ : ℝ) (hθ₀ : θ₀ ∈ U) (hθ₀_range : θ₀ ∈ Set.Ico 0 (2 * Real.pi)) :
    Set.Infinite (U ∩ Set.Ioo 0 (2 * Real.pi)) := by
  obtain ⟨ε, hε_pos, hε_ball⟩ := Metric.isOpen_iff.mp hU θ₀ hθ₀
  have h_ball_eq : Metric.ball θ₀ ε = Set.Ioo (θ₀ - ε) (θ₀ + ε) := Real.ball_eq_Ioo θ₀ ε
  rw [h_ball_eq] at hε_ball
  rw [Set.mem_Ico] at hθ₀_range
  by_cases hθ₀_zero : θ₀ = 0
  · have hpi := Real.pi_pos
    set δ := min ε (2 * Real.pi) with hδ_def
    have hδ_pos : 0 < δ := lt_min hε_pos (by linarith)
    have h_subset : Set.Ioo 0 δ ⊆ U ∩ Set.Ioo 0 (2 * Real.pi) := by
      intro x hx
      rw [Set.mem_Ioo] at hx
      refine ⟨?_, ?_, ?_⟩
      · apply hε_ball
        rw [Set.mem_Ioo, hθ₀_zero]
        simp only [sub_zero, zero_add]
        constructor
        · linarith [hx.1]
        · have hx_lt : x < δ := hx.2
          have hδ_le : δ ≤ ε := min_le_left ε (2 * Real.pi)
          linarith
      · exact hx.1
      · have hx_lt : x < δ := hx.2
        have hδ_le : δ ≤ 2 * Real.pi := min_le_right ε (2 * Real.pi)
        linarith
    have h_inf : Set.Infinite (Set.Ioo 0 δ) := Set.Ioo_infinite hδ_pos
    exact h_inf.mono h_subset
  · have hθ₀_pos : θ₀ > 0 := lt_of_le_of_ne hθ₀_range.1 (Ne.symm hθ₀_zero)
    have hpi := Real.pi_pos
    set a := max 0 (θ₀ - ε) with ha_def
    set b := min (θ₀ + ε) (2 * Real.pi) with hb_def
    have ha_lt_θ₀ : a < θ₀ := by
      rw [ha_def]
      apply max_lt hθ₀_pos
      linarith
    have hθ₀_lt_b : θ₀ < b := by
      rw [hb_def]
      simp only [lt_min_iff, lt_add_iff_pos_right]
      constructor
      · exact hε_pos
      · exact hθ₀_range.2
    have ha_lt_b : a < b := lt_trans ha_lt_θ₀ hθ₀_lt_b
    have h_subset : Set.Ioo a b ⊆ U ∩ Set.Ioo 0 (2 * Real.pi) := by
      intro x hx
      rw [Set.mem_Ioo] at hx
      refine ⟨?_, ?_, ?_⟩
      · apply hε_ball
        rw [Set.mem_Ioo]
        constructor
        · have ha_ge : a ≥ θ₀ - ε := le_max_right 0 (θ₀ - ε)
          linarith [hx.1]
        · have hb_le : b ≤ θ₀ + ε := min_le_left (θ₀ + ε) (2 * Real.pi)
          linarith [hx.2]
      · have ha_ge : a ≥ 0 := le_max_left 0 (θ₀ - ε)
        linarith [hx.1]
      · have hb_le : b ≤ 2 * Real.pi := min_le_right (θ₀ + ε) (2 * Real.pi)
        linarith [hx.2]
    have h_inf : Set.Infinite (Set.Ioo a b) := Set.Ioo_infinite ha_lt_b
    exact h_inf.mono h_subset

/-- There exists some θ in [0, 2π) such that sphereParam R r θ equals the antipodal point -/
lemma exists_antipodal_angle (R G : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r) (hRG : dist R G = r) :
    ∃ θ ∈ Set.Ico (0 : ℝ) (2 * Real.pi), sphereParam R r θ = (2 : ℝ) • R - G := by
  have hRG_ne : R ≠ G := by
    intro h
    rw [h, dist_self] at hRG
    linarith

  set z : ℂ := ⟨(R - G) 0, (R - G) 1⟩

  have hz_ne : z ≠ 0 := by
    intro h
    simp only [Complex.ext_iff] at h
    apply hRG_ne
    ext i
    fin_cases i
    · exact sub_eq_zero.mp h.1
    · exact sub_eq_zero.mp h.2

  have hz_norm : ‖z‖ = r := by
    have h := dist_eq_norm R G
    rw [EuclideanSpace.norm_eq] at h
    simp only [Fin.sum_univ_two, Real.norm_eq_abs, sq_abs] at h
    rw [hRG] at h
    rw [Complex.norm_eq_sqrt_sq_add_sq]
    exact h.symm

  set α := Complex.arg z with hα_def

  have hα_range : α ∈ Set.Ioc (-Real.pi) Real.pi := Complex.arg_mem_Ioc z

  have hz_re : (R - G) 0 = r * Real.cos α := by
    have h := Complex.norm_mul_cos_arg z
    rw [hz_norm] at h
    exact h.symm

  have hz_im : (R - G) 1 = r * Real.sin α := by
    have h := Complex.norm_mul_sin_arg z
    rw [hz_norm] at h
    exact h.symm

  set θ := if α < 0 then α + 2 * Real.pi else α with hθ_def

  have hθ_range : θ ∈ Set.Ico 0 (2 * Real.pi) := by
    rw [Set.mem_Ico, hθ_def]
    split_ifs with h
    · constructor
      · have := hα_range.1; linarith
      · have := hα_range.2; linarith
    · push_neg at h
      constructor
      · linarith [hα_range.1]
      · have := hα_range.2; linarith [Real.pi_pos]

  have hcos_eq : Real.cos θ = Real.cos α := by
    rw [hθ_def]
    split_ifs with h
    · rw [Real.cos_add_two_pi]
    · rfl

  have hsin_eq : Real.sin θ = Real.sin α := by
    rw [hθ_def]
    split_ifs with h
    · rw [Real.sin_add_two_pi]
    · rfl

  use θ
  refine ⟨hθ_range, ?_⟩

  have hcos' : r * Real.cos θ = (R - G) 0 := by
    rw [hcos_eq]
    exact hz_re.symm
  have hsin' : r * Real.sin θ = (R - G) 1 := by
    rw [hsin_eq]
    exact hz_im.symm

  unfold sphereParam myToEuclidean
  ext i
  fin_cases i
  ·
    show R 0 + r * Real.cos θ = 2 * R 0 - G 0
    calc R 0 + r * Real.cos θ = R 0 + (R - G) 0 := by rw [hcos']
      _ = R 0 + (R 0 - G 0) := by rfl
      _ = 2 * R 0 - G 0 := by ring
  ·
    show R 1 + r * Real.sin θ = 2 * R 1 - G 1
    calc R 1 + r * Real.sin θ = R 1 + (R - G) 1 := by rw [hsin']
      _ = R 1 + (R 1 - G 1) := by rfl
      _ = 2 * R 1 - G 1 := by ring

/-- For two points R, G with dist R G = r, the set of points A on the circle
    centered at R with radius r such that dist A G > r/2 is infinite.
    Geometrically: the circle centered at R passes through G (since dist R G = r).
    The set where dist A G ≤ r/2 is a small arc near G, leaving the rest infinite. -/
lemma arc_away_from_point_infinite
    (R G : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r) (hRG : dist R G = r) :
    Set.Infinite {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G > r / 2} := by
  set A₀ := (2 : ℝ) • R - G with hA₀_def

  have hA₀_on_circle : dist A₀ R = r := antipodal_on_circle R G r hr hRG
  have hA₀_far : dist A₀ G = 2 * r := antipodal_far_from_G R G r hr hRG
  have hA₀_good : dist A₀ G > r / 2 := by linarith

  obtain ⟨θ₀, hθ₀_range, hθ₀_eq⟩ := exists_antipodal_angle R G r hr hRG

  have h_f_cont : Continuous (fun θ => dist (sphereParam R r θ) G) := by
    apply Continuous.dist
    · unfold sphereParam myToEuclidean
      apply Continuous.add continuous_const
      apply Continuous.smul continuous_const
      apply continuous_pi
      intro i
      fin_cases i <;> continuity
    · exact continuous_const

  have h_preimage_open : IsOpen {θ | dist (sphereParam R r θ) G > r / 2} :=
    isOpen_lt continuous_const h_f_cont

  have h_θ₀_in_preimage : θ₀ ∈ {θ | dist (sphereParam R r θ) G > r / 2} := by
    simp only [Set.mem_setOf_eq]
    rw [hθ₀_eq]
    exact hA₀_good

  have h_angles_inf : Set.Infinite ({θ | dist (sphereParam R r θ) G > r / 2} ∩ Set.Ioo 0 (2 * Real.pi)) :=
    open_set_intersect_Ioo_infinite _ h_preimage_open θ₀ h_θ₀_in_preimage hθ₀_range

  have h_image_subset : sphereParam R r '' ({θ | dist (sphereParam R r θ) G > r / 2} ∩ Set.Ioo 0 (2 * Real.pi)) ⊆
                        {A | dist A R = r ∧ dist A G > r / 2} := by
    intro A hA
    simp only [Set.mem_image, Set.mem_inter_iff, Set.mem_setOf_eq, Set.mem_Ioo] at hA
    obtain ⟨θ, ⟨hθ_good, ⟨hθ_pos, hθ_lt⟩⟩, hθ_eq⟩ := hA
    simp only [Set.mem_setOf_eq]
    constructor
    · rw [← hθ_eq]
      exact sphereParam_on_sphere R r hr θ
    · rw [← hθ_eq]
      exact hθ_good

  have h_inj : Set.InjOn (sphereParam R r) (Set.Ioo 0 (2 * Real.pi)) :=
    sphereParam_injective_on_Ioo R r hr

  have h_image_inf : Set.Infinite (sphereParam R r '' ({θ | dist (sphereParam R r θ) G > r / 2} ∩ Set.Ioo 0 (2 * Real.pi))) := by
    apply Set.Infinite.image
    · intro θ₁ hθ₁ θ₂ hθ₂ h
      apply h_inj
      · exact (Set.mem_inter_iff _ _ _ |>.mp hθ₁).2
      · exact (Set.mem_inter_iff _ _ _ |>.mp hθ₂).2
      · exact h
    · exact h_angles_inf

  exact Set.Infinite.mono h_image_subset h_image_inf

/-- Helper: The set of opposite-colored points on the sphere is finite.
    Proof: If there were 3 or more points, they would be noncollinear and form a simplex
    whose circumcenter is O. By the coloring hypothesis, O would have the opposite color,
    contradiction. So there are at most 2 points, hence the set is finite. -/
lemma opposite_color_on_sphere_finite
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (O : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r) (c : Bool) (hO : color O = c) :
    {P : EuclideanSpace ℝ (Fin 2) | dist P O = r ∧ color P = !c}.Finite := by
  set S := {P : EuclideanSpace ℝ (Fin 2) | dist P O = r ∧ color P = !c}
  by_contra h_inf
  have h3 : ∃ A B C : EuclideanSpace ℝ (Fin 2),
      A ∈ S ∧ B ∈ S ∧ C ∈ S ∧ A ≠ B ∧ B ≠ C ∧ A ≠ C := by
    obtain ⟨T, hT_sub, _, hT_card⟩ := Set.Infinite.exists_subset_ncard_eq h_inf 3
    rw [Set.ncard_eq_three] at hT_card
    obtain ⟨A, B, C, hAB, hAC, hBC, hT_eq⟩ := hT_card
    refine ⟨A, B, C, ?_, ?_, ?_, hAB, hBC, hAC⟩
    all_goals {
      apply hT_sub
      rw [hT_eq]
      simp
    }
  obtain ⟨A, B, C, hAS, hBS, hCS, hAB, hBC, hAC⟩ := h3
  simp only [Set.mem_setOf_eq] at hAS hBS hCS
  obtain ⟨hA_dist, hA_color⟩ := hAS
  obtain ⟨hB_dist, hB_color⟩ := hBS
  obtain ⟨hC_dist, hC_color⟩ := hCS
  have hO_notc : color O = !c :=
    circumcenter_color_of_three_same_color_on_sphere color h O r hr A B C hA_dist hB_dist hC_dist hAB hBC hAC (!c) hA_color hB_color hC_color
  rw [hO] at hO_notc
  cases c <;> simp at hO_notc

/-- Rotate a vector by 90 degrees in the plane (counterclockwise).
    If v = (a, b), then perpVector v = (-b, a). -/
noncomputable def perpVector (v : EuclideanSpace ℝ (Fin 2)) : EuclideanSpace ℝ (Fin 2) :=
  ![-(v 1), v 0]

/-- The perpendicular rotation preserves the norm. -/
lemma norm_perpVector (v : EuclideanSpace ℝ (Fin 2)) : ‖perpVector v‖ = ‖v‖ := by
  rw [EuclideanSpace.norm_eq, EuclideanSpace.norm_eq]
  congr 1
  simp only [perpVector]
  simp only [Fin.sum_univ_two]
  simp only [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]
  simp only [Real.norm_eq_abs, abs_neg]
  ring

/-- The perpendicular vector is orthogonal to the original. -/
lemma inner_perpVector (v : EuclideanSpace ℝ (Fin 2)) :
    @inner ℝ (EuclideanSpace ℝ (Fin 2)) _ v (perpVector v) = 0 := by
  simp only [EuclideanSpace.inner_eq_star_dotProduct, star_trivial, perpVector]
  simp only [dotProduct, Fin.sum_univ_two]
  simp only [WithLp.ofLp, id_eq]
  simp only [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]
  ring

/-- perpVector is nonzero iff v is nonzero -/
lemma perpVector_eq_zero_iff (v : EuclideanSpace ℝ (Fin 2)) : perpVector v = 0 ↔ v = 0 := by
  constructor
  · intro h
    ext i
    fin_cases i
    ·
      have h1 : perpVector v 1 = 0 := by rw [h]; simp
      simp only [perpVector, Matrix.cons_val_one, Matrix.head_cons] at h1
      exact h1
    ·
      have h0 : perpVector v 0 = 0 := by rw [h]; simp
      simp only [perpVector, Matrix.cons_val_zero, neg_eq_zero] at h0
      exact h0
  · intro h
    simp only [perpVector, h, Pi.zero_apply, neg_zero]
    ext i
    fin_cases i <;> simp [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]

/-- Helper: for orthogonal vectors u, w with same norm r, (a)u + (b)w has norm sqrt(a² + b²) * r.
    Specifically, (1/2)u + (√3/2)w has norm r since (1/2)² + (√3/2)² = 1. -/
lemma norm_half_plus_sqrt3_half_eq {u w : EuclideanSpace ℝ (Fin 2)} {r : ℝ}
    (hu : ‖u‖ = r) (hw : ‖w‖ = r) (hr : 0 < r)
    (horth : @inner ℝ _ _ u w = 0) :
    ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖ = r := by
  have hinner : @inner ℝ _ _ ((1/2 : ℝ) • u) ((Real.sqrt 3 / 2) • w) = 0 := by
    rw [inner_smul_left, inner_smul_right, horth, mul_zero, mul_zero]
  have h := @norm_add_sq_eq_norm_sq_add_norm_sq_of_inner_eq_zero ℝ _ _ _ _
    ((1/2 : ℝ) • u) ((Real.sqrt 3 / 2) • w) hinner
  simp only [norm_smul, Real.norm_eq_abs] at h
  have hsqrt3_pos : 0 < Real.sqrt 3 := Real.sqrt_pos.mpr (by norm_num : (3:ℝ) > 0)
  have h12_pos : (0:ℝ) < 1/2 := by norm_num
  have hsq : Real.sqrt 3 ^ 2 = 3 := Real.sq_sqrt (by norm_num : (3:ℝ) ≥ 0)
  have key : ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖^2 = r^2 := by
    calc ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖^2
        = ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖ * ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖ := sq _
      _ = |1/2| * ‖u‖ * (|1/2| * ‖u‖) + |Real.sqrt 3 / 2| * ‖w‖ * (|Real.sqrt 3 / 2| * ‖w‖) := h
      _ = (1/2) * r * ((1/2) * r) + (Real.sqrt 3 / 2) * r * ((Real.sqrt 3 / 2) * r) := by
          rw [hu, hw, abs_of_pos h12_pos, abs_of_pos (div_pos hsqrt3_pos (by norm_num))]
      _ = (1/4) * r^2 + (Real.sqrt 3 ^ 2 / 4) * r^2 := by ring
      _ = (1/4) * r^2 + (3 / 4) * r^2 := by rw [hsq]
      _ = r^2 := by ring
  have hr2 : 0 ≤ r := le_of_lt hr
  have hnorm_nonneg : 0 ≤ ‖(1/2 : ℝ) • u + (Real.sqrt 3 / 2) • w‖ := norm_nonneg _
  exact sq_eq_sq₀ hnorm_nonneg hr2 |>.mp key

/-- Helper: for orthogonal vectors u, w with same norm r, (1/2)u - (√3/2)w has norm r. -/
lemma norm_half_minus_sqrt3_half_eq {u w : EuclideanSpace ℝ (Fin 2)} {r : ℝ}
    (hu : ‖u‖ = r) (hw : ‖w‖ = r) (hr : 0 < r)
    (horth : @inner ℝ _ _ u w = 0) :
    ‖(1/2 : ℝ) • u - (Real.sqrt 3 / 2) • w‖ = r := by
  have hinner : @inner ℝ _ _ ((1/2 : ℝ) • u) ((-(Real.sqrt 3 / 2)) • w) = 0 := by
    rw [inner_smul_left, inner_smul_right, horth, mul_zero, mul_zero]
  have hrw : (1/2 : ℝ) • u - (Real.sqrt 3 / 2) • w = (1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w := by
    rw [neg_smul, sub_eq_add_neg]
  rw [hrw]
  have h := @norm_add_sq_eq_norm_sq_add_norm_sq_of_inner_eq_zero ℝ _ _ _ _
    ((1/2 : ℝ) • u) ((-(Real.sqrt 3 / 2)) • w) hinner
  simp only [norm_smul, Real.norm_eq_abs, norm_neg, abs_neg] at h
  have hsqrt3_pos : 0 < Real.sqrt 3 := Real.sqrt_pos.mpr (by norm_num : (3:ℝ) > 0)
  have h12_pos : (0:ℝ) < 1/2 := by norm_num
  have hsq : Real.sqrt 3 ^ 2 = 3 := Real.sq_sqrt (by norm_num : (3:ℝ) ≥ 0)
  have key : ‖(1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖^2 = r^2 := by
    calc ‖(1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖^2
        = ‖(1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ * ‖(1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ := sq _
      _ = |1/2| * ‖u‖ * (|1/2| * ‖u‖) + |Real.sqrt 3 / 2| * ‖w‖ * (|Real.sqrt 3 / 2| * ‖w‖) := h
      _ = (1/2) * r * ((1/2) * r) + (Real.sqrt 3 / 2) * r * ((Real.sqrt 3 / 2) * r) := by
          rw [hu, hw, abs_of_pos h12_pos, abs_of_pos (div_pos hsqrt3_pos (by norm_num))]
      _ = (1/4) * r^2 + (Real.sqrt 3 ^ 2 / 4) * r^2 := by ring
      _ = (1/4) * r^2 + (3 / 4) * r^2 := by rw [hsq]
      _ = r^2 := by ring
  have hr2 : 0 ≤ r := le_of_lt hr
  have hnorm_nonneg : 0 ≤ ‖(1/2 : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ := norm_nonneg _
  exact sq_eq_sq₀ hnorm_nonneg hr2 |>.mp key

/-- Helper: for orthogonal vectors u, w with same norm r, (-1/2)u + (√3/2)w has norm r. -/
lemma norm_neg_half_plus_sqrt3_half_eq {u w : EuclideanSpace ℝ (Fin 2)} {r : ℝ}
    (hu : ‖u‖ = r) (hw : ‖w‖ = r) (hr : 0 < r)
    (horth : @inner ℝ _ _ u w = 0) :
    ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖ = r := by
  have hinner : @inner ℝ _ _ ((-(1/2) : ℝ) • u) ((Real.sqrt 3 / 2) • w) = 0 := by
    rw [inner_smul_left, inner_smul_right, horth, mul_zero, mul_zero]
  have h := @norm_add_sq_eq_norm_sq_add_norm_sq_of_inner_eq_zero ℝ _ _ _ _
    ((-(1/2) : ℝ) • u) ((Real.sqrt 3 / 2) • w) hinner
  simp only [norm_smul, Real.norm_eq_abs, abs_neg] at h
  have hsqrt3_pos : 0 < Real.sqrt 3 := Real.sqrt_pos.mpr (by norm_num : (3:ℝ) > 0)
  have h12_pos : (0:ℝ) < 1/2 := by norm_num
  have hsq : Real.sqrt 3 ^ 2 = 3 := Real.sq_sqrt (by norm_num : (3:ℝ) ≥ 0)
  have key : ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖^2 = r^2 := by
    calc ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖^2
        = ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖ * ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖ := sq _
      _ = |1/2| * ‖u‖ * (|1/2| * ‖u‖) + |Real.sqrt 3 / 2| * ‖w‖ * (|Real.sqrt 3 / 2| * ‖w‖) := h
      _ = (1/2) * r * ((1/2) * r) + (Real.sqrt 3 / 2) * r * ((Real.sqrt 3 / 2) * r) := by
          rw [hu, hw, abs_of_pos h12_pos, abs_of_pos (div_pos hsqrt3_pos (by norm_num))]
      _ = (1/4) * r^2 + (Real.sqrt 3 ^ 2 / 4) * r^2 := by ring
      _ = (1/4) * r^2 + (3 / 4) * r^2 := by rw [hsq]
      _ = r^2 := by ring
  have hr2 : 0 ≤ r := le_of_lt hr
  have hnorm_nonneg : 0 ≤ ‖(-(1/2) : ℝ) • u + (Real.sqrt 3 / 2) • w‖ := norm_nonneg _
  exact sq_eq_sq₀ hnorm_nonneg hr2 |>.mp key

/-- Helper: for orthogonal vectors u, w with same norm r, (-1/2)u - (√3/2)w has norm r. -/
lemma norm_neg_half_minus_sqrt3_half_eq {u w : EuclideanSpace ℝ (Fin 2)} {r : ℝ}
    (hu : ‖u‖ = r) (hw : ‖w‖ = r) (hr : 0 < r)
    (horth : @inner ℝ _ _ u w = 0) :
    ‖(-(1/2) : ℝ) • u - (Real.sqrt 3 / 2) • w‖ = r := by
  have hrw : (-(1/2) : ℝ) • u - (Real.sqrt 3 / 2) • w = (-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w := by
    simp only [neg_smul, sub_eq_add_neg]
  rw [hrw]
  have hinner : @inner ℝ _ _ ((-(1/2) : ℝ) • u) ((-(Real.sqrt 3 / 2)) • w) = 0 := by
    rw [inner_smul_left, inner_smul_right, horth, mul_zero, mul_zero]
  have h := @norm_add_sq_eq_norm_sq_add_norm_sq_of_inner_eq_zero ℝ _ _ _ _
    ((-(1/2) : ℝ) • u) ((-(Real.sqrt 3 / 2)) • w) hinner
  simp only [norm_smul, Real.norm_eq_abs, abs_neg] at h
  have hsqrt3_pos : 0 < Real.sqrt 3 := Real.sqrt_pos.mpr (by norm_num : (3:ℝ) > 0)
  have h12_pos : (0:ℝ) < 1/2 := by norm_num
  have hsq : Real.sqrt 3 ^ 2 = 3 := Real.sq_sqrt (by norm_num : (3:ℝ) ≥ 0)
  have key : ‖(-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖^2 = r^2 := by
    calc ‖(-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖^2
        = ‖(-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ * ‖(-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ := sq _
      _ = |1/2| * ‖u‖ * (|1/2| * ‖u‖) + |Real.sqrt 3 / 2| * ‖w‖ * (|Real.sqrt 3 / 2| * ‖w‖) := h
      _ = (1/2) * r * ((1/2) * r) + (Real.sqrt 3 / 2) * r * ((Real.sqrt 3 / 2) * r) := by
          rw [hu, hw, abs_of_pos h12_pos, abs_of_pos (div_pos hsqrt3_pos (by norm_num))]
      _ = (1/4) * r^2 + (Real.sqrt 3 ^ 2 / 4) * r^2 := by ring
      _ = (1/4) * r^2 + (3 / 4) * r^2 := by rw [hsq]
      _ = r^2 := by ring
  have hr2 : 0 ≤ r := le_of_lt hr
  have hnorm_nonneg : 0 ≤ ‖(-(1/2) : ℝ) • u + (-(Real.sqrt 3 / 2)) • w‖ := norm_nonneg _
  exact sq_eq_sq₀ hnorm_nonneg hr2 |>.mp key

/-- Two circles of equal radius r, with centers R, G at distance r apart, intersect
    in exactly two points. Existence follows from standard geometry (using the
    equilateral triangle construction: the third vertices of equilateral triangles
    on segment RG give the intersection points).

    Construction:
    - Let v = G - R (so ‖v‖ = r)
    - Let Jv = perpVector v (the 90° rotation of v, also with norm r)
    - Define X = R + (1/2)v + (√3/2)Jv
    - Define Y = R + (1/2)v - (√3/2)Jv
    These form equilateral triangles with R and G. -/
theorem two_circles_equal_radius_intersect_existence
    (R G : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r)
    (hRG : dist R G = r) :
    ∃ X Y : EuclideanSpace ℝ (Fin 2),
      X ≠ Y ∧
      dist X R = r ∧ dist X G = r ∧
      dist Y R = r ∧ dist Y G = r := by
  set v := G -ᵥ R
  have hv_norm : ‖v‖ = r := by rw [dist_eq_norm_vsub'] at hRG; exact hRG
  set Jv := perpVector v
  have hJv_norm : ‖Jv‖ = r := by rw [norm_perpVector, hv_norm]
  have hJv_inner : @inner ℝ _ _ v Jv = 0 := inner_perpVector v
  set c1 : ℝ := 1 / 2
  set c2 : ℝ := Real.sqrt 3 / 2
  set dX : EuclideanSpace ℝ (Fin 2) := c1 • v + c2 • Jv
  set dY : EuclideanSpace ℝ (Fin 2) := c1 • v - c2 • Jv
  use R +ᵥ dX, R +ᵥ dY
  refine ⟨?_, ?_, ?_, ?_, ?_⟩
  · intro hXY
    have hc2_pos : c2 > 0 := div_pos (Real.sqrt_pos.mpr (by norm_num : (3 : ℝ) > 0)) (by norm_num)
    have hdiff : dX - dY = (2 : ℝ) • (c2 • Jv) := by module
    have heq : dX = dY := by
      have : (R +ᵥ dX) -ᵥ (R +ᵥ dY) = dX -ᵥ dY := vadd_vsub_vadd_cancel_left R dX dY
      simp only [hXY, vsub_self] at this
      exact eq_of_vsub_eq_zero this.symm
    have hdX_eq_dY : dX - dY = 0 := sub_eq_zero.mpr heq
    rw [hdX_eq_dY] at hdiff
    have h2c2Jv : (2 : ℝ) • (c2 • Jv) = 0 := hdiff.symm
    rw [smul_smul] at h2c2Jv
    have h2c2_ne : (2 : ℝ) * c2 ≠ 0 := mul_ne_zero (by norm_num) (ne_of_gt hc2_pos)
    rw [smul_eq_zero, or_iff_right h2c2_ne] at h2c2Jv
    rw [perpVector_eq_zero_iff] at h2c2Jv
    have : r = 0 := by rw [← hv_norm, h2c2Jv, norm_zero]
    linarith
  · rw [dist_eq_norm_vsub]
    have h1 : (R +ᵥ dX) -ᵥ R = dX := by show (R + dX) - R = dX; simp only [add_sub_cancel_left]
    rw [h1]
    exact norm_half_plus_sqrt3_half_eq hv_norm hJv_norm hr hJv_inner
  · rw [dist_eq_norm_vsub]
    have h1 : (R +ᵥ dX) -ᵥ G = dX + (R -ᵥ G) := by show (R + dX) - G = dX + (R - G); abel
    have h2 : R -ᵥ G = -(G -ᵥ R) := by show R - G = -(G - R); abel
    have h3 : G -ᵥ R = v := rfl
    rw [h1, h2, h3]
    have h4 : dX + (-v) = dX - v := by abel
    rw [h4]
    have h5 : dX - v = (c1 - 1) • v + c2 • Jv := by simp only [dX]; module
    rw [h5]
    have hc1m1 : c1 - 1 = -(1/2 : ℝ) := by norm_num
    rw [hc1m1]
    exact norm_neg_half_plus_sqrt3_half_eq hv_norm hJv_norm hr hJv_inner
  · rw [dist_eq_norm_vsub]
    have h1 : (R +ᵥ dY) -ᵥ R = dY := by show (R + dY) - R = dY; simp only [add_sub_cancel_left]
    rw [h1]
    exact norm_half_minus_sqrt3_half_eq hv_norm hJv_norm hr hJv_inner
  · rw [dist_eq_norm_vsub]
    have h1 : (R +ᵥ dY) -ᵥ G = dY + (R -ᵥ G) := by show (R + dY) - G = dY + (R - G); abel
    have h2 : R -ᵥ G = -(G -ᵥ R) := by show R - G = -(G - R); abel
    have h3 : G -ᵥ R = v := rfl
    rw [h1, h2, h3]
    have h4 : dY + (-v) = dY - v := by abel
    rw [h4]
    have h5 : dY - v = (c1 - 1) • v - c2 • Jv := by simp only [dY]; module
    rw [h5]
    have hc1m1 : c1 - 1 = -(1/2 : ℝ) := by norm_num
    rw [hc1m1]
    exact norm_neg_half_minus_sqrt3_half_eq hv_norm hJv_norm hr hJv_inner

/-- If two distinct points P1, P2 both lie on two circles with distinct centers,
    then any third point P on both circles must equal P1 or P2.
    This follows from EuclideanGeometry.eq_of_dist_eq_of_dist_eq_of_finrank_eq_two. -/
lemma two_circles_intersection_at_most_two
    (c₁ c₂ : EuclideanSpace ℝ (Fin 2)) (r₁ r₂ : ℝ)
    (hc : c₁ ≠ c₂)
    (P₁ P₂ : EuclideanSpace ℝ (Fin 2)) (hP : P₁ ≠ P₂)
    (hP₁c₁ : dist P₁ c₁ = r₁) (hP₂c₁ : dist P₂ c₁ = r₁)
    (hP₁c₂ : dist P₁ c₂ = r₂) (hP₂c₂ : dist P₂ c₂ = r₂)
    (P : EuclideanSpace ℝ (Fin 2))
    (hPc₁ : dist P c₁ = r₁) (hPc₂ : dist P c₂ = r₂) :
    P = P₁ ∨ P = P₂ := by
  apply EuclideanGeometry.eq_of_dist_eq_of_dist_eq_of_finrank_eq_two
  · exact finrank_euclideanSpace_fin
  · exact hc
  · exact hP
  · exact hP₁c₁
  · exact hP₂c₁
  · exact hPc₁
  · exact hP₁c₂
  · exact hP₂c₂
  · exact hPc₂

/-- Given two distinct colors (R with color true and G with color false),
    the intersection points X, Y of circles centered at R and G (both radius r = dist R G)
    have different colors.
    Proof: If both X, Y were green, then {G, X, Y} are 3 green points on the circle
    centered at red R. By the density lemma, R would be green, contradiction.
    Similarly if both were red, G would be red. -/
lemma intersection_points_different_colors
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (R G : EuclideanSpace ℝ (Fin 2)) (hR : color R = true) (hG : color G = false)
    (r : ℝ) (hr : 0 < r) (hRG : dist R G = r)
    (X Y : EuclideanSpace ℝ (Fin 2)) (hXY : X ≠ Y)
    (hXR : dist X R = r) (hXG : dist X G = r)
    (hYR : dist Y R = r) (hYG : dist Y G = r) :
    color X ≠ color Y := by
  intro hXY_same_color
  rcases Bool.dichotomy (color X) with hX_green | hX_red
  ·
    have hY_green : color Y = false := hXY_same_color ▸ hX_green
    have hGX : G ≠ X := fun h => by simp [h, dist_self] at hXG; linarith
    have hGY : G ≠ Y := fun h => by simp [h, dist_self] at hYG; linarith
    have hGR : dist G R = r := by rw [dist_comm]; exact hRG
    have hR_green : color R = false :=
      circumcenter_color_of_three_same_color_on_sphere color h R r hr
        G X Y hGR hXR hYR hGX hXY hGY false hG hX_green hY_green
    simp [hR] at hR_green
  ·
    have hY_red : color Y = true := hXY_same_color ▸ hX_red
    have hRX : R ≠ X := fun h => by simp [h, dist_self] at hXR; linarith
    have hRY : R ≠ Y := fun h => by simp [h, dist_self] at hYR; linarith
    have hG_red : color G = true :=
      circumcenter_color_of_three_same_color_on_sphere color h G r hr
        R X Y hRG hXG hYG hRX hXY hRY true hR hX_red hY_red
    simp [hG] at hG_red

/-- Red points on arc far from G is infinite. -/
lemma red_points_far_from_G_infinite
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (R G : EuclideanSpace ℝ (Fin 2)) (hR : color R = true)
    (r : ℝ) (hr : 0 < r) (hRG : dist R G = r) :
    Set.Infinite {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G > r / 2 ∧ color A = true} := by
  let arc := {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G > r / 2}
  have h_arc_inf : arc.Infinite := arc_away_from_point_infinite R G r hr hRG
  let green := {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ color A = false}
  have h_green_finite : green.Finite := by
    have : {P : EuclideanSpace ℝ (Fin 2) | dist P R = r ∧ color P = !true}.Finite :=
      opposite_color_on_sphere_finite color h R r hr true hR
    simp only [Bool.not_true] at this
    exact this
  let green_on_arc := green ∩ arc
  have h_goa_finite : green_on_arc.Finite := Set.Finite.inter_of_left h_green_finite arc
  have h_target_eq : {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G > r / 2 ∧ color A = true}
      = arc \ green_on_arc := by
    ext A
    simp only [Set.mem_setOf_eq, Set.mem_diff, Set.mem_inter_iff]
    constructor
    · intro ⟨hAR, hAG, hA_true⟩
      refine ⟨⟨hAR, hAG⟩, ?_⟩
      intro ⟨⟨_, hA_false⟩, _⟩
      simp [hA_true] at hA_false
    · intro ⟨⟨hAR, hAG⟩, hA_not⟩
      refine ⟨hAR, hAG, ?_⟩
      by_contra hA_not_true
      apply hA_not
      have hA_false : color A = false := by
        cases hc : color A with
        | true => exact absurd hc hA_not_true
        | false => rfl
      exact ⟨⟨hAR, hA_false⟩, ⟨hAR, hAG⟩⟩
  rw [h_target_eq]
  exact Set.Infinite.diff h_arc_inf h_goa_finite

/-- Helper: finrank of submodule is monotone with respect to ≤ -/
lemma Submodule.finrank_le_of_le' {K M : Type*} [DivisionRing K] [AddCommGroup M] [Module K M]
    [FiniteDimensional K M] {s t : Submodule K M} (hst : s ≤ t) :
    Module.finrank K s ≤ Module.finrank K t := by
  have h : Function.Injective (Submodule.inclusion hst) := Submodule.inclusion_injective hst
  exact LinearMap.finrank_le_finrank_of_injective h

/-- If finrank ≤ 1, then rank ≤ 1 (for finite-dimensional modules) -/
lemma rank_le_one_of_finrank_le_one' {K M : Type*} [DivisionRing K] [AddCommGroup M] [Module K M]
    [Module.Finite K M] (h : Module.finrank K M ≤ 1) :
    Module.rank K M ≤ 1 := by
  rw [← Module.finrank_eq_rank K M]
  exact_mod_cast h

/-- Points on the perpendicular bisector of X and G (when X ≠ G) are collinear.
    The perpendicular bisector is a line in 2D, and points on a line are collinear. -/
lemma perpBisector_subset_collinear
    (X G : EuclideanSpace ℝ (Fin 2)) (hXG : X ≠ G)
    (s : Set (EuclideanSpace ℝ (Fin 2)))
    (hs : s ⊆ {A | dist A X = dist A G}) :
    Collinear ℝ s := by
  have h_perp : s ⊆ ↑(AffineSubspace.perpBisector X G) := by
    intro A hA
    rw [SetLike.mem_coe, AffineSubspace.mem_perpBisector_iff_dist_eq]
    exact hs hA
  rw [collinear_iff_rank_le_one]
  have h_vsub : vectorSpan ℝ s ≤ (AffineSubspace.perpBisector X G).direction := by
    rw [vectorSpan_def]
    apply Submodule.span_le.mpr
    intro v hv
    obtain ⟨p, hp, q, hq, rfl⟩ := Set.mem_vsub.mp hv
    exact AffineSubspace.vsub_mem_direction (h_perp hp) (h_perp hq)
  have h_dir : (AffineSubspace.perpBisector X G).direction = (Submodule.span ℝ {G -ᵥ X})ᗮ :=
    AffineSubspace.direction_perpBisector X G
  have h_ne_zero : G -ᵥ X ≠ 0 := vsub_ne_zero.mpr hXG.symm
  have h_finrank_eq : Module.finrank ℝ (AffineSubspace.perpBisector X G).direction = 1 := by
    rw [h_dir]
    have h1 : Module.finrank ℝ ↥(Submodule.span ℝ {G -ᵥ X}) +
              Module.finrank ℝ ↥(Submodule.span ℝ {G -ᵥ X})ᗮ =
              Module.finrank ℝ (EuclideanSpace ℝ (Fin 2)) :=
      Submodule.finrank_add_finrank_orthogonal (Submodule.span ℝ {G -ᵥ X})
    have h2 : Module.finrank ℝ (EuclideanSpace ℝ (Fin 2)) = 2 := finrank_euclideanSpace_fin
    have h3 : Module.finrank ℝ ↥(Submodule.span ℝ {G -ᵥ X}) = 1 := finrank_span_singleton h_ne_zero
    omega
  have h_finrank_vsub : Module.finrank ℝ (vectorSpan ℝ s) ≤ 1 := by
    calc Module.finrank ℝ (vectorSpan ℝ s)
        ≤ Module.finrank ℝ (AffineSubspace.perpBisector X G).direction :=
          Submodule.finrank_le_of_le' h_vsub
      _ = 1 := h_finrank_eq
  exact rank_le_one_of_finrank_le_one' h_finrank_vsub

/-- Circle ∩ perpendicular bisector is finite.
    Points equidistant from X and G lie on the perpendicular bisector of XG,
    which is a line in 2D (when X ≠ G). A line intersects a circle in at most 2 points. -/
theorem circle_perp_bisector_finite
    (R X G : EuclideanSpace ℝ (Fin 2))
    (r : ℝ) (hr : 0 < r)
    (hXG : X ≠ G) :
    {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A X = dist A G}.Finite := by
  by_contra h_inf
  have hne : {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A X = dist A G}.Nonempty :=
    Set.Infinite.nonempty h_inf
  obtain ⟨P₁, hP₁⟩ := hne
  have h_inf' : ({A | dist A R = r ∧ dist A X = dist A G} \ {P₁}).Infinite :=
    Set.Infinite.diff h_inf (Set.finite_singleton P₁)
  obtain ⟨P₂, hP₂⟩ := Set.Infinite.nonempty h_inf'
  simp only [Set.mem_diff, Set.mem_setOf_eq, Set.mem_singleton_iff] at hP₂
  have h_inf'' : ({A | dist A R = r ∧ dist A X = dist A G} \ {P₁, P₂}).Infinite :=
    Set.Infinite.diff h_inf (Set.toFinite {P₁, P₂})
  obtain ⟨P₃, hP₃⟩ := Set.Infinite.nonempty h_inf''
  simp only [Set.mem_diff, Set.mem_setOf_eq, Set.mem_insert_iff, Set.mem_singleton_iff] at hP₃
  have hP₁₂ : P₁ ≠ P₂ := fun h => hP₂.2 h.symm
  have hP₁₃ : P₁ ≠ P₃ := fun h => hP₃.2 (Or.inl h.symm)
  have hP₂₃ : P₂ ≠ P₃ := fun h => hP₃.2 (Or.inr h.symm)
  have hP₁_circle : dist P₁ R = r := hP₁.1
  have hP₂_circle : dist P₂ R = r := hP₂.1.1
  have hP₃_circle : dist P₃ R = r := hP₃.1.1
  have hP₁_bisect : dist P₁ X = dist P₁ G := hP₁.2
  have hP₂_bisect : dist P₂ X = dist P₂ G := hP₂.1.2
  have hP₃_bisect : dist P₃ X = dist P₃ G := hP₃.1.2
  have h_subset : ({P₁, P₂, P₃} : Set (EuclideanSpace ℝ (Fin 2))) ⊆ {A | dist A X = dist A G} := by
    intro A hA
    simp only [Set.mem_insert_iff, Set.mem_singleton_iff, Set.mem_setOf_eq] at hA ⊢
    rcases hA with rfl | rfl | rfl <;> assumption
  have h_collinear : Collinear ℝ ({P₁, P₂, P₃} : Set (EuclideanSpace ℝ (Fin 2))) :=
    perpBisector_subset_collinear X G hXG {P₁, P₂, P₃} h_subset
  have h_not_collinear : ¬Collinear ℝ ({P₁, P₂, P₃} : Set (EuclideanSpace ℝ (Fin 2))) :=
    three_points_on_sphere_noncollinear R r hr P₁ P₂ P₃
      hP₁_circle hP₂_circle hP₃_circle hP₁₂ hP₂₃ hP₁₃
  exact h_not_collinear h_collinear

/-- Circle ∩ perpendicular bisector is finite (at most 2 points). -/
lemma equidistant_from_X_G_finite
    (R G X : EuclideanSpace ℝ (Fin 2))
    (r : ℝ) (hr : 0 < r)
    (hdist_XG : dist X G = r) :
    {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A X = dist A G}.Finite := by
  have hXG_ne : X ≠ G := by
    intro h
    rw [h, dist_self] at hdist_XG
    linarith
  exact circle_perp_bisector_finite R X G r hr hXG_ne

/-- Intersection of two circles (same radius) is finite. -/
lemma dist_eq_r_finite
    (R G : EuclideanSpace ℝ (Fin 2))
    (r : ℝ) (hr : 0 < r) (hRG : dist R G = r)
    (X Y : EuclideanSpace ℝ (Fin 2)) (hXY : X ≠ Y)
    (hXR : dist X R = r) (hXG : dist X G = r)
    (hYR : dist Y R = r) (hYG : dist Y G = r) :
    {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G = r}.Finite := by
  have hRG_ne : R ≠ G := by
    intro h
    rw [h, dist_self] at hRG
    linarith
  have h_subset : {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G = r} ⊆ {X, Y} := by
    intro A ⟨hAR, hAG⟩
    have := two_circles_intersection_at_most_two R G r r hRG_ne X Y hXY hXR hYR hXG hYG A hAR hAG
    simp only [Set.mem_insert_iff, Set.mem_singleton_iff]
    exact this
  exact Set.Finite.subset (Set.toFinite {X, Y}) h_subset

lemma exists_red_point_with_constraints
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (R G : EuclideanSpace ℝ (Fin 2)) (hR : color R = true) (_hG : color G = false)
    (r : ℝ) (hr : 0 < r) (hRG : dist R G = r)
    (X Y : EuclideanSpace ℝ (Fin 2)) (hXY : X ≠ Y)
    (hXR : dist X R = r) (hXG : dist X G = r)
    (hYR : dist Y R = r) (hYG : dist Y G = r)
    (_hX_red : color X = true) (_hY_green : color Y = false) :
    ∃ A : EuclideanSpace ℝ (Fin 2),
      dist A R = r ∧
      color A = true ∧
      dist A G > r / 2 ∧
      dist A G ≠ r ∧
      dist A X ≠ dist A G := by
  let S := {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G > r / 2 ∧ color A = true}
  let Bad₁ := {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A G = r}
  let Bad₂ := {A : EuclideanSpace ℝ (Fin 2) | dist A R = r ∧ dist A X = dist A G}
  have hS_inf : S.Infinite := red_points_far_from_G_infinite color h R G hR r hr hRG
  have hBad₁_fin : Bad₁.Finite := dist_eq_r_finite R G r hr hRG X Y hXY hXR hXG hYR hYG
  have hBad₂_fin : Bad₂.Finite := equidistant_from_X_G_finite R G X r hr hXG
  have hBad_fin : (Bad₁ ∪ Bad₂).Finite := Set.Finite.union hBad₁_fin hBad₂_fin
  have hGood : (S \ (Bad₁ ∪ Bad₂)).Infinite := Set.Infinite.diff hS_inf hBad_fin
  have hGood_ne : (S \ (Bad₁ ∪ Bad₂)).Nonempty := Set.Infinite.nonempty hGood
  obtain ⟨A, hA⟩ := hGood_ne
  use A
  simp only [Set.mem_diff, Set.mem_setOf_eq, Set.mem_union] at hA
  obtain ⟨⟨hAR, hAG_half, hA_red⟩, hNotBad⟩ := hA
  push_neg at hNotBad
  refine ⟨hAR, hA_red, hAG_half, ?_, ?_⟩
  · intro hAG_eq_r
    exact (hNotBad.1 ⟨hAR, hAG_eq_r⟩).elim
  · intro hAX_eq_AG
    exact (hNotBad.2 ⟨hAR, hAX_eq_AG⟩).elim

/-- Define a perpendicular function for 2D vectors -/
def perp2D (v : EuclideanSpace ℝ (Fin 2)) : EuclideanSpace ℝ (Fin 2) :=
  ![-(v 1), v 0]

/-- Show that perp2D gives a perpendicular vector -/
lemma perp2D_inner_eq_zero (v : EuclideanSpace ℝ (Fin 2)) :
    inner ℝ v (perp2D v) = 0 := by
  rw [PiLp.inner_apply, Fin.sum_univ_two]
  simp only [perp2D, RCLike.inner_apply, conj_trivial]
  simp only [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]
  ring

/-- Show that perp2D preserves norm -/
lemma perp2D_norm (v : EuclideanSpace ℝ (Fin 2)) :
    ‖perp2D v‖ = ‖v‖ := by
  simp only [EuclideanSpace.norm_eq, perp2D, Fin.sum_univ_two]
  simp only [Matrix.cons_val_zero, Matrix.cons_val_one, Matrix.head_cons]
  simp only [Real.norm_eq_abs, sq_abs]
  ring_nf

/-- perp of unit is still unit -/
lemma perp2D_unit (v : EuclideanSpace ℝ (Fin 2)) (hv : ‖v‖ = 1) :
    ‖perp2D v‖ = 1 := by
  rw [perp2D_norm, hv]

/-- Key inequality: d > r/2 implies 4d² - r² > 0 -/
lemma key_ineq (r d : ℝ) (hr : 0 < r) (hd : d > r / 2) : 4 * d ^ 2 - r ^ 2 > 0 := by
  have h2 : 2 * d > r := by linarith
  have h3 : (2 * d) ^ 2 > r ^ 2 := sq_lt_sq' (by linarith) h2
  linarith

/-- y₀ > 0 when d > r/2 and r > 0 -/
lemma y_coord_pos (r d : ℝ) (hr : 0 < r) (hd : d > r / 2) :
    r * Real.sqrt (4 * d ^ 2 - r ^ 2) / (2 * d) > 0 := by
  have hd_pos : 0 < d := by linarith
  have h_ineq := key_ineq r d hr hd
  positivity

/-- The algebraic verification: x₀² + y₀² = r² -/
lemma dist_U_G_algebraic (r d : ℝ) (hr : 0 < r) (hd : d > r / 2) :
    let x₀ := r ^ 2 / (2 * d)
    let y₀ := r * Real.sqrt (4 * d ^ 2 - r ^ 2) / (2 * d)
    x₀ ^ 2 + y₀ ^ 2 = r ^ 2 := by
  intro x₀ y₀
  have hd_pos : 0 < d := by linarith
  have h_ineq := key_ineq r d hr hd
  have h_nonneg : 0 ≤ 4 * d ^ 2 - r ^ 2 := by linarith
  simp only [x₀, y₀]
  field_simp
  have h1 : (r * Real.sqrt (4 * d ^ 2 - r ^ 2)) ^ 2 = r ^ 2 * (4 * d ^ 2 - r ^ 2) := by
    rw [mul_pow, Real.sq_sqrt h_nonneg]
  rw [h1]
  ring

/-- The algebraic verification: (x₀ - d)² + y₀² = d² -/
lemma dist_U_A_algebraic (r d : ℝ) (hr : 0 < r) (hd : d > r / 2) :
    let x₀ := r ^ 2 / (2 * d)
    let y₀ := r * Real.sqrt (4 * d ^ 2 - r ^ 2) / (2 * d)
    (x₀ - d) ^ 2 + y₀ ^ 2 = d ^ 2 := by
  intro x₀ y₀
  have hd_pos : 0 < d := by linarith
  have h_ineq := key_ineq r d hr hd
  have h_nonneg : 0 ≤ 4 * d ^ 2 - r ^ 2 := by linarith
  simp only [x₀, y₀]
  field_simp
  have h1 : (r * Real.sqrt (4 * d ^ 2 - r ^ 2)) ^ 2 = r ^ 2 * (4 * d ^ 2 - r ^ 2) := by
    rw [mul_pow, Real.sq_sqrt h_nonneg]
  rw [h1]
  ring

/-- Distance computation for orthonormal pair -/
lemma norm_linear_comb_orthonormal (e₁ e₂ : EuclideanSpace ℝ (Fin 2)) (x y : ℝ)
    (h_orth : inner ℝ e₁ e₂ = 0) (h_norm1 : ‖e₁‖ = 1) (h_norm2 : ‖e₂‖ = 1) :
    ‖x • e₁ + y • e₂‖ ^ 2 = x ^ 2 + y ^ 2 := by
  rw [norm_add_sq_real]
  simp only [norm_smul, Real.norm_eq_abs, inner_smul_left, inner_smul_right]
  rw [h_orth, h_norm1, h_norm2]
  simp only [sq_abs, mul_one, mul_zero]
  ring

/-- Key lemma: distance from G to point constructed via orthonormal pair -/
lemma dist_from_G (G e₁ e₂ : EuclideanSpace ℝ (Fin 2)) (x y : ℝ) (r : ℝ)
    (h_orth : inner ℝ e₁ e₂ = 0) (h_norm1 : ‖e₁‖ = 1) (h_norm2 : ‖e₂‖ = 1)
    (hxy : x ^ 2 + y ^ 2 = r ^ 2) (hr : 0 ≤ r) :
    dist (G + x • e₁ + y • e₂) G = r := by
  rw [dist_eq_norm]
  have h1 : G + x • e₁ + y • e₂ - G = x • e₁ + y • e₂ := by abel
  rw [h1]
  have h2 : ‖x • e₁ + y • e₂‖ ^ 2 = r ^ 2 := by
    rw [norm_linear_comb_orthonormal e₁ e₂ x y h_orth h_norm1 h_norm2, hxy]
  rw [← Real.sqrt_sq hr, ← h2]
  rw [Real.sqrt_sq_eq_abs, abs_norm]

/-- Key lemma: distance from A to point constructed via orthonormal pair
    where A = G + d • e₁ -/
lemma dist_from_A (G e₁ e₂ : EuclideanSpace ℝ (Fin 2)) (x y d : ℝ)
    (h_orth : inner ℝ e₁ e₂ = 0) (h_norm1 : ‖e₁‖ = 1) (h_norm2 : ‖e₂‖ = 1)
    (hxy : (x - d) ^ 2 + y ^ 2 = d ^ 2) (hd : 0 ≤ d) :
    dist (G + x • e₁ + y • e₂) (G + d • e₁) = d := by
  rw [dist_eq_norm]
  have h1 : G + x • e₁ + y • e₂ - (G + d • e₁) = (x - d) • e₁ + y • e₂ := by
    rw [sub_smul]; abel
  rw [h1]
  have h2 : ‖(x - d) • e₁ + y • e₂‖ ^ 2 = d ^ 2 := by
    rw [norm_linear_comb_orthonormal e₁ e₂ (x - d) y h_orth h_norm1 h_norm2, hxy]
  have hn_nonneg : 0 ≤ ‖(x - d) • e₁ + y • e₂‖ := norm_nonneg _
  nlinarith [sq_nonneg ‖(x - d) • e₁ + y • e₂‖, sq_nonneg d]

/-- U and V differ by sign of y -/
lemma U_ne_V (G e₁ e₂ : EuclideanSpace ℝ (Fin 2)) (x y : ℝ)
    (hy : y > 0) (h_norm2 : ‖e₂‖ = 1) :
    G + x • e₁ + y • e₂ ≠ G + x • e₁ + (-y) • e₂ := by
  intro h
  have h1 : y • e₂ = (-y) • e₂ := by
    have : G + x • e₁ + y • e₂ - (G + x • e₁) = G + x • e₁ + (-y) • e₂ - (G + x • e₁) := by
      rw [h]
    simp only [add_sub_cancel_left] at this
    exact this
  have h2 : (2 * y) • e₂ = 0 := by
    have h3 : y • e₂ + y • e₂ = (-y) • e₂ + y • e₂ := by rw [h1]
    simp only [← add_smul] at h3
    have h4 : (y + y) • e₂ = (-y + y) • e₂ := h3
    simp only [neg_add_cancel, zero_smul, ← two_mul] at h4
    exact h4
  have h3 : 2 * y = 0 := by
    have he2_ne : e₂ ≠ 0 := norm_ne_zero_iff.mp (by rw [h_norm2]; exact one_ne_zero)
    exact (smul_eq_zero.mp h2).resolve_right he2_ne
  linarith

lemma two_circles_intersect_condition
    (G A : EuclideanSpace ℝ (Fin 2)) (r : ℝ) (hr : 0 < r)
    (hAG : dist A G > r / 2) :
    ∃ U V : EuclideanSpace ℝ (Fin 2),
      U ≠ V ∧
      dist U G = r ∧ dist U A = dist A G ∧
      dist V G = r ∧ dist V A = dist A G := by
  set d := dist A G with hd_def
  have hd_pos : 0 < d := by linarith
  have hd_half : d > r / 2 := hAG
  let v := A - G
  have hv_norm : ‖v‖ = d := by simp only [v, dist_eq_norm] at hd_def ⊢; rw [hd_def]
  let e₁ := (d⁻¹ : ℝ) • v
  have he₁_norm : ‖e₁‖ = 1 := by
    simp only [e₁, norm_smul, Real.norm_eq_abs, abs_inv, abs_of_pos hd_pos, hv_norm]
    field_simp
  let e₂ := perp2D e₁
  have he₂_norm : ‖e₂‖ = 1 := perp2D_unit e₁ he₁_norm
  have h_orth : inner ℝ e₁ e₂ = 0 := perp2D_inner_eq_zero e₁
  let x₀ := r ^ 2 / (2 * d)
  let y₀ := r * Real.sqrt (4 * d ^ 2 - r ^ 2) / (2 * d)
  have hy₀_pos : y₀ > 0 := y_coord_pos r d hr hd_half
  have h_sum_sq : x₀ ^ 2 + y₀ ^ 2 = r ^ 2 := dist_U_G_algebraic r d hr hd_half
  have h_diff_sq : (x₀ - d) ^ 2 + y₀ ^ 2 = d ^ 2 := dist_U_A_algebraic r d hr hd_half
  have h_sum_sq_neg : x₀ ^ 2 + (-y₀) ^ 2 = r ^ 2 := by simp only [neg_sq]; exact h_sum_sq
  have h_diff_sq_neg : (x₀ - d) ^ 2 + (-y₀) ^ 2 = d ^ 2 := by simp only [neg_sq]; exact h_diff_sq
  let U := G + x₀ • e₁ + y₀ • e₂
  let V := G + x₀ • e₁ + (-y₀) • e₂
  have hA_eq : A = G + d • e₁ := by
    simp only [e₁, smul_smul]
    rw [mul_inv_cancel₀ hd_pos.ne', one_smul]
    simp only [v]
    abel
  use U, V
  refine ⟨?_, ?_, ?_, ?_, ?_⟩
  · exact U_ne_V G e₁ e₂ x₀ y₀ hy₀_pos he₂_norm
  · exact dist_from_G G e₁ e₂ x₀ y₀ r h_orth he₁_norm he₂_norm h_sum_sq hr.le
  · rw [hA_eq]
    exact dist_from_A G e₁ e₂ x₀ y₀ d h_orth he₁_norm he₂_norm h_diff_sq hd_pos.le
  · exact dist_from_G G e₁ e₂ x₀ (-y₀) r h_orth he₁_norm he₂_norm h_sum_sq_neg hr.le
  · rw [hA_eq]
    exact dist_from_A G e₁ e₂ x₀ (-y₀) d h_orth he₁_norm he₂_norm h_diff_sq_neg hd_pos.le

/-- The key construction: given a red point A and green point G, consider the circle
    centered at A with radius dist A G. This circle passes through G.
    If U, V are two distinct points on the intersection of this circle with circle_G
    (centered at G with radius r), and G is on the A-centered circle,
    then at least one of U, V is red.

    Proof: The circle centered at red A contains green G. By the density lemma,
    this circle has at most 2 green points. If both U and V were green,
    together with G that would be 3 green points on the circle, contradicting ≤2.
    Hence at least one of U, V is red. -/
lemma at_least_one_intersection_red
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (G A : EuclideanSpace ℝ (Fin 2))
    (hA_red : color A = true) (hG_green : color G = false)
    (r : ℝ) (_hr : 0 < r)
    (U V : EuclideanSpace ℝ (Fin 2)) (hUV : U ≠ V)
    (_hUG : dist U G = r) (_hVG : dist V G = r)
    (hUA : dist U A = dist A G) (hVA : dist V A = dist A G)
    (hGU : G ≠ U) (hGV : G ≠ V) :
    color U = true ∨ color V = true := by
  by_contra h_neg
  push_neg at h_neg
  have hU_green : color U = false := Bool.eq_false_iff.mpr h_neg.1
  have hV_green : color V = false := Bool.eq_false_iff.mpr h_neg.2

  have hAG_ne : A ≠ G := fun h_eq => by rw [h_eq] at hA_red; simp [hA_red] at hG_green
  have hAG_pos : 0 < dist A G := dist_pos.mpr hAG_ne


  have hG_on : dist G A = dist A G := dist_comm G A

  have hA_green : color A = false :=
    circumcenter_color_of_three_same_color_on_sphere color h A (dist A G) hAG_pos
      G U V hG_on hUA hVA hGU hUV hGV false hG_green hU_green hV_green

  simp [hA_green] at hA_red

/-- U and V (intersection of circle_G and circle(A, dist A G)) are distinct from R and X.
    - U ≠ R: We have dist A R = r and dist A G ≠ r, so dist U A = dist A G ≠ r = dist A R.
      If U = R, then dist A R = dist A G, contradiction.
    - U ≠ X: We have dist A X ≠ dist A G. If U = X, then dist A X = dist U A = dist A G, contradiction.

    Note: This lemma now includes G in the signature (fixing the previous bug). -/
lemma intersection_distinct_from_R_X
    (R G X A : EuclideanSpace ℝ (Fin 2))
    (r : ℝ) (_hr : 0 < r)
    (hAR : dist A R = r) (hAG_ne_r : dist A G ≠ r)
    (hAX_ne_AG : dist A X ≠ dist A G)
    (U : EuclideanSpace ℝ (Fin 2))
    (hUA : dist U A = dist A G) :
    U ≠ R ∧ U ≠ X := by
  have hU_ne_R : U ≠ R := by
    intro h
    have h₁ : dist U A = dist R A := by rw [h]
    have h₂ : dist R A = dist A R := dist_comm R A
    have h₅ : dist A G = r := by linarith
    have h₆ : dist A G ≠ r := hAG_ne_r
    exact h₆ h₅

  have hU_ne_X : U ≠ X := by
    intro h
    have h₁ : dist U A = dist X A := by rw [h]
    have h₂ : dist X A = dist A X := dist_comm X A
    have h₄ : dist A X = dist A G := by linarith
    have h₅ : dist A X ≠ dist A G := hAX_ne_AG
    exact h₅ h₄

  have h_main : U ≠ R ∧ U ≠ X := by
    exact ⟨hU_ne_R, hU_ne_X⟩

  exact h_main

/-- U ≠ G when U is on circle(A, dist A G) and U is also on circle_G (radius r),
    but dist A G ≠ r. If U = G, then dist A G = dist A U = dist G G = 0, but dist A G > r/2 > 0. -/
lemma intersection_distinct_from_G
    (G A : EuclideanSpace ℝ (Fin 2))
    (r : ℝ) (hr : 0 < r)
    (_hAG_pos : dist A G > r / 2)
    (U : EuclideanSpace ℝ (Fin 2))
    (_hUA : dist U A = dist A G)
    (hUG : dist U G = r) :
    G ≠ U := by
  have h_main : G ≠ U := by
    intro h
    have h1 : dist U G = 0 := by
      rw [h]
      simp [dist_eq_norm]
    linarith
  exact h_main

/-- The final contradiction: if we have 3 distinct red points R, X, W all on circle_G
    (centered at green G with radius r), this contradicts the density lemma which says
    there are at most 2 red points on that circle. -/
lemma three_red_points_contradiction
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (G : EuclideanSpace ℝ (Fin 2)) (hG : color G = false)
    (r : ℝ) (hr : 0 < r)
    (R X W : EuclideanSpace ℝ (Fin 2))
    (hR_on : dist R G = r) (hX_on : dist X G = r) (hW_on : dist W G = r)
    (hR_red : color R = true) (hX_red : color X = true) (hW_red : color W = true)
    (hRX : R ≠ X) (hRW : R ≠ W) (hXW : X ≠ W) :
    False := by
  have hG_red : color G = true :=
    circumcenter_color_of_three_same_color_on_sphere color h G r hr R X W
      hR_on hX_on hW_on hRX hXW hRW true hR_red hX_red hW_red
  rw [hG_red] at hG
  exact Bool.noConfusion hG

/-- Main contradiction: assuming both colors exist (a red R and green G) leads to False.

    Proof outline:
    1. Let r = dist R G > 0 (since R ≠ G and they have different colors).
    2. By two_circles_equal_radius_intersect_existence, the circles ω_R (centered at R, radius r)
       and ω_G (centered at G, radius r) intersect in two points X, Y.
    3. By intersection_points_different_colors, X and Y have different colors.
       WLOG assume X is red and Y is green.
    4. By exists_red_point_with_constraints, there exists a red point A on ω_R with:
       - dist A G > r/2
       - dist A G ≠ r
       - dist A X ≠ dist A G
    5. By two_circles_intersect_condition, the circle γ (centered at A, radius dist A G)
       intersects ω_G in two points U, V.
    6. By at_least_one_intersection_red, at least one of U, V is red. Call it W.
    7. By intersection_distinct_from_R_X, W ≠ R and W ≠ X.
    8. Now ω_G contains three distinct red points: R (since hRG: dist R G = r), X, and W.
       But by at_most_two_opposite_color_on_sphere (with green center G), ω_G has ≤2 red points.
    9. Contradiction via three_red_points_contradiction. -/
lemma both_colors_contradiction
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0))
    (R G : EuclideanSpace ℝ (Fin 2)) (hR : color R = true) (hG : color G = false)
    (hRG_ne : R ≠ G) :
    False := by
  set r := dist R G with hr_def
  have hr : 0 < r := by
    rw [hr_def]
    exact dist_pos.mpr hRG_ne
  obtain ⟨X, Y, hXY, hXR, hXG, hYR, hYG⟩ := two_circles_equal_radius_intersect_existence R G r hr rfl
  have hXY_color : color X ≠ color Y := intersection_points_different_colors color h R G hR hG r hr rfl X Y hXY hXR hXG hYR hYG
  rcases Bool.dichotomy (color X) with hX_green | hX_red
  case inl =>
    have hY_red : color Y = true := by
      cases hy : color Y with
      | true => rfl
      | false => simp [hX_green, hy] at hXY_color
    obtain ⟨A, hAR, hA_red, hAG_half, hAG_ne_r, hAY_ne_AG⟩ :=
      exists_red_point_with_constraints color h R G hR hG r hr rfl Y X hXY.symm hYR hYG hXR hXG hY_red hX_green
    obtain ⟨U, V, hUV, hUG, hUA, hVG, hVA⟩ := two_circles_intersect_condition G A r hr hAG_half
    have hGU : G ≠ U := intersection_distinct_from_G G A r hr hAG_half U hUA hUG
    have hGV : G ≠ V := intersection_distinct_from_G G A r hr hAG_half V hVA hVG
    have hUV_one_red : color U = true ∨ color V = true :=
      at_least_one_intersection_red color h G A hA_red hG r hr U V hUV hUG hVG hUA hVA hGU hGV
    rcases hUV_one_red with hU_red | hV_red
    case inl =>
      have ⟨hU_ne_R, hU_ne_Y⟩ := intersection_distinct_from_R_X R G Y A r hr hAR hAG_ne_r hAY_ne_AG U hUA
      have hRY : R ≠ Y := fun h_eq => by
        have : dist Y R = 0 := by simp [h_eq]
        rw [hYR] at this; linarith
      have hYU : Y ≠ U := hU_ne_Y.symm
      exact three_red_points_contradiction color h G hG r hr R Y U rfl hYG hUG hR hY_red hU_red hRY hU_ne_R.symm hYU
    case inr =>
      have ⟨hV_ne_R, hV_ne_Y⟩ := intersection_distinct_from_R_X R G Y A r hr hAR hAG_ne_r hAY_ne_AG V hVA
      have hRY : R ≠ Y := fun h_eq => by
        have : dist Y R = 0 := by simp [h_eq]
        rw [hYR] at this; linarith
      have hYV : Y ≠ V := hV_ne_Y.symm
      exact three_red_points_contradiction color h G hG r hr R Y V rfl hYG hVG hR hY_red hV_red hRY hV_ne_R.symm hYV
  case inr =>
    have hY_green : color Y = false := by
      cases hy : color Y with
      | true => simp [hX_red, hy] at hXY_color
      | false => rfl
    obtain ⟨A, hAR, hA_red, hAG_half, hAG_ne_r, hAX_ne_AG⟩ :=
      exists_red_point_with_constraints color h R G hR hG r hr rfl X Y hXY hXR hXG hYR hYG hX_red hY_green
    obtain ⟨U, V, hUV, hUG, hUA, hVG, hVA⟩ := two_circles_intersect_condition G A r hr hAG_half
    have hGU : G ≠ U := intersection_distinct_from_G G A r hr hAG_half U hUA hUG
    have hGV : G ≠ V := intersection_distinct_from_G G A r hr hAG_half V hVA hVG
    have hUV_one_red : color U = true ∨ color V = true :=
      at_least_one_intersection_red color h G A hA_red hG r hr U V hUV hUG hVG hUA hVA hGU hGV
    rcases hUV_one_red with hU_red | hV_red
    case inl =>
      have ⟨hU_ne_R, hU_ne_X⟩ := intersection_distinct_from_R_X R G X A r hr hAR hAG_ne_r hAX_ne_AG U hUA
      have hRX : R ≠ X := fun h_eq => by
        have : dist X R = 0 := by simp [h_eq]
        rw [hXR] at this; linarith
      have hXU : X ≠ U := hU_ne_X.symm
      exact three_red_points_contradiction color h G hG r hr R X U rfl hXG hUG hR hX_red hU_red hRX hU_ne_R.symm hXU
    case inr =>
      have ⟨hV_ne_R, hV_ne_X⟩ := intersection_distinct_from_R_X R G X A r hr hAR hAG_ne_r hAX_ne_AG V hVA
      have hRX : R ≠ X := fun h_eq => by
        have : dist X R = 0 := by simp [h_eq]
        rw [hXR] at this; linarith
      have hXV : X ≠ V := hV_ne_X.symm
      exact three_red_points_contradiction color h G hG r hr R X V rfl hXG hVG hR hX_red hV_red hRX hV_ne_R.symm hXV

theorem putnam_2025_b1
    (color : EuclideanSpace ℝ (Fin 2) → Bool)
    (h : ∀ (s : Simplex ℝ (EuclideanSpace ℝ (Fin 2)) 2),
      (∀ i j : Fin 3, color (s.points i) = color (s.points j)) →
      color s.circumcenter = color (s.points 0)) :
    ∃ c : Bool, ∀ P : EuclideanSpace ℝ (Fin 2), color P = c := by
  by_cases h_mono : ∀ P Q : EuclideanSpace ℝ (Fin 2), color P = color Q
  ·
    use color 0
    intro P
    exact h_mono P 0
  ·
    push_neg at h_mono
    obtain ⟨R, G, hRG_color⟩ := h_mono
    rcases Bool.dichotomy (color R) with hR | hR
    ·
      have hG : color G = true := by
        cases hG_eq : color G with
        | true => rfl
        | false => simp [hR, hG_eq] at hRG_color
      have hGR : G ≠ R := fun h_eq => by simp [← h_eq, hG] at hR
      exact absurd (both_colors_contradiction color h G R hG hR hGR) False.elim
    ·
      have hG : color G = false := by
        cases hG_eq : color G with
        | true => simp [hR, hG_eq] at hRG_color
        | false => rfl
      have hRG : R ≠ G := fun h_eq => by rw [h_eq] at hR; simp [hR] at hG
      exact absurd (both_colors_contradiction color h R G hR hG hRG) False.elim
