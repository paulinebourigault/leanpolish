import Lake
open Lake DSL

package LeanPolish where
  leanOptions := #[
    ⟨`pp.unicode.fun, true⟩,
    ⟨`autoImplicit, false⟩
  ]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "v4.21.0"

require batteries from git
  "https://github.com/leanprover-community/batteries" @ "v4.21.0"

require aesop from git
  "https://github.com/leanprover-community/aesop" @ "v4.21.0"

require Qq from git
  "https://github.com/leanprover-community/quote4" @ "v4.21.0"

lean_exe LeanPolish where
  root := `LeanPolish
  supportInterpreter := true

lean_exe LinterBaseline where
  root := `LinterBaseline
  supportInterpreter := true