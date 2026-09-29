import Mathlib
import Aesop

set_option maxHeartbeats 0

open BigOperators Real Nat Topology Rat

/- Prove that \\( \\dfrac{1}{2a+b+6} + \\dfrac{1}{2b+c+6} + \\dfrac{1}{2c+a+6} \le \\dfrac{1}{4} \\) for positive real numbers \\( a,b,c \\) such that \\( abc = 8 \\) -/
theorem lean_workbook_38886 (a b c : ℝ) (ha : 0 < a) (hb : 0 < b) (hc : 0 < c) (habc : a * b * c = 8) : 1 / (2 * a + b + 6) + 1 / (2 * b + c + 6) + 1 / (2 * c + a + 6) ≤ 1 / 4  := by
  /-
  To prove the inequality \(\dfrac{1}{2a+b+6} + \dfrac{1}{2b+c+6} + \dfrac{1}{2c+a+6} \le \dfrac{1}{4}\) for positive real numbers \(a, b, c\) such that \(abc = 8\), we proceed as follows:
  1. **Establish Positivity of Denominators**: Since \(a, b, c\) are positive, we have \(2a + b + 6 > 0\), \(2b + c + 6 > 0\), and \(2c + a + 6 > 0\).
  2. **Simplify the Fractions**: Clear the denominators by multiplying through by the common denominator \((2a + b + 6)(2b + c + 6)(2c + a + 6)\).
  3. **Combine and Simplify**: Combine the terms and simplify the expression.
  4. **Use Non-negativity and Inequalities**: Utilize the non-negativity of squares and linear inequalities to show that the simplified expression is less than or equal to \(\dfrac{1}{4}\).
  -/
  have h₀ : 0 < a * b := by
    -- Since a and b are positive, their product is also positive.
    apply mul_pos ha hb
  have h₁ : 0 < a * c := by
    -- Since a and c are positive, their product is also positive.
    apply mul_pos ha hc
  have h₂ : 0 < b * c := by
    -- Since b and c are positive, their product is also positive.
    apply mul_pos hb hc
  -- Establish the positivity of the denominators.
  have h₃ : 0 < 2 * a + b + 6 := by
    -- Since a, b, and c are positive, 2a + b + 6 is positive.
    linarith
  have h₄ : 0 < 2 * b + c + 6 := by
    -- Since b and c are positive, 2b + c + 6 is positive.
    linarith
  have h₅ : 0 < 2 * c + a + 6 := by
    -- Since c and a are positive, 2c + a + 6 is positive.
    linarith
  -- Clear the denominators by multiplying through by the common denominator.
  field_simp [h₃, h₄, h₅]
  -- Combine and simplify the terms.
  rw [div_le_div_iff (by positivity) (by positivity)]
  ring_nf
  -- Use non-negativity of squares and linear inequalities to show the desired inequality.
  nlinarith [sq_nonneg (a + b + c - 6), sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a)]
