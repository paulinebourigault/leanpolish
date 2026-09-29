import Mathlib
import Aesop
set_option maxHeartbeats 0
open BigOperators Real Nat Topology Rat
set_option linter.all false
set_option linter.deprecated false
set_option linter.unusedVariables false

theorem algebra_sqineq_36azm9asqle36zsq (z a : ℝ) : 36 * (a * z) - 9 * a ^ 2 ≤ 36 * z ^ 2 := by
  have h_main : 36 * z ^ 2 - 36 * (a * z) + 9 * a ^ 2 ≥ 0 := by
    have h1 : 36 * z ^ 2 - 36 * (a * z) + 9 * a ^ 2 = (6 * z - 3 * a) ^ 2 := by
      ring_nf
      <;>
      linarith
    rw [h1]
    nlinarith [sq_nonneg (6 * z - 3 * a)]
  
  have h_final : 36 * (a * z) - 9 * a ^ 2 ≤ 36 * z ^ 2 := by
    have h2 : 36 * z ^ 2 - 36 * (a * z) + 9 * a ^ 2 ≥ 0 := h_main
    -- Rearrange the inequality to match the desired form
    have h3 : 36 * (a * z) - 9 * a ^ 2 ≤ 36 * z ^ 2 := by
      linarith
    exact h3
  
  exact h_final
