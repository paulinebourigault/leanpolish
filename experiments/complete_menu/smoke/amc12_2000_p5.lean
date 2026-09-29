import Mathlib
import Aesop
set_option maxHeartbeats 0
open BigOperators Real Nat Topology Rat
set_option linter.all false
set_option linter.deprecated false
set_option linter.unusedVariables false

theorem amc12_2000_p5 (x p : ℝ) (h₀ : x < 2) (h₁ : abs (x - 2) = p) : x - p = 2 - 2 * p := by
  have h₂ : p = 2 - x := by
    have h₂₁ : x - 2 < 0 := by linarith
    have h₂₂ : abs (x - 2) = -(x - 2) := by
      rw [abs_of_neg h₂₁]
      <;> linarith
    rw [h₂₂] at h₁
    -- Now we have -(x - 2) = p, which simplifies to 2 - x = p
    linarith
  
  have h₃ : x - p = 2 - 2 * p := by
    have h₃₁ : x = 2 - p := by linarith
    rw [h₃₁]
    <;> ring_nf
    <;> linarith
  
  apply h₃
