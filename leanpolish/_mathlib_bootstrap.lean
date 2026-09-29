-- Bootstrap header for the mathlib_optimization corpus run.
-- Loads the umbrella modules `Mathlib` and `Batteries`, which
-- transitively import every submodule in the mathlib4 + Batteries
-- packages.  Pair with `--umbrella Mathlib --umbrella Batteries` on
-- the orchestrator so that candidate files importing
-- `Mathlib.X.Y` / `Batteries.Z` pass the soundness pre-filter.
import Mathlib
import Batteries
