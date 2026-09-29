import Lean
import Mathlib

open Lean Elab Meta Command Parser Term Tactic System Frontend

/-!
# LeanPolish : Lean 4 Proof Shortener

A proof optimization tool that shortens Lean 4 proofs while
preserving correctness.  Loads the Mathlib environment once,
then processes input files in-process.

## Optimization phases

1. Phase 1 : Tactic replacement (fold).
   Walks the elaborated InfoTree to find tactic blocks replaceable by shorter
   automation.  15 tactics are tried in priority order (most specific first):
   `rfl` > `ring` = `abel` > `norm_num` > `norm_cast` > `positivity` >
   `decide` (5 s cap) > `linarith` > `omega` > `field_simp` (5 s cap) >
   `contradiction` > `ext` > `gcongr` > `tauto` (5 s cap) >
   `simp?` → squeezed `simp only [...]` (5 s cap).
   Library search via `exact?` (bounded heartbeats, max 15 calls/file) is
   attempted when no deterministic tactic matches.

2. Phase 1.5 : L1 have-block deduplication and L2 anti-unification.
   L1: exact-duplicate `have` blocks (same type + proof text) are replaced
   by `exact <firstHypName>`.
   L2: near-duplicate blocks are grouped by Expr-level anti-unification;
   when profitable, a shared lemma is extracted and duplicates call it.

3. Phase 2 : Dead code removal.
   Removes `have`/`haveI` blocks whose introduced hypothesis is never
   referenced (FVar usage DAG analysis across all InfoTrees).

4. Phase 3 : Warning-guided cleanup (up to 3 rounds).
   Re-elaborates with linters, then removes dead `<;>` arms, never-executed
   tactics, and converts `<;>` → `;` where sufficient.

5. Final safety verification.
   Re-elaborates the fully modified text to confirm zero errors.

## Design principles

1. Leaf-level candidates only : never at structural wrapper kinds
   (`null`, `tacticSeq`, `tacticSeq1Indented`, `paren`, etc.) to prevent
   overlapping or duplicated replacements.
2. Outermost replaceable node preferred : when a `byTactic` node and
   its inner tactic both succeed, only the `byTactic` node is recorded so
   the replacement text `by <tac>` is syntactically complete.
3. Quality hierarchy : a tactic may only be replaced by one of equal
   or higher mathematical specificity.  Witness tactics (`exact`, `rw`,
   `apply`, …) are never replaced unless they are multi-step blocks.
4. Greedy overlap selection : candidates sorted by byte savings
   descending; largest wins picked first.
5. In-process verification : modified text is re-elaborated using the
   already-loaded import environment.  Errors come as structured
   `MessageData` with source positions, mapped back to candidates.
   Up to 4 verification rounds with error-blame and re-selection.
6. Adaptive time budgets : fold budget = max(120 s, 3× elaboration),
   exact? budget = max(180 s, 2× elaboration), verify budget =
   max(420 s, 5× elaboration).  Per-goal cap of 30 s on automation search.

## Training data

Emits contrastive training pairs (JSON) with the original tactic,
the replacement, and the list of tactics that failed on each goal.

## Usage

```
lake build LeanPolish
lake env .lake/build/bin/LeanPolish [flags] file1.lean [file2.lean ...]
```

All files share the import environment loaded from the first file's header.
Usually invoked through `leanpolish.py`, `run_goedel.py`, `run_mathlib.py`
or `run_worker_pool.py` (`--worker` mode).
-/

-- ═══════════════════════════════════════════════════════════════════════════
-- Helpers
-- ═══════════════════════════════════════════════════════════════════════════

/- Catch all exceptions including `interrupted` (which Lean's default MonadExcept
    instances skip). Required for cleanup after CancelToken-based timeouts.
    Uses the `attribute [-instance]` pattern from MathlibTest/tactic_timeout.lean. -/
attribute [-instance]
  Lean.instMonadExceptOfExceptionCoreM Lean.Elab.Tactic.instMonadExceptExceptionTacticM

private def TermElabM.tryCatchAll {α : Type} (x : TermElabM α) (h : Exception → TermElabM α) :
    TermElabM α := tryCatch x h

/-- Run a TermElabM computation with a timeout using IO.CancelToken.
    The computation runs on the current thread (preserving all MetaM/CoreM state).
    A thread sleeps for `ms` milliseconds then sets the cancel token.
    Lean's tactic machinery checks `cancelTk?` at regular intervals and throws
    `interrupted` when set.

    This is the only thread-safe pattern for MetaM timeouts in Lean 4.
    See: MathlibTest/tactic_timeout.lean -/
def withTimeoutMs {α : Type} (ms : UInt32) (action : TermElabM α) : TermElabM (Option α) := do
  let tk ← IO.CancelToken.new
  withTheReader Core.Context (fun ctx => { ctx with cancelTk? := some tk }) do
    let watchdog ← IO.asTask do
      IO.sleep ms
      tk.set
    let result ← TermElabM.tryCatchAll (some <$> action) fun e => do
      IO.cancel watchdog
      if e.isInterrupt then
        -- Timeout : tactic took too long, return none
        return none
      else
        -- Re-throw non-timeout exceptions (tactic failure, etc.)
        throw e
    IO.cancel watchdog
    return result

def hasLeakage (mctxBefore mctxAfter : MetavarContext) (mainGoal : MVarId) : Bool :=
  let leakE := mctxAfter.eAssignment.foldl (init := false) fun leak mvarId _ =>
    leak || (mvarId != mainGoal && mctxBefore.decls.contains mvarId && !(mctxBefore.eAssignment.contains mvarId))
  let leakD := mctxAfter.dAssignment.foldl (init := false) fun leak mvarId _ =>
    leak || (mctxBefore.decls.contains mvarId && !(mctxBefore.dAssignment.contains mvarId))
  leakE || leakD

/-- Run a tactic string against `mainGoal` and report
    `(success, goalType, tryThisText, assignmentSize, errMsg, wallMs)`.
    On success, `errMsg = ""`. On failure, `errMsg` is the first error
    diagnostic (truncated to 200 chars, newlines flattened).
    `wallMs` is monotonic-clock wall time spent inside `Tactic.run`. -/
def runTacticString (mainGoal : MVarId) (tac : String) (mctxBefore : MetavarContext)
    : TermElabM (Bool × String × String × Nat × String × Nat) := do
  let env ← getEnv
  match Parser.runParserCategory env `tactic tac with
  | Except.ok stx =>
    let s ← saveState
    let t0 ← IO.monoMsNow
    try
      let mvarDecl ← mainGoal.getDecl
      let (success, gt, cleanTry, assignmentSize, errMsg) ← withLCtx mvarDecl.lctx mvarDecl.localInstances do
        let msgsBefore ← Core.getMessageLog
        Core.setMessageLog {}
        let goals ← Tactic.run mainGoal (evalTactic stx)
        let msgsAfter ← Core.getMessageLog
        Core.setMessageLog (msgsBefore.append msgsAfter)

        let mctxAfter ← getMCtx
        let typeStr ← instantiateMVars mvarDecl.type
        let noNewErrors := !msgsAfter.hasErrors

        let mut cleanTryStr := ""
        let mut firstErr := ""
        for msg in msgsAfter.toList do
          let data ← msg.data.toString
          if data.startsWith "Try this: " then
            cleanTryStr := data.drop 10 |>.map (fun c => if c == '\n' then ' ' else c)
          if msg.severity == .error && firstErr.isEmpty then
            firstErr := (data.take 200).map (fun c => if c == '\n' then ' ' else c)

        let assignmentSize := mctxAfter.eAssignment.toArray.size
        -- Reject proofs containing sorry (unsound replacement)
        let hasSorry := match mctxAfter.eAssignment.find? mainGoal with
          | some expr => expr.find? (fun e => e.isConstOf ``sorryAx) |>.isSome
          | none => false
        let succ := goals.isEmpty && noNewErrors && !hasLeakage mctxBefore mctxAfter mainGoal && !hasSorry
        let errMsg :=
          if succ then ""
          else if !firstErr.isEmpty then firstErr
          else if !goals.isEmpty then s!"unsolved goals ({goals.length})"
          else if hasSorry then "introduces sorry"
          else "metavariable leakage"
        return (succ, s!"{typeStr}", cleanTryStr, assignmentSize, errMsg)
      s.restore
      let dt := (← IO.monoMsNow) - t0
      return (success, gt, cleanTry, assignmentSize, errMsg, dt)
    catch e =>
      -- Handle both normal exceptions and interrupted (CancelToken timeout).
      -- Normal tactic failures produce Except.error handled above; true exceptions
      -- are OOM/stack overflow/timeout.
      s.restore
      if e.isInterrupt then
        -- CancelToken timeout : propagate so withTimeoutMs sees it
        throw e
      let msg ← try e.toMessageData.toString catch _ => pure "<unknown>"
      if msg.containsSubstr "out of memory" || msg.containsSubstr "stack overflow" ||
         msg.containsSubstr "deep recursion" || msg.containsSubstr "maximum recursion" then
        IO.println s!"[WARN] runTacticString exception for `{tac}`: {msg.take 120}"
      let dt := (← IO.monoMsNow) - t0
      let errStr := (msg.take 200).map (fun c => if c == '\n' then ' ' else c)
      return (false, "", "", 0, errStr, dt)
  | Except.error e =>
    let errStr := (toString e).take 200 |>.map (fun c => if c == '\n' then ' ' else c)
    return (false, "", "", 0, s!"parse error: {errStr}", 0)

/-- Test automation tactics in priority order.
    Ordered by mathematical specificity: decision procedures > domain-specific > generic.

    Tactics fall into two categories:
    • Fast tactics (tiers 1-3.5, 4-5): terminate quickly on any input. Run directly.
    • Slow tactics (tiers 3.7, 4.5, 5.5): can hang on large goals (`decide` does exponential
      case analysis, `field_simp` can loop, `tauto` explores exponential search spaces).
      Run inside `withTimeoutMs` with a 5s cooperative CancelToken budget.

    Current set (15 tactics): rfl, ring, abel, norm_num, norm_cast, positivity,
    decide (5s cap), linarith, omega, field_simp (5s cap), contradiction, ext,
    gcongr, tauto (5s cap), simp? (squeezed to simp only).

    Returns `none` if no shorter tactic found, or `some (tac, goalType, termSize)`.
    Accumulates `(tacName, errMsg, wallMs)` triples for tried-but-failed tactics
    in `failedRef` for contrastive training data - REJECTED_PAIR
    JSON carries the error verbatim and wall-time per attempt. -/
def checkAutomations (goal : MVarId) (ti : TacticInfo) (origLen : Nat)
    (failedRef : IO.Ref (Array (String × String × Nat))) : MetaM (Option (String × String × Nat)) := do
  try
    withMCtx ti.mctxBefore do
      TermElabM.run' do
        -- ═══════════════════════════════════════════════════════════════
        -- Safety gate: only replace tactics whose goal is a Prop.
        --
        -- For theorems/lemmas, the goal type is a Prop, and Lean's kernel
        -- guarantees proof irrelevance - any closed proof of the same Prop
        -- is definitionally correct. Automation tactics are safe here.
        --
        -- For definitions (`def f : T := by ...` where T : Type u), the
        -- goal type is a data type, not a Prop. Any term of type T closes
        -- the goal (e.g., `norm_cast` might return a local hypothesis),
        -- but the resulting definition may be semantically wrong while the
        -- file still compiles. The tool's whole-file verification cannot
        -- catch this because correctness of `def` is not checked by type
        -- theory - only type-correctness is guaranteed.
        --
        -- Example: `balance l x r : Ordnode α := by norm_cast` compiles
        -- (norm_cast closes `⊢ Ordnode α` by returning `l`), but the
        -- resulting balance function is a constant function, breaking all
        -- downstream theorems about tree rebalancing.
        -- ═══════════════════════════════════════════════════════════════
        let goalType ← goal.getType
        unless ← Meta.isProp goalType do
          return none

        -- ═══════════════════════════════════════════════════════════════
        -- Priority order: most specific/mathematical first.
        -- Each tier represents a narrower mathematical domain.
        -- A tactic from a higher tier is always preferred over a lower one.
        --
        -- Each failed-tier branch records `(name, errMsg, wallMs)` in
        -- `failedRef`. For tactics wrapped in `withTimeoutMs`, the inner
        -- block stashes `(errMsg, wallMs)` into a small per-call Ref so
        -- that on timeout we still record `("timeout (Nms)", outerWall)`.
        -- ═══════════════════════════════════════════════════════════════

        -- Tier 1: rfl (definitional equality)
        if origLen > 3 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "rfl" ti.mctxBefore
          if suc then return some ("rfl", gt, ts)
          failedRef.modify (·.push ("rfl", em, dt))

        -- Tier 2: Algebraic decision procedures (exact for their domain)
        if origLen > 4 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "ring" ti.mctxBefore
          if suc then return some ("ring", gt, ts)
          failedRef.modify (·.push ("ring", em, dt))
        if origLen > 4 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "abel" ti.mctxBefore
          if suc then return some ("abel", gt, ts)
          failedRef.modify (·.push ("abel", em, dt))

        -- Tier 3: Numeric/domain-specific normalizers
        if origLen > 8 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "norm_num" ti.mctxBefore
          if suc then return some ("norm_num", gt, ts)
          failedRef.modify (·.push ("norm_num", em, dt))
        if origLen > 9 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "norm_cast" ti.mctxBefore
          if suc then return some ("norm_cast", gt, ts)
          failedRef.modify (·.push ("norm_cast", em, dt))

        -- Tier 3.5: Positivity : decision procedure for 0 ≤ x, 0 < x goals
        if origLen > 11 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "positivity" ti.mctxBefore
          if suc then return some ("positivity", gt, ts)
          failedRef.modify (·.push ("positivity", em, dt))

        -- Tier 3.7: decide : complete decision procedure for decidable propositions.
        -- Runs with a 5s CancelToken timeout because case analysis can be exponential
        -- on large types (e.g., Fin 256 × Fin 256); cooperative cancellation
        -- makes this safe.
        if origLen > 6 then
          let infoRef ← IO.mkRef (none : Option (String × Nat))
          let t0 ← IO.monoMsNow
          let r ← withTimeoutMs 5000 do
            let (suc, gt, _, ts, em, dt) ← runTacticString goal "decide" ti.mctxBefore
            infoRef.set (some (em, dt))
            if suc then return some ("decide", gt, ts)
            return none
          let outerDt := (← IO.monoMsNow) - t0
          if let some (some result) := r then return some result
          match ← infoRef.get with
          | some (em, dt) => failedRef.modify (·.push ("decide", em, dt))
          | none          => failedRef.modify (·.push ("decide", "timeout (5000ms)", outerDt))

        -- Tier 4: Arithmetic solvers
        if origLen > 8 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "linarith" ti.mctxBefore
          if suc then return some ("linarith", gt, ts)
          failedRef.modify (·.push ("linarith", em, dt))
        if origLen > 5 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "omega" ti.mctxBefore
          if suc then return some ("omega", gt, ts)
          failedRef.modify (·.push ("omega", em, dt))

        -- Tier 4.5: field_simp : clears denominators in field expressions.
        -- Can loop on tricky field expressions; 5s CancelToken timeout.
        if origLen > 10 then
          let infoRef ← IO.mkRef (none : Option (String × Nat))
          let t0 ← IO.monoMsNow
          let r ← withTimeoutMs 5000 do
            let (suc, gt, _, ts, em, dt) ← runTacticString goal "field_simp" ti.mctxBefore
            infoRef.set (some (em, dt))
            if suc then return some ("field_simp", gt, ts)
            return none
          let outerDt := (← IO.monoMsNow) - t0
          if let some (some result) := r then return some result
          match ← infoRef.get with
          | some (em, dt) => failedRef.modify (·.push ("field_simp", em, dt))
          | none          => failedRef.modify (·.push ("field_simp", "timeout (5000ms)", outerDt))

        -- Tier 5: Structural solvers
        if origLen > 13 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "contradiction" ti.mctxBefore
          if suc then return some ("contradiction", gt, ts)
          failedRef.modify (·.push ("contradiction", em, dt))
        if origLen > 3 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "ext" ti.mctxBefore
          if suc then return some ("ext", gt, ts)
          failedRef.modify (·.push ("ext", em, dt))
        if origLen > 6 then
          let (suc, gt, _, ts, em, dt) ← runTacticString goal "gcongr" ti.mctxBefore
          if suc then return some ("gcongr", gt, ts)
          failedRef.modify (·.push ("gcongr", em, dt))

        -- Tier 5.5: tauto : propositional logic tautology checker.
        -- Explores an exponential search space; 5s CancelToken timeout.
        if origLen > 5 then
          let infoRef ← IO.mkRef (none : Option (String × Nat))
          let t0 ← IO.monoMsNow
          let r ← withTimeoutMs 5000 do
            let (suc, gt, _, ts, em, dt) ← runTacticString goal "tauto" ti.mctxBefore
            infoRef.set (some (em, dt))
            if suc then return some ("tauto", gt, ts)
            return none
          let outerDt := (← IO.monoMsNow) - t0
          if let some (some result) := r then return some result
          match ← infoRef.get with
          | some (em, dt) => failedRef.modify (·.push ("tauto", em, dt))
          | none          => failedRef.modify (·.push ("tauto", "timeout (5000ms)", outerDt))

        -- Tier 6: General rewriting (least specific, last resort)
        -- Use `simp?` to obtain the squeezed `simp only [...]` form, which is
        -- strictly more robust (survives Mathlib changes), more transparent
        -- (reader sees which lemmas are used), and faster to elaborate.
        -- Bare `simp` is never emitted because it can produce huge proof terms.
        -- 5s CancelToken timeout: simp? performs library search which can be
        -- unbounded on complex goals.
        if origLen > 4 then
          let infoRef ← IO.mkRef (none : Option (String × Nat))
          let t0 ← IO.monoMsNow
          let r ← withTimeoutMs 5000 do
            let (suc, gt, tryThis, ts, em, dt) ← runTacticString goal "simp?" ti.mctxBefore
            infoRef.set (some (em, dt))
            if suc then
              if tryThis != "" && tryThis.length < origLen then
                return some (tryThis, gt, ts)
            return none
          let outerDt := (← IO.monoMsNow) - t0
          if let some (some result) := r then return some result
          match ← infoRef.get with
          | some (em, dt) => failedRef.modify (·.push ("simp?", em, dt))
          | none          => failedRef.modify (·.push ("simp?", "timeout (5000ms)", outerDt))

        return none
  catch e => do
    let msg ← try e.toMessageData.toString catch _ => pure "<unknown>"
    if msg.containsSubstr "out of memory" || msg.containsSubstr "stack overflow" ||
       msg.containsSubstr "deep recursion" || msg.containsSubstr "maximum recursion" then
      IO.println s!"[WARN] checkAutomations exception: {msg.take 120}"
    return none

/-- Complete-menu mode (`--complete-menu`): one record per automation-menu entry tried on a goal. -/
structure MenuOutcome where
  menuIdx  : Nat
  menuName : String          -- menu entry, e.g. "norm_num", "simp?"
  tac      : String          -- candidate text (for simp?: the squeezed `simp only [...]`)
  valid    : Bool            -- closed the goal (no errors, no sorry, no mvar leakage)
  timedOut : Bool            -- hit the 5 s CancelToken budget (slow tactics only)
  skipped  : Bool            -- not run: menu text not strictly shorter than the original span
  goalType : String
  termSize : Nat
  err      : String
  wallMs   : Nat
  deriving Inhabited

/-- The automation menu in the SAME order as `checkAutomations`.
    Second component: run under a 5 s `withTimeoutMs` budget (as in `checkAutomations`). -/
def automationMenu : Array (String × Bool) :=
  #[("rfl", false), ("ring", false), ("abel", false), ("norm_num", false),
    ("norm_cast", false), ("positivity", false), ("decide", true),
    ("linarith", false), ("omega", false), ("field_simp", true),
    ("contradiction", false), ("ext", false), ("gcongr", false),
    ("tauto", true), ("simp?", true)]

/-- Complete-menu variant of `checkAutomations`: tries EVERY menu entry
    (no early exit) with the same per-tactic timeouts, and returns every
    outcome.  Length guard: a menu entry is run only if its text is strictly
    shorter than the original span (`checkAutomations` uses hand-set
    thresholds that coincide with this rule for every entry except
    `positivity`, which requires span > 11 instead of > 10).  For `simp?` the
    entry runs when span > 4, as in `checkAutomations`; a valid squeeze whose
    text is not shorter is kept and labelled `rejected_length` by the caller.
    Selection is done by the caller. -/
def checkAutomationsAll (goal : MVarId) (ti : TacticInfo) (origLen : Nat)
    (timeoutAll : Bool := false) : MetaM (Array MenuOutcome) := do
  let outRef ← IO.mkRef (#[] : Array MenuOutcome)
  try
    withMCtx ti.mctxBefore do
      TermElabM.run' do
        let goalType ← goal.getType
        unless ← Meta.isProp goalType do
          return
        let mut idx : Nat := 0
        for (name, slow0) in automationMenu do
          -- --menu-timeout-all: put EVERY entry (not only the 4 slow ones) under the
          -- 5 s CancelToken budget; guards against a "fast" tactic hanging on a goal
          -- that first-success mode would never have reached.
          let slow := slow0 || timeoutAll
          let i := idx
          idx := idx + 1
          let runnable := if name == "simp?" then origLen > 4 else name.length < origLen
          if !runnable then
            outRef.modify (·.push (MenuOutcome.mk (i) (name) (name) (false) (false) (true) ("") (0) ("skipped: not shorter than original") (0)))
            continue
          if slow then
            let infoRef ← IO.mkRef (none : Option (Bool × String × String × Nat × String × Nat))
            let t0 ← IO.monoMsNow
            try
              let _ ← withTimeoutMs 5000 do
                let r ← runTacticString goal name ti.mctxBefore
                infoRef.set (some r)
            catch e =>
              let msg ← try e.toMessageData.toString catch _ => pure "<exception>"
              infoRef.set (some (false, "", "", 0, (msg.take 200).map (fun c => if c == '\n' then ' ' else c), 0))
            let outerDt := (← IO.monoMsNow) - t0
            match ← infoRef.get with
            | some (suc, gt, tryThis, ts, em, dt) =>
              let tacText := if name == "simp?" then (if suc && tryThis != "" then tryThis else "simp?") else name
              -- simp? that "succeeds" without a squeeze suggestion is treated as invalid (never emitted in first-success mode)
              let suc' := suc && (name != "simp?" || tryThis != "")
              let em' := if suc && !suc' then "simp? produced no squeeze suggestion" else em
              outRef.modify (·.push (MenuOutcome.mk (i) (name) (tacText) (suc') (false) (false) (gt) (ts) (em') (dt)))
            | none =>
              outRef.modify (·.push (MenuOutcome.mk (i) (name) (name) (false) (true) (false) ("") (0) ("timeout (5000ms)") (outerDt)))
          else
            try
              let (suc, gt, _, ts, em, dt) ← runTacticString goal name ti.mctxBefore
              outRef.modify (·.push (MenuOutcome.mk (i) (name) (name) (suc) (false) (false) (gt) (ts) (em) (dt)))
            catch e =>
              let msg ← try e.toMessageData.toString catch _ => pure "<exception>"
              outRef.modify (·.push (MenuOutcome.mk (i) (name) (name) (false) (false) (false) ("") (0) ((msg.take 200).map (fun c => if c == '\n' then ' ' else c)) (0)))
        -- terminate the loop so the outer `catch` below binds to the outer `try`
        pure ()
  catch e => do
    let msg ← try e.toMessageData.toString catch _ => pure "<unknown>"
    IO.println s!"[WARN] checkAutomationsAll exception: {msg.take 120}"
  outRef.get

def stripMVarArgs (e : Expr) : Expr :=
  e.replace (fun sub => if sub.getAppFn.isMVar then some sub.getAppFn else none)

-- ═══════════════════════════════════════════════════════════════════════════
-- Level 3: exact? : library search with bounded heartbeats
-- ═══════════════════════════════════════════════════════════════════════════

/-- Quality gate for `exact?` suggestions.
    Only accept when:
    • The entire suggested tactic is ≤ 60 characters (keeps proofs readable).
    • The suggestion contains no primed identifiers (`'`) : primed names indicate
      unstable/deprecated Mathlib variants that may break across versions.
    • The suggestion is shorter than the original tactic text (net savings). -/
def isAcceptableExactResult (suggestion : String) (origLen : Nat) : Bool :=
  suggestion.length ≤ 60 &&
  !suggestion.any (· == '\'') &&
  suggestion.length < origLen

/-- Run `exact?` against a goal with a tight heartbeat budget.
    Uses `set_option maxHeartbeats 200000 in exact?` to prevent unbounded search
    (the global setting is maxHeartbeats=0 i.e. unlimited; exact? needs a hard cap).
    Returns `some (suggestion, goalType, termSize)` on success, `none` otherwise.

    The `runTacticString` infrastructure already captures `Try this: …` output
    from `exact?` : exactly the same mechanism used by `simp`. -/
def checkExactQuestion (goal : MVarId) (ti : TacticInfo) (origLen : Nat)
    : MetaM (Option (String × String × Nat)) := do
  try
    withMCtx ti.mctxBefore do
      TermElabM.run' do
        -- Safety gate: only search for library lemmas when the goal is a Prop.
        -- `exact?` finds any term of the goal type. For data types (T : Type u),
        -- it may suggest a library constant that is type-correct but semantically
        -- wrong (e.g., `exact Ordnode.nil` for ⊢ Ordnode α when a rebalancing
        -- function was expected). Prop goals are safe: proof irrelevance guarantees
        -- that any closed proof of the same Prop is semantically equivalent.
        let goalType ← goal.getType
        unless ← Meta.isProp goalType do return none
        -- Only attempt on sufficiently long original tactics (multi-step proofs)
        -- Short tactics (≤20 chars) are unlikely to benefit from library search
        -- and the search cost is not worth the potential marginal gain.
        if origLen ≤ 20 then return none
        -- Run exact? with bounded heartbeats via tactic-level set_option
        let (suc, gt, tryThis, ts, _em, _dt) ← runTacticString goal
          "set_option maxHeartbeats 200000 in exact?" ti.mctxBefore
        if !suc then return none
        -- exact? emits "Try this: exact Foo.bar" : tryThis has the content after "Try this: "
        if tryThis.isEmpty then return none
        -- Quality gate
        if !isAcceptableExactResult tryThis origLen then return none
        return some (tryThis, gt, ts)
  catch e => do
    let msg ← try e.toMessageData.toString catch _ => pure "<unknown>"
    if msg.containsSubstr "out of memory" || msg.containsSubstr "stack overflow" ||
       msg.containsSubstr "deep recursion" || msg.containsSubstr "maximum recursion" then
      IO.println s!"[WARN] checkExactQuestion exception: {msg.take 120}"
    return none

def collectFVarUsages (trees : PersistentArray InfoTree) : CoreM (Std.HashSet FVarId) := do
  let mut usages : Std.HashSet FVarId := {}
  for tree in trees do
    let subUsages ← tree.foldInfoM (init := ({} : Std.HashSet FVarId)) fun _cfg info acc => do
      match info with
      | .ofTermInfo ti =>
        let mut s := acc
        if !ti.isBinder then
          let st := Lean.collectFVars {} ti.expr
          for fv in st.fvarSet do
            s := s.insert fv
        return s
      | .ofTacticInfo ti =>
        let mut s := acc
        for (_, e) in ti.mctxAfter.eAssignment.toArray do
          let st := Lean.collectFVars {} (stripMVarArgs e)
          for fv in st.fvarSet do
            s := s.insert fv
        return s
      | _ => return acc
    for u in subUsages do usages := usages.insert u
  return usages

/-- Independent syntactic witness that the user-name `name` is referenced at any
    byte position strictly greater than `afterPos` somewhere inside `stx`.

    Used as a check on top of `collectFVarUsages` for the
    `dead_have` detector: lazy-elaboration paths (e.g. tactic-generated terms
    constructed on demand inside `decide`/`omega`/macro expansions) can leave
    the FVar absent from `mctxAfter.eAssignment`, even when the source text
    still contains the identifier. A surface-syntax check using Lean's own
    parser-emitted `Syntax.ident` nodes handles that
    (comment/string false positives that a regex would have).

    Conservative by design: name-only match (no scope tracking). If a later
    `have name := ...` shadows our `name`, we safely refuse to remove the
    earlier one; preferring a missed optimization to a broken proof. -/
partial def syntaxMentionsNameAfter (stx : Syntax) (afterPos : Nat) (name : Name) : Bool :=
  match stx with
  | .ident _ _ id _ =>
    if id == name then
      match stx.getPos? with
      | some pos => pos.byteIdx > afterPos
      | none     => false
    else false
  | .node _ _ args => args.any (fun s => syntaxMentionsNameAfter s afterPos name)
  | _ => false

/-- Extract the topmost `Syntax` of an `InfoTree` (the command/decl syntax that
    spans the largest source range in this tree). Returns the first `Info.stx`
    encountered when descending through `.context` wrappers. -/
partial def InfoTree.topStx? : InfoTree → Option Syntax
  | .node info _ => some info.stx
  | .context _ t => InfoTree.topStx? t
  | _            => none

-- ═══════════════════════════════════════════════════════════════════════════
-- Syntax-kind classification
-- ═══════════════════════════════════════════════════════════════════════════

/-- Returns true for syntax kinds that are structural wrappers, combinators,
    or internal elaboration artifacts rather than concrete tactic
    invocations.  We never emit candidates for these because:
    1. Structural wrappers produce broken syntax when replaced.
    2. Combinator wrappers (try/first/all_goals) break proof structure.
    3. Mathlib-internal kinds are elaboration artifacts whose byte ranges
       may not correspond to the user-written tactic text. -/
def isStructuralKind (kind : String) : Bool :=
  -- Structural wrappers
  kind == "null" ||
  kind == "Lean.Parser.Tactic.tacticSeq" ||
  kind == "Lean.Parser.Tactic.tacticSeq1Indented" ||
  kind == "Lean.Parser.Tactic.withAnnotateState" ||
  kind == "Lean.Parser.Tactic.paren" ||
  kind == "Lean.Parser.Tactic.seq1" ||
  kind == "group" ||
  -- Combinator wrappers : replacing their body breaks the combinator
  kind == "Lean.Parser.Tactic.tacticTry_" ||
  kind == "Lean.Parser.Tactic.first" ||
  kind == "Lean.Parser.Tactic.allGoals" ||
  kind == "Lean.Parser.Tactic.anyGoals" ||
  kind == "Lean.Parser.Tactic.focus" ||
  kind == "Lean.Parser.Tactic.tacticRepeat_" ||
  -- Already-optimal tactic kinds (source is already rfl/eq_refl)
  kind == "Lean.Parser.Tactic.tacticRfl" ||
  kind == "Lean.Parser.Tactic.eqRefl" ||
  -- Conv-mode wrappers : tactics inside `conv => ...` operate in a
  -- different tactic mode (rewriting left-to-right on subexpressions).
  -- Normal-mode replacements (simp, ring, omega, …) are syntactically
  -- valid inside conv blocks but semantically broken: they don't work
  -- in conv mode.  Verification catches failures, but rejecting upfront
  -- avoids wasting the verification budget on doomed candidates.
  kind == "Lean.Parser.Tactic.Conv.conv" ||
  kind.startsWith "Lean.Parser.Tactic.Conv." ||
  -- Internal wrappers that share byte ranges with user syntax
  kind == "Lean.Parser.Tactic.withReducible" ||
  kind == "Lean.Parser.Tactic.withReducibleAndInstances" ||
  kind == "Lean.cdot" ||
  -- Mathlib-internal elaboration artifacts : their byte ranges refer to
  -- the enclosing user syntax, not their own tactic text
  kind.startsWith "Mathlib.Tactic."

/-- Taxonomy axis.

    Orthogonal to the tier ladder used by `isQualityUpgrade`, every
    tactic is either:

    * `.structural` - announces a specific proof technique: `rfl`, `ring`, `norm_num`,
      `linarith`, `omega`, `decide`, `field_simp`, `positivity`, …  These
      proofs document how the goal was closed and remain stable as
      Mathlib drifts.

    * `.opaque` - closes the goal by undirected search: `simp`, `simp_all`,
      `aesop`, `hint`, `tauto`, `fin_cases`.  These record only that
      some search succeeded; their behaviour is sensitive to the ambient
      simp set / instance graph, which makes downstream maintenance and
      training-pair reuse strictly harder.

    * `.neutral` - everything else (`trivial`, `assumption`, plain identifiers).

    The axis lets us reject a final class of replacements the tier
    ladder does not catch (e.g. `rfl ↝ simp`, `decide ↝ aesop`):
    `structural ↝ opaque` is a quality regression even when shorter,
    and is rejected by `isQualityUpgrade` as the final guard. -/
inductive TacAxis where
  | structural
  | opaque
  | neutral
  deriving DecidableEq, Inhabited

/-- Map a head identifier (the last component of a tactic's
  `SyntaxNodeKind`, or the leading source token as a fallback) to a
    `TacAxis`.  Centralised so `tacticAxisOfSyntax` and the
    string fallback `tacticAxisOfString` stay in lock-step. -/
def axisOfHead : String → TacAxis
  | "rfl" | "Rfl" | "tacticRfl"
  | "ring" | "ring1" | "ring_nf" | "ringNF"
  | "abel" | "abel_nf" | "abelNF"
  | "norm_num" | "normNum" | "norm_num1" | "normNum1"
  | "norm_cast" | "normCast"
  | "push_cast" | "pushCast"
  | "push_neg" | "pushNeg"
  | "positivity"
  | "decide" | "tacticDecide"
  | "linarith" | "Linarith" | "linarith!"
  | "nlinarith" | "Nlinarith" | "nlinarith!"
  | "omega" | "tacticOmega" | "omega_nat"
  | "polyrith" | "Polyrith"
  | "field_simp" | "fieldSimp"
  | "gcongr" | "Gcongr" | "GCongr"
  | "linear_combination" | "linearCombination" =>
      .structural
  | "simp" | "tacticSimp" | "simp_all" | "simpAll"
  | "simp_arith" | "simpArith"
  | "simp_rw" | "simpRw"
  | "aesop" | "Aesop" | "Aesop_"
  | "hint" | "tauto" | "Tauto"
  | "fin_cases" | "finCases" =>
      .opaque
  | _ => .neutral

/-- Walk a parsed tactic `Syntax` to the head tactic node, peeling off
    structural wrappers (`tacticSeq`, `tacticSeq1Indented`, `byTactic`,
    `paren`, `first | … | …`, leading `(config := …)`).  Returns the
    inner tactic whose `SyntaxNodeKind` we want to classify. -/
partial def headTacticOfSyntax : Syntax → Syntax
  | stx =>
    let k := stx.getKind
    let kStr := k.toString
    -- Peel structural wrappers by kind.
    if kStr.endsWith "tacticSeq" || kStr.endsWith "tacticSeq1Indented" ||
       kStr.endsWith "tacticSeqBracketed" || kStr.endsWith "byTactic" then
      -- Descend into the first child that has a kind (skip atoms / null).
      match stx.getArgs.find? (fun c => c.getKind != Name.anonymous) with
      | some inner => headTacticOfSyntax inner
      | none       => stx
    else if kStr.endsWith "first" then
      -- `first | t1 | t2`: classify by the FIRST alternative; if it is
      -- structural we keep the structural label (the disjunction is at
      -- least as informative as its strongest branch).
      match stx.getArgs.find? (fun c => c.getKind != Name.anonymous && !c.isAtom) with
      | some inner => headTacticOfSyntax inner
      | none       => stx
    else
      stx

/-- Extract a head identifier from a parsed tactic syntax node:
    use the last component of its `SyntaxNodeKind`, falling back to
    the first leading atom token if the kind is anonymous or generic. -/
partial def headIdOfSyntax (stx : Syntax) : String :=
  let k := stx.getKind
  if k != Name.anonymous then
    k.componentsRev.head?.map Name.toString |>.getD ""
  else
    -- Anonymous (raw atom or null): walk to the first atom value.
    match stx with
    | .atom _ val => val
    | .ident _ _ val _ => val.toString
    | .node _ _ args =>
        args.foldl (fun acc c =>
          if acc.isEmpty then headIdOfSyntax c else acc) ""
    | .missing => ""

/-- Classify a tactic snippet by parsing it as Lean syntax and inspecting
    the resulting head tactic's `SyntaxNodeKind`.  Robust against
    `(config := …) simp`, `first | linarith | nlinarith`, leading
    whitespace / comments / `by` prefixes, and arbitrary-arity arg lists.

    Returns `.neutral` if the string fails to parse as a tactic - this
    keeps the axis check a no-op for un-parseable junk rather than
    risking a false `structural↝opaque` rejection from the string
    prefix-scanner. -/
def tacticAxisOfSyntax (env : Environment) (s : String) : TacAxis :=
  let s := s.trim
  -- Strip a leading `by ` or `· ` so the parser sees a bare tactic.
  let s := if s.startsWith "by " then (s.drop 3).trim
           else if s.startsWith "by\n" then (s.drop 3).trim
           else if s.startsWith "· " then (s.drop 2).trim
           else s
  match Parser.runParserCategory env `tactic s with
  | Except.error _   => .neutral
  | Except.ok stx =>
    let head := headTacticOfSyntax stx
    axisOfHead (headIdOfSyntax head)

/-- Pure-string classifier, used as a fallback when no
    `Environment` is available.  Takes the leading
    alphanumeric/underscore identifier and dispatches via `axisOfHead`. -/
def tacticAxisOfString (s : String) : TacAxis :=
  let s := s.trim
  let s := if s.startsWith "by " then (s.drop 3).trim
           else if s.startsWith "· " then (s.drop 2).trim
           else s
  axisOfHead (s.takeWhile (fun c => c.isAlphanum || c == '_'))

/-- String-only classifier.
    Use `tacticAxisOfSyntax` when an `Environment` is in scope. -/
@[inline] def tacticAxis (s : String) : TacAxis := tacticAxisOfString s

/-- Stable string label for a `TacAxis`, used in JSON emission. -/
def TacAxis.toAxisString : TacAxis → String
  | .structural => "structural"
  | .opaque     => "opaque"
  | .neutral    => "neutral"

/-- The schema version of every `[TRAINING_PAIR]` / `[REJECTED_PAIR]`
    JSON row this binary emits.  Bumped whenever a required field is
    added, removed, or renamed.  Consumers should warn on mismatch.
    Optional/derived fields do not require a bump. -/
def trainingPairSchemaVersion : Nat := 2

/-- Git SHA of the binary at build/launch time.  Read once from the
    `LEANPOLISH_GIT_SHA` environment variable, if set;
    defaults to `"unknown"`.  Embedded in every emitted training row
    for full per-run provenance. -/
def gitShaIO : IO String := do
  match (← IO.getEnv "LEANPOLISH_GIT_SHA") with
  | some s => pure s.trim
  | none   => pure "unknown"

/-- Single source of truth for emitting a tagged JSON line.  Builds the
    object via `Lean.Json.mkObj`, which performs RFC-8259-compliant
    string escaping (covers all control chars, not just `\n` / `\r` /
    `\t` / `\"` / `\\`). -/
def emitJsonLine (tag : String) (fields : List (String × Lean.Json)) : IO Unit :=
  IO.println s!"{tag} {(Lean.Json.mkObj fields).compress}"

/-- Check if replacing origText with newTac is a quality upgrade.
    Rejects replacements that would degrade proof readability.

    The tactic hierarchy (most to least specific):
      rfl > ring = abel > norm_num > positivity > norm_cast > decide >
      linarith > omega > field_simp > contradiction > ext > gcongr > tauto > simp

    A tactic may only be replaced by one of equal or higher specificity.
    Witness tactics (exact, rw, apply …) are never replaced except by rfl.

    `env?` is the current `Environment`; when supplied, the taxonomy-axis
    cross-check uses `tacticAxisOfSyntax` (real Lean parsing +
    `SyntaxNodeKind` dispatch).  Falls back to the string
    classifier otherwise - for callers that don't have an env in scope. -/
def isQualityUpgrade (origText : String) (newTac : String)
    (env? : Option Environment := none) : Bool := Id.run do
  let strip (s : String) : String :=
    let s := s.trim
    let s := if s.startsWith "· " then (s.drop 2).trim else s
    let s := if s.startsWith "by " then (s.drop 3).trim else s
    s
  let orig := strip origText
  let repl := strip newTac

  -- ── Witness / structural tactics ─────────────────────────────────────
  -- Single-step tactics that name specific terms, lemmas, hypotheses or
  -- proof structure. Replacing them with automation loses information.
  -- Only multi-step blocks (containing ';' or '<;>') are simplification targets.
  let isMultiStep := orig.containsSubstr ";" || orig.containsSubstr "<;>"
  if !isMultiStep then
    if orig.startsWith "exact " || orig.startsWith "rw " || orig.startsWith "rw[" ||
       orig.startsWith "rewrite " || orig.startsWith "rewrite[" ||
       orig.startsWith "apply " || orig.startsWith "refine " || orig.startsWith "refine'" ||
       orig.startsWith "use " || orig.startsWith "convert " ||
       orig.startsWith "cases " || orig.startsWith "rcases " || orig.startsWith "obtain " ||
       orig.startsWith "calc " ||
       orig.startsWith "induction " || orig.startsWith "match " ||
       orig == "constructor" || orig == "left" || orig == "right" ||
       orig == "exfalso" || orig == "symmetry" ||
       orig.startsWith "nomatch " || orig == "nomatch" ||
       orig.startsWith "absurd " || orig.startsWith "nofun" ||
       -- conv blocks express precise surgical rewriting on subexpressions.
       -- Replacing them with a non-conv tactic is semantically wrong
       -- (incompatible tactic modes) and loses targeting information.
       orig.startsWith "conv " || orig.startsWith "conv\n" then
      return false

  -- ── rfl is an upgrade for non-witness tactics ────────────────────────
  if repl == "rfl" then return true

  -- ── Already-lightweight tactics ──────────────────────────────────────
  if orig == "trivial" || orig == "assumption" || orig == "contradiction" then return false

  -- ── Decision-procedure preservation ──────────────────────────────────
  -- Each decision procedure is definitive for its domain.
  -- A tactic can only be replaced by one of equal or higher specificity.

  -- Tier 2: ring / abel : algebraic decision procedures (nothing beats except rfl)
  if orig == "ring" || orig == "abel" then return false

  -- Classify simp-like replacements: bare `simp`, `simp only [...]`, `simp [...]`
  -- All are Tier 6 and should never replace domain-specific tactics.
  let isSimpLike := repl == "simp" || repl.startsWith "simp only" || repl.startsWith "simp ["

  -- Tier 3: norm_num / positivity / norm_cast : domain-specific normalizers
  -- Tier 3.7: decide : complete decision procedure (definitive for decidable props)
  -- None of these should be downgraded to anything below them.
  let isTier3Below := repl == "linarith" || repl == "omega" || repl == "field_simp" ||
                      repl == "tauto" || isSimpLike ||
                      repl == "contradiction" || repl == "ext" || repl == "gcongr"
  if orig.startsWith "norm_num" && isTier3Below then return false
  if orig.startsWith "positivity" && isTier3Below then return false
  if orig.startsWith "norm_cast" && isTier3Below then return false
  if orig == "decide" && isTier3Below then return false

  -- Tier 4: linarith / omega : arithmetic solvers (peer tactics, each is definitive for its domain)
  -- linarith: linear arithmetic over ordered fields; omega: natural/integer arithmetic
  -- Neither downgrades to the other : they solve different domains.
  let isTier4Below := repl == "field_simp" || repl == "tauto" || isSimpLike ||
                      repl == "contradiction" || repl == "ext" ||
                      repl == "gcongr"
  if orig.startsWith "linarith" && isTier4Below then return false
  if orig.startsWith "nlinarith" && isTier4Below then return false
  if orig.startsWith "omega" && isTier4Below then return false

  -- Tier 4.5: field_simp : clears denominators (more specific than general simp)
  -- Tier 5: contradiction / ext / gcongr : structural solvers
  -- Tier 5.5: tauto : propositional tautology checker
  let isTier5Below := isSimpLike
  if orig.startsWith "field_simp" && isTier5Below then return false
  if orig == "tauto" && isTier5Below then return false
  if orig.startsWith "gcongr" && isTier5Below then return false
  -- Domain-specific preprocessing tactics : more specific than simp
  if orig.startsWith "push_cast" && isSimpLike then return false
  if orig.startsWith "push_neg" && isSimpLike then return false
  if orig.startsWith "simp_rw" && isSimpLike then return false
  -- `simp only [...]` is strictly more robust than bare `simp` : never downgrade
  if orig.startsWith "simp only" && repl == "simp" then return false

  -- ── Taxonomy-axis cross-check ────────────────────────────────────────
  -- Final guard: never demote a structural (intent-announcing) tactic to
  -- an opaque (search-based) one, even when both are below the tier
  -- ladder's resolution.  Catches e.g. `rfl ↝ simp`, `decide ↝ aesop`,
  -- `linarith ↝ aesop` that the tier rules above don't already block.
  -- Use syntax-tree classifier when an `Environment` is in scope
  -- (robust against `(config := …) simp`, `first | … | …`, etc.);
  -- otherwise the string-prefix scanner.
  let axisOf : String → TacAxis := fun s =>
    match env? with
    | some env => tacticAxisOfSyntax env s
    | none     => tacticAxisOfString s
  match axisOf orig, axisOf repl with
  | .structural, .opaque => return false
  | _, _ => return true

-- ═══════════════════════════════════════════════════════════════════════════
-- Candidate: a structured replacement record
-- ═══════════════════════════════════════════════════════════════════════════

structure Candidate where
  startPos    : Nat
  endPos      : Nat
  newTac      : String
  goalType    : String
  goalPretty  : String := ""   -- pretty-printed target type via Meta.ppExpr
  goalState   : String := ""   -- full goal state (hypotheses ⊢ target) via Meta.ppGoal
  kind        : String
  termSize    : Nat
  isPropSafe  : Bool := false  -- True if proof irrelevance guarantees this edit is safe
  -- (tacName, errMsg, wallMs) tried before the winner that failed on this goal
  failedTactics : Array (String × String × Nat) := #[]
  -- --complete-menu only: every other menu candidate tried on this goal,
  -- as (candidateText, outcomeLabel, errMsg, wallMs).  outcomeLabel ∈
  -- {valid_not_chosen, rejected_kernel, timeout, rejected_quality, rejected_length}.
  -- Empty in default (first-success) mode.
  menuSiblings : Array (String × String × String × Nat) := #[]
  deriving Inhabited

-- ═══════════════════════════════════════════════════════════════════════════
-- Ablation configuration : controls which phases run.
-- All phases enabled by default.  CLI flags --skip-phase1, --skip-l2,
-- --skip-dead-code, --skip-cleanup, --no-quality-gate selectively disable
-- phases for ablation experiments.
-- ═══════════════════════════════════════════════════════════════════════════

structure AblationConfig where
  skipPhase1     : Bool := false  -- skip tactic replacement (Phase 1)
  skipL2         : Bool := false  -- skip L2 anti-unification (Phase 1.5)
  skipDeadCode   : Bool := false  -- skip dead code removal (Phase 2)
  skipCleanup    : Bool := false  -- skip warning-guided cleanup (Phase 3)
  noQualityGate  : Bool := false  -- accept shortest valid tactic regardless of specificity tier
  noG3           : Bool := false  -- ablation: disable G3 generalization gate in L2
  menuTimeoutAll : Bool := false  -- 5 s budget on every menu entry (complete-menu only)
  completeMenu   : Bool := false  -- try the WHOLE automation menu, pick shortest quality-passing success
  memTrace       : Bool := false  -- emit [MEMTRACE] lines at phase boundaries (Linux /proc/self/status)
  blockLocal     : Bool := false  -- advisory per-candidate one-command pre-check.
                                   -- Never drops candidates: every survivor is forwarded to the
                                   -- Phase 2b batch verify, which is the only authority.
                                   -- Logs `fast=N, deferred=M` per file. Default off.
  workerMode     : Bool := false  -- Read file paths from stdin (one per line) instead of argv;
                                   -- shared importEnv loaded once from a bootstrap file passed on argv,
                                   -- then loop until EOF.  Enables a Python orchestrator to keep N long-lived
                                   -- worker processes, paying the Mathlib-import cost once per worker.
  deriving Inhabited

-- ═══════════════════════════════════════════════════════════════════════════
-- Memory tracing helpers
--   readMemKB reads /proc/self/status (Linux only) and returns
--   (VmRSS, VmHWM, VmPeak) in kilobytes.  VmHWM is the high-water-mark
--   resident set size since process start; VmPeak is the peak virtual size.
--   Used by --mem-trace to report per-phase memory without an external
--   profiler.
-- ═══════════════════════════════════════════════════════════════════════════

def readMemKB : IO (Option (Nat × Nat × Nat)) := do
  try
    let content ← IO.FS.readFile "/proc/self/status"
    let lines := content.splitOn "\n"
    let getField (name : String) : Nat := Id.run do
      let pfx := name ++ ":"
      match lines.find? (fun l => l.startsWith pfx) with
      | none => 0
      | some line =>
        -- Format: "VmRSS:\t   12345 kB"
        let rest := (line.drop pfx.length).trim
        let numStr := (rest.splitOn " ").head!
        numStr.toNat?.getD 0
    return some (getField "VmRSS", getField "VmHWM", getField "VmPeak")
  catch _ => return none

def traceMem (label : String) (cfg : AblationConfig) : IO Unit := do
  if cfg.memTrace then
    let now ← IO.monoMsNow
    match (← readMemKB) with
    | some (rss, hwm, peak) =>
      IO.println s!"[MEMTRACE] t={now}ms label={label} rss_kb={rss} hwm_kb={hwm} vpeak_kb={peak}"
    | none =>
      IO.println s!"[MEMTRACE] t={now}ms label={label} (proc unavailable)"

-- ═══════════════════════════════════════════════════════════════════════════
-- Level 1: Have-block deduplication key
-- ═══════════════════════════════════════════════════════════════════════════

/-- Key for deduplicating have-blocks.  Two have-blocks are duplicates iff
    they introduce a hypothesis of the same elaborated type and have the same
    proof text.  Keying on (type, proof) rather than type alone avoids false
    matches when two hypotheses share a type but are proved differently (e.g.,
    one by `linarith`, the other by `ring`). -/
structure DedupKey where
  typeStr  : String   -- pretty-printed elaborated type
  proofTxt : String   -- verbatim source text of the proof term
  deriving BEq, Hashable, Repr

/-- Value stored for the first occurrence of a dedup key. -/
structure DedupVal where
  hypName : String    -- name of the introduced hypothesis
  bytePos : Nat       -- byte offset of the `have` keyword
  deriving Repr

-- ═══════════════════════════════════════════════════════════════════════════
-- Level 2: Expr-level anti-unification (near-duplicate detection)
-- ═══════════════════════════════════════════════════════════════════════════

/-- A collected `have`-block with its elaborated proof term and source info.
    Extracted during InfoTree traversal for anti-unification analysis. -/
structure HaveBlockInfo where
  hypName     : String         -- name of the introduced hypothesis (e.g., "h3")
  hypType     : Expr           -- elaborated type of the hypothesis
  hypTypeStr  : String         -- canonical type (FVars → _lvN), for fingerprint grouping
  hypTypeRaw  : String         -- raw ppExpr type (actual variable names), for Prop-safe matching
  proofExpr   : Expr           -- instantiated proof term from mctxAfter
  startPos    : Nat            -- byte offset of `have` keyword
  endPos      : Nat            -- byte offset of the end of the have block
  proofStart  : Nat            -- byte offset where the proof body starts (after `:= `)
  lctx        : LocalContext   -- outer local context (after have-block, includes new hyp) for scope checks
  proofLCtx   : LocalContext   -- goal local context (before proof elaboration) for ppExpr of proof sub-exprs
  mctx        : MetavarContext -- metavar context after the tactic
  isPropType  : Bool           -- true if hypType is a Prop (pre-computed during collection)
  deriving Inhabited

/-- Result of anti-unifying two expressions. -/
structure AntiUnifResult where
  skeleton : Expr              -- common structure with .bvar holes for parameters
  arity    : Nat               -- number of unique differing positions
  diffs    : Array (Nat × Expr × Expr)  -- (paramIdx, e1_sub, e2_sub) for each parameter
  deriving Inhabited

/-- A group of have-blocks that share the same anti-unification skeleton. -/
structure AntiUnifGroup where
  skeleton     : Expr                    -- common structure
  arity        : Nat                     -- number of parameters
  members      : Array HaveBlockInfo     -- all blocks in this group
  /-- For each member (except template), the substitution values for each parameter.
      memberDiffs[i] corresponds to members[i+1] (member 0 is the template). -/
  memberDiffs  : Array (Array (Nat × Expr × Expr))
  deriving Inhabited

/-- Anti-unify two expressions: find their most specific common generalization.
    Returns the skeleton (with `.bvar` holes at differing positions) and the
    list of differing sub-expression pairs.

    Uses a substitution table to ensure that identical differing pairs always map
    to the same parameter variable. -/
def antiUnifyExprs (e1 e2 : Expr) : AntiUnifResult := Id.run do
  -- Substitution table: maps (hash of e1, hash of e2, e1, e2) → param index
  -- We use hashes for fast lookup and BEq Expr for correctness
  let mut nextParam : Nat := 0
  let mut diffs : Array (Nat × Expr × Expr) := #[]
  -- Simple assoc list for the substitution table (sufficient for arity ≤ 10)
  let mut substTable : Array (Expr × Expr × Nat) := #[]

  let freshParam (sub1 sub2 : Expr) : StateM (Nat × Array (Nat × Expr × Expr) × Array (Expr × Expr × Nat)) Expr := do
    let (np, df, st) ← get
    -- Check if this pair was already seen
    for (s1, s2, idx) in st do
      if s1 == sub1 && s2 == sub2 then
        return .bvar idx
    -- New pair
    let idx := np
    set (np + 1, df.push (idx, sub1, sub2), st.push (sub1, sub2, idx))
    return .bvar idx

  let rec go (a b : Expr) : StateM (Nat × Array (Nat × Expr × Expr) × Array (Expr × Expr × Nat)) Expr := do
    -- Fast path: structurally identical (BEq, not isDefEq : intentional).
    -- Using BEq here is correct: anti-unification is a syntactic operation
    -- that finds the most specific common generalization. α-equivalent exprs
    -- with different internal names should produce parameters (the names
    -- genuinely differ). isDefEq would hide meaningful differences.
    -- Meta.check downstream catches any unsound abstractions.
    if a == b then return a
    match a, b with
    | .app f1 a1, .app f2 a2 =>
      return .app (← go f1 f2) (← go a1 a2)
    | .lam n1 t1 b1 bi1, .lam _ t2 b2 bi2 =>
      if bi1 == bi2 then
        -- Recurse into binder types (in enclosing scope, safe).
        -- Treat bodies atomically: diffs inside bodies contain loose BVars
        -- (referencing the lambda parameter) that can't be pretty-printed.
        if b1 == b2 then return .lam n1 (← go t1 t2) b1 bi1
        else freshParam a b
      else freshParam a b
    | .forallE n1 t1 b1 bi1, .forallE _ t2 b2 bi2 =>
      if bi1 == bi2 then
        if b1 == b2 then return .forallE n1 (← go t1 t2) b1 bi1
        else freshParam a b
      else freshParam a b
    | .letE n1 t1 v1 b1 nd1, .letE _ t2 v2 b2 nd2 =>
      if nd1 == nd2 then
        -- Recurse into types and values (enclosing scope), body is atomic.
        if b1 == b2 then return .letE n1 (← go t1 t2) (← go v1 v2) b1 nd1
        else freshParam a b
      else freshParam a b
    | .proj s1 i1 e1, .proj s2 i2 e2 =>
      if s1 == s2 && i1 == i2 then
        return .proj s1 i1 (← go e1 e2)
      else freshParam a b
    | .const n1 ls1, .const n2 ls2 =>
      -- Require an exact match on universe levels.
      if n1 == n2 && ls1 == ls2 then return a
      else freshParam a b
    | _, _ => freshParam a b

  let (skeleton, (np, df, _)) := StateT.run (go e1 e2) (nextParam, diffs, substTable)
  { skeleton := skeleton, arity := np, diffs := df }

/-- Run the N-way grouping algorithm on a bucket of have-blocks that share the
    same fingerprint. Uses the template-based approach: B_1 is the template,
    each subsequent B_i is anti-unified against B_1. Blocks with incompatible
    arity or parameter positions go into separate groups. -/
def groupByAntiUnif (blocks : Array HaveBlockInfo) : Array AntiUnifGroup := Id.run do
  if blocks.size < 2 then return #[]
  let mut groups : Array AntiUnifGroup := #[]

  -- Process each block
  for i in [:blocks.size] do
    let block := blocks[i]!
    let mut joined := false
    -- Try to join an existing group
    for gIdx in [:groups.size] do
      let g := groups[gIdx]!
      let template := g.members[0]!
      let result := antiUnifyExprs template.proofExpr block.proofExpr
      if result.arity ≤ 10 then
        if g.members.size == 1 then
          -- First pair in the group: establish the skeleton and arity
          let newMembers := g.members.push block
          let newDiffs := g.memberDiffs.push result.diffs
          groups := groups.set! gIdx {
            skeleton := result.skeleton
            arity := result.arity
            members := newMembers
            memberDiffs := newDiffs
          }
          joined := true
          break
        else
          -- Subsequent members: must match established arity + skeleton
          if result.arity == g.arity && result.skeleton == g.skeleton then
            let newMembers := g.members.push block
            let newDiffs := g.memberDiffs.push result.diffs
            groups := groups.set! gIdx { g with members := newMembers, memberDiffs := newDiffs }
            joined := true
            break
    if !joined then
      -- Start a new group with this block as template
      groups := groups.push {
        skeleton := block.proofExpr  -- placeholder until second member joins
        arity := 0
        members := #[block]
        memberDiffs := #[]
      }
  -- Filter out singleton groups
  return groups.filter (fun g => g.members.size >= 2)

/-- Byte savings of this replacement. -/
def Candidate.savings (c : Candidate) : Int :=
  (c.endPos - c.startPos : Int) - c.newTac.length

/-- Check if a character is an identifier character (alphanumeric, underscore, or Unicode letter).
    Used for word-boundary-aware replacement. -/
private def isIdentChar (c : Char) : Bool :=
  c.isAlphanum || c == '_' || c == '\'' || c == '₀' || c == '₁' || c == '₂' || c == '₃' || c == '₄' || c == '₅' || c == '₆' || c == '₇' || c == '₈' || c == '₉'

/-- Replace occurrences of `old` with `new` in `s`, but only at word boundaries.
    A match at position i is on a word boundary if:
    - i == 0 or s[i-1] is not an identifier character
    - i + old.length >= s.length or s[i + old.length] is not an identifier character
    This prevents replacing "h" inside "th" or "show". -/
def replaceWord (s old new_ : String) : String := Id.run do
  if old.isEmpty then return s
  let mut result := ""
  let mut pos : String.Pos := ⟨0⟩
  let oldByteLen := old.utf8ByteSize
  let sLen := s.utf8ByteSize
  while pos.byteIdx + oldByteLen ≤ sLen do
    let endSlice : String.Pos := ⟨pos.byteIdx + oldByteLen⟩
    if s.extract pos endSlice == old then
      -- Check word boundaries (UTF-8 safe via String.prev/get)
      let leftOk := pos.byteIdx == 0 || !isIdentChar (s.get (s.prev pos))
      let rightOk := endSlice.byteIdx ≥ sLen || !isIdentChar (s.get endSlice)
      if leftOk && rightOk then
        result := result ++ new_
        pos := endSlice
        continue
    result := result.push (s.get pos)
    pos := s.next pos
  -- Append remainder
  result := result ++ s.extract pos ⟨sLen⟩
  return result

-- ═══════════════════════════════════════════════════════════════════════════
-- Text-level diff for source-based lemma extraction
-- ═══════════════════════════════════════════════════════════════════════════

/-- Tokenize tactic text into identifier tokens and separator strings.
    Returns an array of (isIdent : Bool, text : String). -/
private def tokenize (s : String) : Array (Bool × String) := Id.run do
  let mut result : Array (Bool × String) := #[]
  let mut pos : String.Pos := ⟨0⟩
  let sLen := s.utf8ByteSize
  while pos.byteIdx < sLen do
    let c := s.get pos
    if isIdentChar c then
      let mut endPos := s.next pos
      while endPos.byteIdx < sLen && isIdentChar (s.get endPos) do endPos := s.next endPos
      result := result.push (true, s.extract pos endPos)
      pos := endPos
    else
      let mut endPos := s.next pos
      while endPos.byteIdx < sLen && !isIdentChar (s.get endPos) do endPos := s.next endPos
      result := result.push (false, s.extract pos endPos)
      pos := endPos
  return result

/-- Find word-level diffs between two tactic texts.
    Returns `some diffs` where each diff is (tokenIndex, templateWord, memberWord)
    if the texts have the same token structure (same separators, same non-differing tokens).
    Returns `none` if the structure doesn't match. -/
def textDiff (templateText memberText : String) : Option (Array (Nat × String × String)) := Id.run do
  let tToks := tokenize templateText
  let mToks := tokenize memberText
  if tToks.size != mToks.size then return none
  let mut diffs : Array (Nat × String × String) := #[]
  for i in [:tToks.size] do
    let (tIsId, tText) := tToks[i]!
    let (mIsId, mText) := mToks[i]!
    if tIsId != mIsId then return none  -- structural mismatch
    if tText != mText then
      if !tIsId then return none  -- separator differs → structural mismatch
      diffs := diffs.push (i, tText, mText)
  return some diffs

-- ═══════════════════════════════════════════════════════════════════════════
-- Metrics: Lean token counter and line counter
--
-- Two compression metrics beyond raw byte count, for comparability with
-- ProofOptimizer (Gu et al., arXiv:2510.15700) and standard practice:
--   1. Lean token count - ProofOptimizer's primary metric (Appendix L)
--   2. Non-blank non-comment line count - standard "lines of code" metric
-- ═══════════════════════════════════════════════════════════════════════════

/-- Character classification for Lean identifier tokens.
    Includes alphanumeric characters, underscore, apostrophe, and
    Unicode subscript digits.
    Matches Lean 4's identifier syntax: `isAlphaNum || _ || ' || subscript`. -/
private def isLeanTokenIdentChar (c : Char) : Bool :=
  c.isAlpha || c.isDigit || c == '_' || c == '\'' || (c.val ≥ 0x2080 && c.val ≤ 0x2089)

/-- Count Lean tokens in a string, matching ProofOptimizer's tokenizer
    (Gu et al., arXiv:2510.15700, Appendix L).

    Tokenization rules (applied in priority order):
    1. Whitespace (space, tab, newline, CR) → skipped, not counted.
    2. Single-line comments (`--` to end of line) → skipped entirely.
    3. Block comments (`/-` to `-/`, nesting-aware) → skipped entirely.
    4. Identifiers (`[a-zA-Z0-9_'₀-₉]+`) → one token per maximal run.
    5. Multi-character operators → one token each:
       - 3-char: `<;>` (tactic combinator), `>>=` (bind)
       - 2-char: `:=`, `!=`, `->`, `<-`, `=>`, `>=`, `<=`, `++`, `>>`, `..`, `#[`
    6. Any other character → one token.

    Design rationale: ProofOptimizer's tokenizer "correlates with character
    count but does not penalize long identifier names, and it ignores comments
    and line breaks" (§5.1).  This implementation below reproduces that
    semantics.

    Example: `have h : n ≤ m := by omega -- fast` → tokens:
      `have`, `h`, `:`, `n`, `≤`, `m`, `:=`, `by`, `omega` = 9 tokens
      (the `-- fast` comment and all whitespace are skipped) -/
def countLeanTokens (s : String) : Nat := Id.run do
  let mut count : Nat := 0
  let mut pos : String.Pos := ⟨0⟩
  let len := s.utf8ByteSize
  while pos.byteIdx < len do
    let c := s.get pos
    -- 1. Skip whitespace
    if c == ' ' || c == '\t' || c == '\n' || c == '\r' then
      pos := s.next pos
      continue
    -- 2. Skip single-line comments: `--` to end of line
    --    Must check before multi-char operators (which also match `->`).
    if c == '-' then
      let p1 := s.next pos
      if p1.byteIdx < len && s.get p1 == '-' then
        -- Advance past end of line (or end of string)
        pos := s.next p1
        while pos.byteIdx < len && s.get pos != '\n' do
          pos := s.next pos
        continue
    -- 3. Skip block comments: `/-` to `-/` (nesting-aware)
    --    Lean 4 block comments nest: `/- a /- b -/ c -/` is one comment.
    if c == '/' then
      let p1 := s.next pos
      if p1.byteIdx < len && s.get p1 == '-' then
        pos := s.next p1  -- skip past `/-`
        let mut depth : Nat := 1
        while pos.byteIdx < len && depth > 0 do
          let cc := s.get pos
          let np := s.next pos
          if cc == '/' && np.byteIdx < len && s.get np == '-' then
            depth := depth + 1
            pos := s.next np
          else if cc == '-' && np.byteIdx < len && s.get np == '/' then
            depth := depth - 1
            pos := s.next np
          else
            pos := np
        continue
    -- 4. Identifier token: maximal run of [a-zA-Z0-9_'₀-₉]
    if isLeanTokenIdentChar c then
      pos := s.next pos
      while pos.byteIdx < len && isLeanTokenIdentChar (s.get pos) do
        pos := s.next pos
      count := count + 1
      continue
    -- 5. Multi-character operators (longest match first)
    let p1 := s.next pos
    if p1.byteIdx < len then
      let c1 := s.get p1
      -- 3-character operators
      let p2 := s.next p1
      if p2.byteIdx < len then
        let c2 := s.get p2
        if (c == '<' && c1 == ';' && c2 == '>') ||  -- <;> tactic combinator
           (c == '>' && c1 == '>' && c2 == '=') then -- >>= bind
          count := count + 1
          pos := s.next p2
          continue
      -- 2-character operators
      if (c == ':' && c1 == '=') ||   -- := definition
         (c == '!' && c1 == '=') ||   -- != not equal
         (c == '-' && c1 == '>') ||   -- -> function type
         (c == '<' && c1 == '-') ||   -- <- monadic bind / pattern
         (c == '=' && c1 == '>') ||   -- => match arm / lambda
         (c == '>' && c1 == '=') ||   -- >= greater-equal
         (c == '<' && c1 == '=') ||   -- <= less-equal
         (c == '+' && c1 == '+') ||   -- ++ append
         (c == '>' && c1 == '>') ||   -- >> sequence
         (c == '.' && c1 == '.') ||   -- .. range
         (c == '#' && c1 == '[') then -- #[ array literal
        count := count + 1
        pos := s.next p1
        continue
    -- 6. Single-character token (punctuation, Unicode symbol, etc.)
    count := count + 1
    pos := s.next pos
  return count

/-- Count non-blank, non-comment lines in text.

    A line is counted if and only if it contains at least one non-whitespace
    character that is outside any comment (single-line `--` or block `/-...-/`).

    Block comment tracking is nesting-aware: `/-` increments depth, `-/`
    decrements, and characters inside a block comment do not contribute
    content. Single-line comments (`--` outside block comments) cause the
    remainder of the line to be skipped.

    This handles all edge cases correctly:
    • `/- comment -/ real_code` → counted (real_code is outside comment)
    • `code /- comment` → counted (code is outside comment)
    • `still_in_block -/ code` → counted (code is outside after close)
    • `-- line comment` → not counted
    • `   ` (whitespace only) → not counted
    • lines entirely inside a block comment → not counted -/
def countNonBlankLines (s : String) : Nat := Id.run do
  let lines := s.splitOn "\n"
  let mut count : Nat := 0
  let mut blockDepth : Nat := 0
  for line in lines do
    let mut hasContent := false
    let mut pos : String.Pos := ⟨0⟩
    let lineLen := line.utf8ByteSize
    while pos.byteIdx < lineLen do
      let c := line.get pos
      let np := line.next pos
      -- Block comment open
      if c == '/' && np.byteIdx < lineLen && line.get np == '-' then
        blockDepth := blockDepth + 1
        pos := line.next np
        continue
      -- Block comment close
      if c == '-' && np.byteIdx < lineLen && line.get np == '/' then
        if blockDepth > 0 then blockDepth := blockDepth - 1
        pos := line.next np
        continue
      -- Inside block comment: skip character
      if blockDepth > 0 then
        pos := np
        continue
      -- Single-line comment: rest of line is comment
      if c == '-' && np.byteIdx < lineLen && line.get np == '-' then
        break
      -- Non-whitespace outside any comment → line has content
      if c != ' ' && c != '\t' && c != '\r' then
        hasContent := true
      pos := np
    if hasContent then count := count + 1
  return count

-- ═══════════════════════════════════════════════════════════════════════════
-- Text replacement helpers
-- ═══════════════════════════════════════════════════════════════════════════

/-- Apply an array of candidates to original text, bottom-up (highest position first). -/
def applyReplacements (fileData : String) (cands : Array Candidate) : String := Id.run do
  let sorted := cands.qsort (fun a b => a.startPos > b.startPos)
  let mut data := fileData
  for c in sorted do
    let pre := data.extract 0 ⟨c.startPos⟩
    let suf := data.extract ⟨c.endPos⟩ data.endPos
    data := pre ++ c.newTac ++ suf
  return data

/-- Byte offset of the beginning of the line containing byte position `pos`. -/
def findLineStart (fileData : String) (pos : Nat) : Nat := Id.run do
  let mut i := pos
  while i > 0 do
    if fileData.get ⟨i - 1⟩ == '\n' then return i
    i := i - 1
  return 0

/-- Number of leading space characters starting at byte offset `pos`. -/
def lineIndent (fileData : String) (pos : Nat) : Nat := Id.run do
  let len := fileData.utf8ByteSize
  let mut n := 0
  let mut i := pos
  while i < len do
    let c := fileData.get ⟨i⟩
    if c == ' ' || c == '\t' then n := n + 1
    else break
    i := i + 1
  return n

/-- Given the byte offset at the start of a `have`-line, return the byte offset
    of the `\n` at the end of the last indented body line. For a single-line
    `have`, this is the `\n` at the end of that line (or EOF). -/
def findHaveBlockEnd (fileData : String) (lineStart : Nat) : Nat := Id.run do
  let len := fileData.utf8ByteSize
  let baseIndent := lineIndent fileData lineStart
  -- Skip to end of the have line
  let mut pos := lineStart
  while pos < len && fileData.get ⟨pos⟩ != '\n' do pos := pos + 1
  let mut blockEnd := pos  -- \n of the have line (or EOF)
  if pos < len then pos := pos + 1  -- advance past newline
  -- Include all subsequent lines with strictly deeper indentation
  while pos < len do
    let mut eol := pos
    while eol < len && fileData.get ⟨eol⟩ != '\n' do eol := eol + 1
    let lineLen := eol - pos
    let ind := lineIndent fileData pos
    -- Blank line: skip but don't update blockEnd
    if ind >= lineLen then
      pos := if eol < len then eol + 1 else eol
      continue
    if ind <= baseIndent then break
    blockEnd := eol
    pos := if eol < len then eol + 1 else eol
  return blockEnd

/-- Extend a byte range to cover full lines, if the content before startPos
    on its line is only whitespace. This ensures clean deletion of dead code. -/
def extendToFullLines (fileData : String) (startPos endPos : Nat) : Nat × Nat := Id.run do
  let len := fileData.utf8ByteSize
  -- Scan backwards: check if everything before startPos on same line is whitespace
  let mut s := startPos
  let mut onlyWS := true
  while s > 0 do
    let prev := s - 1
    let c := fileData.get ⟨prev⟩
    if c == '\n' then break
    if c != ' ' && c != '\t' then
      onlyWS := false
      break
    s := prev
  if !onlyWS then return (startPos, endPos)
  -- Scan forward from endPos past trailing whitespace + newline
  let mut e := endPos
  while e < len do
    let c := fileData.get ⟨e⟩
    if c == '\n' then return (s, e + 1)
    if c != ' ' && c != '\t' then return (s, e)
    e := e + 1
  return (s, e)

-- ═══════════════════════════════════════════════════════════════════════════
-- In-process verification
-- ═══════════════════════════════════════════════════════════════════════════

/-- Re-elaborate modified file text using the already-loaded import environment.
    Returns an array of (byteOffset, line, message) for each error.
    This is fast because we skip import processing entirely. -/
def verifyText (importEnv : Environment) (headerEndPos : String.Pos)
    (optText : String) (path : String) : IO (Array (Nat × Nat × String)) := do
  let inputCtx := Parser.mkInputContext optText path
  let opts := Options.empty |>.setNat `maxHeartbeats 800000
  let mut cmdState : Command.State := Command.mkState importEnv {} opts
  let mut ps : ModuleParserState := { pos := headerEndPos }

  let mut hitCrash := false
  while !hitCrash do
    let pmctx : ParserModuleContext := {
      env := cmdState.env, options := cmdState.scopes.head!.opts,
      currNamespace := cmdState.scopes.head!.currNamespace,
      openDecls := cmdState.scopes.head!.openDecls
    }
    let (cmd, ps', msgs) := Parser.parseCommand inputCtx pmctx ps cmdState.messages
    ps := ps'
    cmdState := { cmdState with messages := msgs }

    if cmd.isOfKind ``Parser.Command.eoi then break

    let cmdCtx : Command.Context := {
      fileName := path, fileMap := inputCtx.fileMap, currRecDepth := 0,
      cmdPos := cmd.getPos?.getD ps.pos, macroStack := [],
      currMacroScope := firstFrontendMacroScope,
      ref := cmd, snap? := none, cancelTk? := none, suppressElabErrors := false
    }

    let eio := Command.elabCommand cmd |>.run cmdCtx |>.run cmdState
    match ← eio.toBaseIO with
    | .ok ((), s') => cmdState := s'
    | .error _ => hitCrash := true

  let mut errors : Array (Nat × Nat × String) := #[]
  for msg in cmdState.messages.toList do
    if msg.severity == .error then
      let data ← msg.data.toString
      errors := errors.push (msg.pos.line, msg.pos.column, data.take 200)
  return errors

/-- Incremental verification using command-state checkpoints.

    Instead of re-elaborating the entire file from the import header, resume
    from the last command checkpoint whose byte position is ≤ the first
    modification.  This is correct because:

    • Text before the first modification is identical in original and modified
      versions, so the checkpoint's parser position is still valid.
    • The checkpoint's `Command.State` contains the fully elaborated
      `Environment` and scopes (namespace, `open`, `set_option`) from all
      commands up to that point.
    • Only errors from re-elaborated (modified) commands are reported.

    Falls back to full `verifyText` if no useful checkpoint exists. -/
def verifyTextIncremental
    (checkpoints : Array (String.Pos × Command.State))
    (importEnv : Environment) (headerEndPos : String.Pos)
    (optText : String) (path : String) (firstModByte : Nat)
    : IO (Array (Nat × Nat × String)) := do
  -- Find the last checkpoint whose pos ≤ firstModByte
  let mut resumeIdx : Nat := 0
  let mut foundUseful := false
  for i in [:checkpoints.size] do
    if let some cp := checkpoints[i]? then
      let pos : String.Pos := cp.1
      if pos.byteIdx ≤ firstModByte && pos.byteIdx > headerEndPos.byteIdx then
        resumeIdx := i
        foundUseful := true
  -- Fall back to full verification if no checkpoint after header
  if !foundUseful then
    return ← verifyText importEnv headerEndPos optText path
  let some cp := checkpoints[resumeIdx]? | return ← verifyText importEnv headerEndPos optText path
  let resumePos : String.Pos := cp.1
  let resumeCmdState : Command.State := cp.2

  let inputCtx := Parser.mkInputContext optText path
  -- Reuse the checkpoint's command state (preserves env, scopes, options)
  -- but clear messages so we only see errors from re-elaborated commands
  let mut cmdState : Command.State := { resumeCmdState with messages := MessageLog.empty }
  let mut ps : ModuleParserState := { pos := resumePos }

  let mut hitCrash := false
  while !hitCrash do
    let pmctx : ParserModuleContext := {
      env := cmdState.env, options := cmdState.scopes.head!.opts,
      currNamespace := cmdState.scopes.head!.currNamespace,
      openDecls := cmdState.scopes.head!.openDecls
    }
    let (cmd, ps', msgs) := Parser.parseCommand inputCtx pmctx ps cmdState.messages
    ps := ps'
    cmdState := { cmdState with messages := msgs }

    if cmd.isOfKind ``Parser.Command.eoi then break

    let cmdCtx : Command.Context := {
      fileName := path, fileMap := inputCtx.fileMap, currRecDepth := 0,
      cmdPos := cmd.getPos?.getD ps.pos, macroStack := [],
      currMacroScope := firstFrontendMacroScope,
      ref := cmd, snap? := none, cancelTk? := none, suppressElabErrors := false
    }

    let eio := Command.elabCommand cmd |>.run cmdCtx |>.run cmdState
    match ← eio.toBaseIO with
    | .ok ((), s') => cmdState := s'
    | .error _ => hitCrash := true

  let mut errors : Array (Nat × Nat × String) := #[]
  for msg in cmdState.messages.toList do
    if msg.severity == .error then
      let data ← msg.data.toString
      errors := errors.push (msg.pos.line, msg.pos.column, data.take 200)
  return errors

/-- Block-local re-verification.
    Re-elaborates ONLY the single top-level command that contains
    `[firstModByte, lastModByte)`. Returns errors restricted to that
    one command. Falls back to `verifyTextIncremental` when:
      • no usable checkpoint exists at/before `firstModByte`, or
      • the modification crosses a command boundary
        (i.e. `lastModByte` lies past the end of the command starting at the checkpoint).

    Soundness invariant: for tactic-position replacements inside a
    `theorem T : P := …` with `P : Prop`, proof irrelevance guarantees
    that the resulting `Environment` delta `Δ_k` is observationally
    identical to the original. Cross-candidate interactions are caught
    by the subsequent batch `verifyTextIncremental` pass on the surviving
    set.

    Command boundaries are obtained from `Parser.parseCommand`,
    the same parser the Lean kernel uses. -/
def verifyTextBlockLocal
    (checkpoints : Array (String.Pos × Command.State))
    (importEnv   : Environment) (headerEndPos : String.Pos)
    (optText path : String)
    (firstModByte lastModByte : Nat)
    : IO (Array (Nat × Nat × String)) := do
  -- 1. Find the latest checkpoint whose pos ≤ firstModByte (and past the header).
  let mut resumeIdx : Nat := 0
  let mut foundUseful := false
  for i in [:checkpoints.size] do
    if let some cp := checkpoints[i]? then
      let pos : String.Pos := cp.1
      if pos.byteIdx ≤ firstModByte && pos.byteIdx > headerEndPos.byteIdx then
        resumeIdx := i
        foundUseful := true
  if !foundUseful then
    -- No checkpoint inside the body : fall back to the file-suffix verifier.
    return ← verifyTextIncremental checkpoints importEnv headerEndPos optText path firstModByte
  let some cp := checkpoints[resumeIdx]?
    | return ← verifyTextIncremental checkpoints importEnv headerEndPos optText path firstModByte
  let resumePos      : String.Pos    := cp.1
  let resumeCmdState : Command.State := cp.2

  let inputCtx := Parser.mkInputContext optText path
  -- Reuse the checkpoint's elaborated env/scopes/options; clear messages so
  -- we observe only this command's diagnostics.
  let mut cmdState : Command.State := { resumeCmdState with messages := MessageLog.empty }
  let ps : ModuleParserState := { pos := resumePos }

  -- 2. Parse exactly ONE top-level command from the checkpoint.
  let pmctx : ParserModuleContext := {
    env := cmdState.env, options := cmdState.scopes.head!.opts,
    currNamespace := cmdState.scopes.head!.currNamespace,
    openDecls := cmdState.scopes.head!.openDecls
  }
  let (cmd, ps', msgs) := Parser.parseCommand inputCtx pmctx ps cmdState.messages
  cmdState := { cmdState with messages := msgs }

  -- EOI right at the checkpoint : nothing to elaborate, return empty.
  if cmd.isOfKind ``Parser.Command.eoi then
    return #[]

  -- 3. Span containment check.  `ps'.pos` is the parser position AFTER this
  -- command (i.e. the start of the next command). If the modification's
  -- right edge `lastModByte` extends past it, the edit straddles a command
  -- boundary and block-local verification is unsound for it. Fall back.
  if lastModByte > ps'.pos.byteIdx then
    return ← verifyTextIncremental checkpoints importEnv headerEndPos optText path firstModByte

  -- 4. Elaborate this single command.
  let cmdCtx : Command.Context := {
    fileName := path, fileMap := inputCtx.fileMap, currRecDepth := 0,
    cmdPos := cmd.getPos?.getD ps'.pos, macroStack := [],
    currMacroScope := firstFrontendMacroScope,
    ref := cmd, snap? := none, cancelTk? := none, suppressElabErrors := false
  }
  let eio := Command.elabCommand cmd |>.run cmdCtx |>.run cmdState
  match ← eio.toBaseIO with
  | .ok ((), s') => cmdState := s'
  | .error _    => pure ()  -- crash → diagnostics already in cmdState.messages

  -- 5. Restrict reported errors to those whose source position lies inside
  -- this command's span.  This filters out any stale messages that the
  -- checkpoint state happened to carry (defensive - `MessageLog.empty` above
  -- should already prevent this).
  let cmdStartLine := (inputCtx.fileMap.toPosition resumePos).line
  let cmdEndLine   := (inputCtx.fileMap.toPosition ps'.pos).line
  let mut errors : Array (Nat × Nat × String) := #[]
  for msg in cmdState.messages.toList do
    if msg.severity == .error &&
       msg.pos.line ≥ cmdStartLine && msg.pos.line ≤ cmdEndLine then
      let data ← msg.data.toString
      errors := errors.push (msg.pos.line, msg.pos.column, data.take 200)
  return errors

/-- Re-elaborate and return both errors and warnings.
    Warnings include "tactic does nothing", "never executed", "<;> where ; suffices", etc.
    Returns (errors, warnings) where each entry is (bytePos, line, col, message). -/
def elaborateAndCollect (importEnv : Environment) (headerEndPos : String.Pos)
    (text : String) (path : String) : IO (Array (Nat × Nat × String) × Array (Nat × Nat × Nat × String)) := do
  let inputCtx := Parser.mkInputContext text path
  let opts := Options.empty |>.setNat `maxHeartbeats 800000
  let mut cmdState : Command.State := Command.mkState importEnv {} opts
  let mut ps : ModuleParserState := { pos := headerEndPos }
  let fileMap := inputCtx.fileMap

  let mut hitCrash := false
  while !hitCrash do
    let pmctx : ParserModuleContext := {
      env := cmdState.env, options := cmdState.scopes.head!.opts,
      currNamespace := cmdState.scopes.head!.currNamespace,
      openDecls := cmdState.scopes.head!.openDecls
    }
    let (cmd, ps', msgs) := Parser.parseCommand inputCtx pmctx ps cmdState.messages
    ps := ps'
    cmdState := { cmdState with messages := msgs }

    if cmd.isOfKind ``Parser.Command.eoi then break

    let cmdCtx : Command.Context := {
      fileName := path, fileMap := fileMap, currRecDepth := 0,
      cmdPos := cmd.getPos?.getD ps.pos, macroStack := [],
      currMacroScope := firstFrontendMacroScope,
      ref := cmd, snap? := none, cancelTk? := none, suppressElabErrors := false
    }

    let eio := (do Command.elabCommand cmd; Command.runLinters cmd) |>.run cmdCtx |>.run cmdState
    match ← eio.toBaseIO with
    | .ok ((), s') => cmdState := s'
    | .error _ => hitCrash := true

  let mut errors : Array (Nat × Nat × String) := #[]
  let mut warnings : Array (Nat × Nat × Nat × String) := #[]
  for msg in cmdState.messages.toList do
    let data ← msg.data.toString
    if msg.severity == .error then
      errors := errors.push (msg.pos.line, msg.pos.column, data.take 200)
    else if msg.severity == .warning then
      -- Convert line:col position to byte offset using FileMap
      let bytePos := fileMap.ofPosition msg.pos |>.byteIdx
      warnings := warnings.push (bytePos, msg.pos.line, msg.pos.column, data)
  return (errors, warnings)

-- ═══════════════════════════════════════════════════════════════════════════
-- Phase 3: Warning-guided cleanup : dead arm removal in <;> chains
-- ═══════════════════════════════════════════════════════════════════════════

/-- Classify a warning message into an actionable type. -/
inductive WarningKind where
  | doesNothing   -- "'X' tactic does nothing"
  | neverExecuted -- "this tactic is never executed"
  | useSemicolon  -- "where (tac1; tac2) would suffice"
  | other
  deriving Repr, BEq

def classifyWarning (msg : String) : WarningKind :=
  if msg.containsSubstr "tactic does nothing" then .doesNothing
  else if msg.containsSubstr "is never executed" then .neverExecuted
  else if msg.containsSubstr "would suffice" then .useSemicolon
  else .other

/-- A warning with its byte position and classification. -/
structure LocatedWarning where
  bytePos : Nat
  line    : Nat
  col     : Nat
  msg     : String
  kind    : WarningKind
  deriving Repr

/-- Line-based cleanup: remove dead `<;>` arms from text using warning positions.
    Works on lines rather than byte offsets for robustness.

    Six phases, applied in order:
    - Phase A: Remove full-line `<;>` arms (line starts with `<;>`, has dead warning, no inner `<;>`)
    - Phase B: Remove dead-only lines (no `<;>`/`{`/`}`) preceded by a `<;>` continuation
    - Phase F: Remove multi-line dead blocks (neverExecuted + doesNothing with `{` in tactic)
    - Phase E: Inline dead arm removal (remove ` <;> DEAD_TAC` patterns within lines)
    - Phase C: Trim trailing `<;>` from lines preceding removed blocks
    - Phase D: Replace ` <;> ` with `; ` for useSemicolon warnings on surviving lines

    Returns the cleaned text. -/
def removeDeadWarningLines (text : String) (warnings : Array LocatedWarning) : String := Id.run do
  let lines := text.splitOn "\n"
  let numLines := lines.length

  -- Build set of line numbers (1-indexed) that have dead warnings
  let mut deadLines : Std.HashSet Nat := {}
  for w in warnings do
    if w.kind == .doesNothing || w.kind == .neverExecuted then
      deadLines := deadLines.insert w.line

  -- ─── Phase A: Mark full-line dead `<;>` arms for removal ───────────────
  -- A line qualifies if:
  --   (a) its trimmed content starts with `<;>`, AND
  --   (b) it has a dead warning on it, AND
  --   (c) there is NO other `<;>` in the line content after the leading one
  --       (ensures we don't remove lines with mixed dead/live inline arms)
  let mut removeLines : Std.HashSet Nat := {}
  for lineIdx in [:numLines] do
    let lineNo := lineIdx + 1  -- 1-indexed
    if deadLines.contains lineNo then
      let lineText := lines[lineIdx]!
      let trimmed := lineText.trim
      -- Full-line <;> arm: starts with <;>
      if trimmed.startsWith "<;>" then
        -- Check: no other <;> after the leading one
        let afterLeading := (trimmed.drop 3).trim
        let hasInnerSeq := afterLeading.containsSubstr "<;>"
        if !hasInnerSeq then
          removeLines := removeLines.insert lineNo

  -- ─── Phase B: Remove dead-only lines preceded by `<;>` ────────────────
  -- but where the preceding non-empty line ends with <;>
  -- Only if the line has a single tactic (no internal <;>)
  for lineIdx in [:numLines] do
    let lineNo := lineIdx + 1
    if deadLines.contains lineNo && !removeLines.contains lineNo then
      let lineText := lines[lineIdx]!
      let trimmed := lineText.trim
      -- Skip empty lines, lines with <;>, { or } (multi-line blocks/chains)
      if trimmed.isEmpty then continue
      if trimmed.containsSubstr "<;>" then continue
      if trimmed.containsSubstr "{" then continue
      if trimmed.containsSubstr "}" then continue
      -- Check if the dead tactic is the entire meaningful content of the line
      -- AND the preceding non-removed line ends with <;>
      -- Find preceding non-empty, non-removed line
      let mut prevLine := ""
      let mut pi := lineIdx
      while pi > 0 do
        pi := pi - 1
        if !removeLines.contains (pi + 1) then
          let pt := lines[pi]!.trim
          if !pt.isEmpty then
            prevLine := pt
            break
      if prevLine.endsWith "<;>" then
        removeLines := removeLines.insert lineNo

  -- ─── Phase F: Multi-line dead block removal ───────────────────────────
  -- When a line has both `neverExecuted` AND `doesNothing` warnings (confirming the tactic
  -- at that position is truly dead), AND was NOT removed by Phase A/B, AND its preceding
  -- non-removed line ends with `<;>`, remove the entire multi-line block by tracking
  -- paren/brace nesting until balanced.
  -- Additionally, require that the doesNothing tactic text contains `{` : indicating a
  -- multi-line block that Phase E can't handle inline.
  let mut neverExecLines : Std.HashSet Nat := {}
  for w in warnings do
    if w.kind == .neverExecuted then
      neverExecLines := neverExecLines.insert w.line

  -- Collect lines with doesNothing warnings whose tactic text contains `{`
  let mut multiLineDeadLines : Std.HashSet Nat := {}
  for w in warnings do
    if w.kind == .doesNothing then
      let msg := w.msg
      if msg.startsWith "'" then
        let inner := msg.drop 1
        let endPos := inner.posOf '\''
        if endPos != inner.endPos then
          let tacText := inner.extract 0 endPos
          if tacText.containsSubstr "{" then
            multiLineDeadLines := multiLineDeadLines.insert w.line

  for lineIdx in [:numLines] do
    let lineNo := lineIdx + 1
    -- Require both neverExecuted and a multi-line doesNothing tactic on this line
    if neverExecLines.contains lineNo && multiLineDeadLines.contains lineNo && !removeLines.contains lineNo then
      let lineText := lines[lineIdx]!
      let trimmed := lineText.trim
      if trimmed.isEmpty then continue
      -- Find preceding non-empty, non-removed line
      let mut prevLine := ""
      let mut pi := lineIdx
      while pi > 0 do
        pi := pi - 1
        if !removeLines.contains (pi + 1) then
          let pt := lines[pi]!.trim
          if !pt.isEmpty then
            prevLine := pt
            break
      if !prevLine.endsWith "<;>" then continue
      -- This dead multi-line block follows a `<;>` : remove it
      -- Track paren/brace nesting to find the end of the block
      let mut depth : Int := 0
      let mut k := lineIdx
      let mut firstLine := true
      while k < numLines do
        let kText := lines[k]!
        for c in kText.toList do
          if c == '(' || c == '{' then depth := depth + 1
          if c == ')' || c == '}' then depth := depth - 1
        removeLines := removeLines.insert (k + 1)
        if !firstLine && depth <= 0 then break
        firstLine := false
        k := k + 1

  -- ─── Phase E: Inline dead arm removal ─────────────────────────────────
  -- For each dead warning, if its tactic text is a parenthesized form like
  -- `(try exact h₆)`, remove ` <;> (try exact h₆)` or `(try exact h₆) <;> ` from the line.
  -- Also handles bare simple tactics (no spaces/braces) like `simp_all` at line ends.
  --
  -- Tactic text is extracted from warning messages of the form:
  --   'TACTIC_TEXT' tactic does nothing
  -- Lean 4 uses single quotes for this; tactic syntax never contains single quotes,
  -- so posOf '\'' is safe for extraction.
  -- Extract dead tactic names from warning messages.
  let mut inlineEdits : Std.HashMap Nat (Array String) := {}  -- lineNo → dead tactic strings
  for w in warnings do
    if w.kind == .doesNothing then
      -- Extract tactic text from message: pattern is `'TACTIC' tactic does nothing`
      let msg := w.msg
      if msg.startsWith "'" then
        -- Extract tactic text: pattern is 'TACTIC' tactic does nothing
        let inner := msg.drop 1  -- after first '
        let endPos := inner.posOf '\''
        if endPos != inner.endPos then
          let tacText := inner.extract 0 endPos
          -- Skip if the line is already marked for removal
          if !removeLines.contains w.line then
            -- Accept parenthesized dead tactics (safe inline removal)
            -- OR bare dead tactics that don't contain spaces/braces (safe at end of line)
            let isParenthesized := tacText.startsWith "(" && tacText.endsWith ")"
            let isSimpleBare := !tacText.containsSubstr " " &&
                                !tacText.containsSubstr "{" &&
                                !tacText.containsSubstr "(" &&
                                !tacText.isEmpty
            if isParenthesized || isSimpleBare then
              let arr : Array String := inlineEdits.getD w.line #[]
              inlineEdits := inlineEdits.insert w.line (arr.push tacText)

  -- Apply inline edits: for each line, remove ` <;> DEAD_TACTIC` patterns
  let mut editedLines : Std.HashMap Nat String := {}
  for (lineNo, deadTacs) in inlineEdits.toList do
    let lineIdx := lineNo - 1
    if lineIdx < numLines then
      let mut lineText := lines[lineIdx]!
      for tac in deadTacs do
        -- Try removing ` <;> TACTIC` first (tactic AFTER a combinator)
        let pat := s!" <;> {tac}"
        if lineText.containsSubstr pat then
          lineText := lineText.replace pat ""
        else
          -- Try removing `TACTIC <;> ` (tactic BEFORE a combinator)
          let pat2 := s!"{tac} <;> "
          if lineText.containsSubstr pat2 then
            lineText := lineText.replace pat2 ""
          else
            -- Try removing ` <;> TACTIC` at end of line (no trailing space)
            let trimmed := lineText.trimRight
            let endPat := s!" <;> {tac}"
            if trimmed.endsWith endPat then
              lineText := trimmed.dropRight endPat.length
      editedLines := editedLines.insert lineNo lineText

  -- ─── Phase C: Trim trailing `<;>` from lines preceding removed blocks ─
  -- Build the output line by line
  let mut resultLines : Array String := #[]
  for lineIdx in [:numLines] do
    let lineNo := lineIdx + 1
    if removeLines.contains lineNo then continue

    -- Use inline-edited version if available
    let lineText := if let some edited := editedLines.get? lineNo then edited
                    else lines[lineIdx]!

    -- Check if the next non-removed line was removed (i.e., this line may need <;> trimming)
    let nextLineNo := lineNo + 1
    let mut nextIsRemoved := false
    if nextLineNo <= numLines && removeLines.contains nextLineNo then
      nextIsRemoved := true

    if nextIsRemoved then
      -- Check if this line ends with <;> (after trimming trailing whitespace)
      let trimmedRight := lineText.trimRight
      if trimmedRight.endsWith "<;>" then
        -- Also check that all following removed lines are contiguous
        -- and the first non-removed line after them doesn't start with <;>
        let mut allNextRemoved := true
        let mut firstSurvivor := numLines
        let mut k := lineIdx + 1
        while k < numLines do
          let kLineNo := k + 1
          if removeLines.contains kLineNo then
            k := k + 1
          else
            firstSurvivor := k
            allNextRemoved := false
            break
        -- If the first surviving line doesn't start with <;>, trim the trailing <;> from this line
        let survivorStartsWithSeq :=
          if firstSurvivor < numLines then
            lines[firstSurvivor]!.trim.startsWith "<;>"
          else false
        if !survivorStartsWithSeq then
          -- Trim trailing ` <;>` (with preceding space if present)
          let t := trimmedRight.dropRight 3 |>.trimRight
          resultLines := resultLines.push t
        else
          resultLines := resultLines.push lineText
      else
        resultLines := resultLines.push lineText
    else
      resultLines := resultLines.push lineText

  -- ─── Phase D: Replace `<;>` with `;` for useSemicolon warnings ────────
  -- We work on the original line indices since warnings use original line numbers
  -- Need to map original line numbers to result line positions
  let mut semicolonOrigLines : Std.HashSet Nat := {}
  for w in warnings do
    if w.kind == .useSemicolon then
      let lineNo := w.line
      -- Only apply to surviving (non-removed) lines
      if !removeLines.contains lineNo then
        semicolonOrigLines := semicolonOrigLines.insert lineNo

  let mut finalLines : Array String := #[]
  -- We need to track original line number → result line index mapping
  -- Since we built resultLines by iterating over original lines and skipping removed ones,
  -- we can replay the mapping
  let mut resultIdx : Nat := 0
  for lineIdx in [:numLines] do
    let lineNo := lineIdx + 1
    if removeLines.contains lineNo then continue
    if resultIdx < resultLines.size then
      let mut lineText := resultLines[resultIdx]!
      if semicolonOrigLines.contains lineNo then
        -- Replace first ` <;> ` with `; ` on this line
        lineText := lineText.replace " <;> " "; "
      finalLines := finalLines.push lineText
    resultIdx := resultIdx + 1

  "\n".intercalate finalLines.toList

/-- Compute which candidate indices are blamed for a set of errors.
    Maps error byte positions to the candidate whose opt-text span
    contains or is near the error. -/
def mapErrorsToCandidates (candidates : Array Candidate) (optText : String)
    (errors : Array (Nat × Nat × String)) : Std.HashSet Nat := Id.run do
  let optInputCtx := Parser.mkInputContext optText ""
  let optFileMap := optInputCtx.fileMap
  -- Compute each candidate's line range in the opt text
  let indexed := candidates.zipIdx.qsort
    (fun a b => a.1.startPos < b.1.startPos)
  let mut cumDelta : Int := 0
  let mut candOptLines : Array (Nat × Nat × Nat) := #[] -- (origIdx, startLine, endLine)
  for (c, idx) in indexed do
    let optStart := (c.startPos : Int) + cumDelta
    let optEnd := optStart + (c.newTac.utf8ByteSize : Int)
    let sl := optFileMap.toPosition ⟨optStart.toNat⟩ |>.line
    let el := optFileMap.toPosition ⟨max optStart.toNat (optEnd.toNat - 1)⟩ |>.line
    candOptLines := candOptLines.push (idx, sl, el)
    cumDelta := cumDelta + (c.newTac.utf8ByteSize : Int) - ((c.endPos - c.startPos : Nat) : Int)

  let WINDOW := 5
  let mut bad : Std.HashSet Nat := {}

  for (errLine, _, _) in errors do
    let mut matched := false
    -- Direct blame: error within ±WINDOW of a candidate
    for (idx, sl, el) in candOptLines do
      if sl ≤ errLine + WINDOW && errLine ≤ el + WINDOW then
        bad := bad.insert idx
        matched := true
    -- Downstream blame: error after a replacement, blame nearest preceding
    if !matched then
      let mut closestIdx : Option Nat := none
      let mut closestDist : Nat := 999999
      for (idx, _, el) in candOptLines do
        if el ≤ errLine then
          let d := errLine - el
          if d < closestDist then
            closestDist := d
            closestIdx := some idx
      if let some ci := closestIdx then
        bad := bad.insert ci

  return bad

-- ═══════════════════════════════════════════════════════════════════════════
-- Main file processor
-- ═══════════════════════════════════════════════════════════════════════════

set_option maxRecDepth 4096 in
def processFile (importEnv : Environment) (path : String) (cfg : AblationConfig := {}) : IO Unit := do
  let fileData ← IO.FS.readFile path
  traceMem "00_start" cfg
  let inputCtx := Parser.mkInputContext fileData path
  let (_header, parserState, messages) ← Parser.parseHeader inputCtx

  let headerEndPos := parserState.pos
  -- `server.enabled true` is required: Lean 4 gates InfoTree population
  -- (TacticInfo, TermInfo nodes) behind this flag.  Without it, the InfoTree
  -- is empty and the optimizer finds zero candidates.
  let opts := (Options.empty
    |>.setBool `server.enabled true
    |>.setNat `maxHeartbeats 0
    |>.setBool `linter.unusedVariables true)
  let mut cmdState : Command.State := Command.mkState importEnv messages opts
  cmdState := { cmdState with infoState := { cmdState.infoState with enabled := true } }

  -- ── Initial elaboration with command-state checkpoints ──────────────
  -- Save (parserPos, cmdState) at each top-level command boundary.
  -- These checkpoints let us resume verification from the last unmodified
  -- command rather than re-elaborating the entire file from scratch.
  -- For a file with preamble (open, set_option, helper lemmas) followed by
  -- the main theorem, this avoids redundant re-elaboration of all preamble
  -- commands on every verification round.
  let elaborateStartMs ← IO.monoMsNow
  let mut cmdCheckpoints : Array (String.Pos × Command.State) := #[]
  let mut ps := parserState
  while true do
    -- Checkpoint: save state before parsing this command
    cmdCheckpoints := cmdCheckpoints.push (ps.pos, cmdState)
    let pmctx : ParserModuleContext := {
      env := cmdState.env, options := cmdState.scopes.head!.opts,
      currNamespace := cmdState.scopes.head!.currNamespace,
      openDecls := cmdState.scopes.head!.openDecls
    }
    let (cmd, ps', messages) := Parser.parseCommand inputCtx pmctx ps cmdState.messages
    ps := ps'
    cmdState := { cmdState with messages := messages }

    if cmd.isOfKind ``Parser.Command.eoi then break

    let cmdCtx : Command.Context := {
      fileName := path, fileMap := inputCtx.fileMap, currRecDepth := 0,
      cmdPos := ps.pos, macroStack := [], currMacroScope := firstFrontendMacroScope,
      ref := cmd, snap? := none, cancelTk? := none, suppressElabErrors := false
    }

    let eio := Command.elabCommand cmd |>.run cmdCtx |>.run cmdState
    match ← eio.toIO (fun _ => IO.userError "command error") with
    | ((), cmdState') => cmdState := cmdState'

  let trees := cmdState.infoState.trees
  let elaborateEndMs ← IO.monoMsNow
  let elaborationTimeMs := elaborateEndMs - elaborateStartMs
  IO.println s!"[AST ELABORATED] in {elaborationTimeMs}ms ({cmdCheckpoints.size} command checkpoints saved)"
  traceMem "01_post_elab" cfg
  let ctx : Core.Context := {
    fileName := path, fileMap := inputCtx.fileMap,
    options := opts,
    currRecDepth := 0, maxRecDepth := 1000, maxHeartbeats := 0, ref := default
  }
  let state : Core.State := { env := cmdState.env }

  -- Collect linter messages
  let mut unusedPos : List String := []
  for msg in cmdState.messages.toList do
    let data_str ← msg.data.toString
    if (data_str.splitOn "unused variable").length > 1 then
      unusedPos := s!"{msg.pos.line}:{msg.pos.column}" :: unusedPos

  let candsRef ← IO.mkRef ([] : List Candidate)
  let deadCodeRef ← IO.mkRef ([] : List (Nat × Nat))
  -- L1: Dedup map : tracks first occurrence of each (type, proof) pair
  let dedupMapRef ← IO.mkRef (Std.HashMap.emptyWithCapacity : Std.HashMap DedupKey DedupVal)
  -- L2: Collected have-blocks for Expr-level anti-unification (post-fold pass)
  let haveBlocksRef ← IO.mkRef (#[] : Array HaveBlockInfo)
  -- L3: Counter for exact? attempts (bounded to prevent excessive search time)
  let exactQCountRef ← IO.mkRef (0 : Nat)
  let MAX_EXACT_Q_ATTEMPTS := 15  -- max exact? calls per file
  -- Adaptive time budget: scale limits based on actual elaboration cost,
  -- not hardcoded constants.  Heavy Mathlib proofs that take 5 minutes to
  -- elaborate need proportionally more time for the optimizer to work.
  let startTimeMs := elaborateStartMs  -- measure from start of elaboration
  let maxExactQTimeMs := max 180000 (elaborationTimeMs * 2)  -- exact? budget = 2× elaboration time
  let maxVerifyTimeMs := max 420000 (elaborationTimeMs * 5)  -- verify budget = 5× elaboration time
  -- Global fold-phase budget: cap total automation search time.
  -- Even with per-tactic timeouts, 100+ goals × 15 tactics = very slow.
  -- Budget = max(120s, 3× elaboration time)
  let maxFoldTimeMs := max 120000 (elaborationTimeMs * 3)
  let foldBudgetExceededRef ← IO.mkRef false

  let eio := (do
    IO.println "[FOLD START]"
    let usages ← collectFVarUsages trees

    IO.println "[AFTER USAGES]"
    for tree in trees do
      let _ ← tree.foldInfoM (init := 0) fun _cfg info acc => do
        match info with
        | .ofTacticInfo ti =>
          if let (some startPos, some endPos) := (info.stx.getPos?, info.stx.getTailPos?) then
            let kind := s!"{info.stx.getKind}"

            -- Dead code detection + L1 dedup for have-blocks
            if kind.startsWith "Lean.Parser.Tactic.tacticHave" || kind.startsWith "Lean.Parser.Tactic.have" then
              if !ti.goalsBefore.isEmpty && !ti.goalsAfter.isEmpty then
                let gBefore := ti.goalsBefore.head!
                let gAfter := ti.goalsAfter.head!
                if let some declBefore := ti.mctxBefore.findDecl? gBefore then
                  if let some declAfter := ti.mctxAfter.findDecl? gAfter then
                    let mut anyUsed := false
                    let mut anyAdded := false
                    let mut newHypName := ""
                    let mut newHypType := ""
                    for ldecl in declAfter.lctx do
                      if !declBefore.lctx.contains ldecl.fvarId then
                        anyAdded := true
                        if usages.contains ldecl.fvarId then
                          anyUsed := true
                        -- Capture the first newly introduced hypothesis for L1 dedup
                        if newHypName.isEmpty then
                          newHypName := ldecl.userName.toString
                          newHypType ← try
                            MetaM.run' (withMCtx ti.mctxAfter do
                              let ty ← instantiateMVars ldecl.type
                              return s!"{ty}")
                          catch _ => pure ""

                    -- Dead code removal
                    if anyAdded && !anyUsed then
                      let ls := findLineStart fileData startPos.byteIdx
                      let mut eol := ls
                      while eol < fileData.utf8ByteSize && fileData.get ⟨eol⟩ != '\n' do eol := eol + 1
                      let lineText := fileData.extract ⟨ls⟩ ⟨eol⟩
                      let trimLine := lineText.trimLeft
                      if trimLine.startsWith "have " || trimLine.startsWith "have:" ||
                         trimLine.startsWith "haveI " || trimLine.startsWith "haveI:" then
                        let blockEnd := findHaveBlockEnd fileData ls
                        -- Independent syntactic witness check: walk this command's
                        -- top Syntax for any Ident named `newHypName` whose source
                        -- position is past the have's tail. If found, the FVar usage
                        -- analysis missed a downstream reference (lazy elaboration,
                        -- macro expansion, …) and we must not remove the have.
                        let stillReferenced :=
                          match InfoTree.topStx? tree with
                          | some topStx => syntaxMentionsNameAfter topStx endPos.byteIdx newHypName.toName
                          | none        => false
                        if stillReferenced then
                          IO.println s!"[DEAD_CODE_SUPPRESSED] {ls}-{blockEnd}: name `{newHypName}` still appears in source past byte {endPos.byteIdx} (FVar analysis missed it)"
                        else
                          IO.println s!"[NATIVE_DEAD_CODE] {ls}-{blockEnd}"
                          deadCodeRef.modify (fun l => (ls, blockEnd) :: l)

                    -- ═══════════════════════════════════════════════════════
                    -- L1: Have-block deduplication
                    -- ═══════════════════════════════════════════════════════
                    -- For used have-blocks (not dead code), check if an earlier
                    -- have-block with the same (type, proof) pair exists.
                    -- If so, emit a candidate replacing this block's proof with
                    -- `exact <firstHypName>`.
                    if anyAdded && anyUsed && !newHypName.isEmpty && !newHypType.isEmpty then
                      -- Extract the proof text from source
                      let haveText := fileData.extract ⟨startPos.byteIdx⟩ ⟨endPos.byteIdx⟩
                      -- Find the proof part: search for `:=` (not just `=`, which
                      -- would false-match on `>=`, `<=`, `==`, etc.)
                      let mut colonEqPos : Option Nat := none
                      let haveBytes := haveText.utf8ByteSize
                      let mut scanIdx : Nat := 0
                      while scanIdx + 1 < haveBytes do
                        if haveText.get ⟨scanIdx⟩ == ':' && haveText.get ⟨scanIdx + 1⟩ == '=' then
                          colonEqPos := some scanIdx
                          break
                        scanIdx := scanIdx + 1
                      if let some cePos := colonEqPos then
                          -- cePos is the byte offset of `:` in `:=`; proof starts after `=` (cePos+2)
                          let proofText := (haveText.extract ⟨cePos + 2⟩ haveText.endPos).trim
                          let dedupKey : DedupKey := { typeStr := newHypType, proofTxt := proofText }
                          let dedupMap ← dedupMapRef.get
                          if let some firstOcc := dedupMap.get? dedupKey then
                            -- Duplicate found! The first occurrence used hypName `firstOcc.hypName`.
                            -- Scoping check (defense-in-depth): the replacement
                            -- `exact firstOcc.hypName` is sound only if `firstOcc.hypName`
                            -- is actually in scope at this occurrence. dedupMap is file-
                            -- scoped, so two textually identical (type, proof) pairs in
                            -- different branches (by_cases, match arms, separate theorems)
                            -- would otherwise produce a cross-scope reference that fails
                            -- to elaborate. Use declBefore.lctx (pre-have context: the
                            -- exact context where the replacement will be elaborated).
                            let firstOccInScope := Id.run do
                              match declBefore.lctx.findFromUserName? firstOcc.hypName.toName with
                              | some _ => true
                              | none   => false
                            -- Replace this have's proof with `exact <firstHypName>`.
                            -- The subproof starts after `:= ` or `:= by `
                            let isBy := proofText.startsWith "by " || proofText.startsWith "by\n"
                            let replacementTac := if isBy
                              then s!"by exact {firstOcc.hypName}"
                              else firstOcc.hypName
                            -- Emit if shorter or if the dedup reference is more elegant
                            -- (explicit dependency is always an upgrade even at same length)
                            if firstOccInScope && replacementTac.length ≤ proofText.length then
                              -- Proof starts at startPos + cePos + 2 in the original file
                              let proofByteStart := startPos.byteIdx + cePos + 2
                              -- Skip leading whitespace to get the actual proof start
                              let mut actualStart := proofByteStart
                              while actualStart < endPos.byteIdx &&
                                (fileData.get ⟨actualStart⟩ == ' ' ||
                                 fileData.get ⟨actualStart⟩ == '\n' ||
                                 fileData.get ⟨actualStart⟩ == '\t') do
                                actualStart := actualStart + 1
                              IO.println s!"[L1_DEDUP] {actualStart}-{endPos.byteIdx}: `{proofText.take 50}` → `{replacementTac}` (duplicates {firstOcc.hypName})"
                              candsRef.modify (fun l => {
                                startPos := actualStart
                                endPos   := endPos.byteIdx
                                newTac   := replacementTac
                                goalType := newHypType
                                kind     := "L1_dedup"
                                termSize := 1
                                -- L1 dedup replaces identical (type, proof) pairs;
                                -- for Prop types, proof irrelevance guarantees safety;
                                -- for Type, the proofs are textually identical anyway.
                                isPropSafe := true
                              } :: l)
                            else if !firstOccInScope then
                              -- First occurrence is out of scope here (different branch /
                              -- nested scope). Re-register the dedup map to point at this
                              -- occurrence so that subsequent identical proofs in this
                              -- scope can dedup against it. This preserves the dedup
                              -- benefit across scope boundaries.
                              dedupMapRef.set (dedupMap.insert dedupKey {
                                hypName := newHypName
                                bytePos := startPos.byteIdx
                              })
                          else
                            -- First occurrence : register in the dedup map
                            dedupMapRef.set (dedupMap.insert dedupKey {
                              hypName := newHypName
                              bytePos := startPos.byteIdx
                            })

                    -- ═══════════════════════════════════════════════════════
                    -- L2: Collect have-block info for Expr-level anti-unif
                    -- ═══════════════════════════════════════════════════════
                    -- For all used have-blocks (including those caught by L1),
                    -- extract the elaborated proof term for post-fold anti-unification.
                    -- L2 catches near-duplicates that L1 misses (different tactic text,
                    -- same proof structure modulo hypothesis renaming).
                    if anyAdded && anyUsed && !newHypName.isEmpty then
                      -- Guard: verify source text starts with "have" (not set/let/etc.)
                      -- set tactic internally creates have-like InfoTree nodes, but its
                      -- "proof body" is a value expression, not a proof term.
                      let srcPrefix := (fileData.extract startPos ⟨min (startPos.byteIdx + 5) fileData.utf8ByteSize⟩).trimLeft
                      if srcPrefix.startsWith "have" then do
                      -- Extract proof term from MetavarContext
                      let proofExpr? ← try
                        MetaM.run' (withMCtx ti.mctxAfter do
                          let gBefore' := ti.goalsBefore.head!
                          -- For `have h : T := proof`, the eAssignment for gBefore' has the form:
                          --   letFun T proof (fun h => ?continuation)
                          -- We want to extract `proof` from this structure.
                          match ti.mctxAfter.eAssignment.find? gBefore' with
                          | some rawExpr =>
                            -- instantiate and look at the structure
                            let expr ← instantiateMVars rawExpr
                            -- Try to detect letFun pattern: app (app (app (const `letFun) A) proof) (lam ...)
                            let proofBody := match expr with
                              | .app (.app (.app (.app _ _) _) proof) (.lam ..) => some proof
                              | .app (.app (.app _ _) proof) (.lam ..) => some proof
                              | .letE _ _ val _ _ => some val
                              | _ =>
                                -- If it is an app with a lam at the end, try extracting
                                let args := expr.getAppArgs
                                if args.size >= 2 then
                                  match args[args.size - 1]! with
                                  | .lam .. => some args[args.size - 2]!
                                  | _ => none
                                else none

                            match proofBody with
                            | some proof =>
                              let cleanProof ← instantiateMVars proof
                              if cleanProof.hasExprMVar then return none
                              -- β-reduce to normalize: (fun x => f x) a → f a
                              -- This catches equivalences invisible without reduction.
                              let reduced := cleanProof.headBeta
                              return some reduced
                            | none =>
                              return none
                          | none =>
                            return none)
                      catch _ => pure none
                      if let some proofExpr := proofExpr? then
                        -- Compute proof body start position
                        let haveText' := fileData.extract ⟨startPos.byteIdx⟩ ⟨endPos.byteIdx⟩
                        let mut cePos' : Nat := 0
                        let haveBytes' := haveText'.utf8ByteSize
                        let mut foundCE := false
                        while cePos' + 1 < haveBytes' do
                          if haveText'.get ⟨cePos'⟩ == ':' && haveText'.get ⟨cePos' + 1⟩ == '=' then
                            foundCE := true
                            break
                          cePos' := cePos' + 1
                        let mut proofBodyStart := startPos.byteIdx
                        if foundCE then
                          proofBodyStart := startPos.byteIdx + cePos' + 2
                          while proofBodyStart < endPos.byteIdx &&
                            (fileData.get ⟨proofBodyStart⟩ == ' ' ||
                             fileData.get ⟨proofBodyStart⟩ == '\n' ||
                             fileData.get ⟨proofBodyStart⟩ == '\t') do
                            proofBodyStart := proofBodyStart + 1
                        -- Get the elaborated type as Expr, canonical text, and Prop status.
                        -- Canonical text: replace all local FVarIds with positional names
                        -- so structurally identical types across branches compare equal
                        -- (e.g., `x ∈ S` vs `y ∈ S` both become `_lv0 ∈ S`).
                        let (hypTypeExpr, hypTypeStr, hypTypeRaw, hypIsProp) ← try
                          MetaM.run' (withMCtx ti.mctxAfter do
                           withLCtx declAfter.lctx #[] do
                            if let some ldecl := declAfter.lctx.findFromUserName? newHypName.toName then
                              let ty ← instantiateMVars ldecl.type
                              -- Canonicalize: replace local FVarIds with `_lv{i}` names
                              -- in order of first appearance, so cross-branch types match
                              -- (e.g., `x ∈ S` vs `y ∈ S` both become `_lv0 ∈ S`).
                              let fvState := Lean.collectFVars {} ty
                              let mut fvarIdx : Nat := 0
                              let mut fvarMap : Std.HashMap FVarId Name := {}
                              -- Sort FVars deterministically by Name before assigning
                              -- canonical indices. HashSet iteration order is not stable,
                              -- so without sorting, two structurally identical types could
                              -- produce different canonical strings (false-negative match).
                              let sortedFvars := fvState.fvarSet.toArray.qsort (fun a b => a.name.lt b.name)
                              for fv in sortedFvars do
                                if declAfter.lctx.contains fv then
                                  fvarMap := fvarMap.insert fv s!"_lv{fvarIdx}".toName
                                  fvarIdx := fvarIdx + 1
                              let fmt ← Meta.ppExpr ty
                              let rawStr := toString fmt
                              let isProp ← Meta.isProp ty
                              if !fvarMap.isEmpty then
                                -- Text-level substitution of FVar names → canonical names
                                let mut txt := rawStr
                                for (fvId, canonName) in fvarMap.toArray do
                                  if let some ld := declAfter.lctx.find? fvId then
                                    txt := replaceWord txt ld.userName.toString canonName.toString
                                return (ty, txt, rawStr, isProp)
                              else
                                return (ty, rawStr, rawStr, isProp)
                            else return (Expr.sort .zero, "", "", false))  -- fallback
                        catch _ => pure (Expr.sort .zero, "", "", false)
                        haveBlocksRef.modify (fun arr => arr.push {
                          hypName := newHypName
                          hypType := hypTypeExpr
                          hypTypeStr := hypTypeStr
                          hypTypeRaw := hypTypeRaw
                          proofExpr := proofExpr
                          startPos := startPos.byteIdx
                          endPos := endPos.byteIdx
                          proofStart := proofBodyStart
                          lctx := declAfter.lctx
                          proofLCtx := declBefore.lctx
                          mctx := ti.mctxAfter
                          isPropType := hypIsProp
                        })

            -- Automation candidate detection (L3 exact? integrated)
            -- Skip structural wrapper kinds entirely
            -- --skip-phase1 disables tactic replacement but preserves dead code / L1 / L2 collection
            if !cfg.skipPhase1 && !isStructuralKind kind then
              if !ti.goalsBefore.isEmpty && ti.goalsAfter.isEmpty then
                -- Skip nodes too short to improve (min replacement is "rfl" = 3 bytes)
                let origSpan := (endPos.byteIdx - startPos.byteIdx)
                if origSpan > 3 then
                  -- Check global fold-phase time budget
                  let foldNowMs ← IO.monoMsNow
                  if foldNowMs - startTimeMs > maxFoldTimeMs then do
                    let exceeded ← foldBudgetExceededRef.get
                    if !exceeded then
                      foldBudgetExceededRef.set true
                      IO.println s!"[FOLD] Time budget exceeded ({(foldNowMs - startTimeMs) / 1000}s > {maxFoldTimeMs / 1000}s), skipping remaining automation checks"
                  else do
                  let mainGoal := ti.goalsBefore.head!
                  -- Track which tactics failed (for contrastive training data)
                  let failedTacticsRef ← IO.mkRef (#[] : Array (String × String × Nat))
                  -- First try deterministic automations (fast, highest quality)
                  -- Per-goal timeout is already inside checkAutomations (30s withTimeoutMs).
                  -- --complete-menu: all non-chosen menu candidates with outcome labels
                  let menuSibsRef ← IO.mkRef (#[] : Array (String × String × String × Nat))
                  let canShorten? ← if !cfg.completeMenu then
                      try
                        MetaM.run' (checkAutomations mainGoal ti origSpan failedTacticsRef)
                      catch _ => pure none
                    else do
                      let outs ← try MetaM.run' (checkAutomationsAll mainGoal ti origSpan cfg.menuTimeoutAll)
                                 catch _ => pure #[]
                      let origTextCM := fileData.extract ⟨startPos.byteIdx⟩ ⟨endPos.byteIdx⟩
                      let envCM ← getEnv
                      let wrapCM := fun (t : String) =>
                        if kind == "Lean.Parser.Term.byTactic" then s!"by {t}" else t
                      -- usable = valid AND strictly shorter than the original span
                      let usable := fun (o : MenuOutcome) => o.valid && o.tac.length < origSpan
                      let qualOk := fun (o : MenuOutcome) =>
                        cfg.noQualityGate || isQualityUpgrade origTextCM (wrapCM o.tac) (some envCM)
                      -- shortest usable+quality-passing candidate; ties → earliest in menu order
                      let mut best : Option MenuOutcome := none
                      for o in outs do
                        if usable o && qualOk o then
                          match best with
                          | none => best := some o
                          | some b => if o.tac.length < b.tac.length then best := some o
                      let bestIdx : Option Nat := best.map (·.menuIdx)
                      -- what first-success mode would pick: earliest usable entry
                      let v1Pick := outs.find? usable
                      let mut candJson : Array Lean.Json := #[]
                      for o in outs do
                        let q := usable o && qualOk o
                        let label :=
                          if o.skipped then "skipped_length"
                          else if bestIdx == some o.menuIdx then "chosen"
                          else if o.timedOut then "timeout"
                          else if !o.valid then "rejected_kernel"
                          else if !(o.tac.length < origSpan) then "rejected_length"
                          else if !q then "rejected_quality"
                          else "valid_not_chosen"
                        if !o.skipped && bestIdx != some o.menuIdx then
                          menuSibsRef.modify (·.push (wrapCM o.tac, label, o.err, o.wallMs))
                          if label == "rejected_kernel" || label == "timeout" then
                            failedTacticsRef.modify (·.push (o.tac, o.err, o.wallMs))
                        candJson := candJson.push (Lean.Json.mkObj
                          [("menu_idx", Lean.toJson o.menuIdx), ("menu_name", Lean.toJson o.menuName),
                           ("tac", Lean.toJson o.tac), ("final_tac", Lean.toJson (wrapCM o.tac)),
                           ("len", Lean.toJson o.tac.length), ("valid", Lean.toJson o.valid),
                           ("timed_out", Lean.toJson o.timedOut), ("skipped", Lean.toJson o.skipped),
                           ("quality_ok", Lean.toJson q), ("outcome", Lean.toJson label),
                           ("err", Lean.toJson o.err), ("wall_ms", Lean.toJson o.wallMs)])
                      let v1QualOk := match v1Pick with
                        | some o => qualOk o
                        | none => false
                      -- goal (pretty target + full goal state) for ranker training/eval
                      let (poolGPretty, poolGState) ← try
                          MetaM.run' (withMCtx ti.mctxBefore do
                            let mvarDecl ← mainGoal.getDecl
                            withLCtx mvarDecl.lctx mvarDecl.localInstances do
                              let ty ← instantiateMVars mvarDecl.type
                              let prettyTy ← Meta.ppExpr ty
                              let goalFmt ← Meta.ppGoal mainGoal
                              return (toString prettyTy, toString goalFmt))
                        catch _ => pure ("", "")
                      emitJsonLine "[MENU_POOL]"
                        [("file", Lean.toJson path),
                         ("goal_pretty", Lean.toJson poolGPretty),
                         ("goal_state", Lean.toJson poolGState),
                         ("start_byte", Lean.toJson startPos.byteIdx),
                         ("end_byte", Lean.toJson endPos.byteIdx),
                         ("kind", Lean.toJson kind),
                         ("orig_span", Lean.toJson origSpan),
                         ("original", Lean.toJson origTextCM),
                         ("chosen_idx", match bestIdx with | some i => Lean.toJson i | none => Lean.Json.null),
                         ("chosen_tac", match best with | some b => Lean.toJson (wrapCM b.tac) | none => Lean.Json.null),
                         ("v1_pick_idx", match v1Pick with | some o => Lean.toJson o.menuIdx | none => Lean.Json.null),
                         ("v1_pick_quality_ok", Lean.toJson v1QualOk),
                         ("candidates", Lean.Json.arr candJson)]
                      -- exact? fallback is only reached when no menu entry is usable
                      -- (valid and shorter), as in first-success mode.
                      if best.isNone && outs.any usable then
                        -- usable candidates exist but none passes the quality gate:
                        -- first-success mode also produces no edit here (its first usable
                        -- entry fails the gate). Signal "no edit, no exact?".
                        pure (some ("", "", 0))
                      else
                        pure (best.map fun b => (b.tac, b.goalType, b.termSize))
                  -- L3: If no deterministic automation found, try exact? (bounded)
                  let finalCandidate ← match canShorten? with
                    | some r => pure (some r)
                    | none => do
                      let eqCount ← exactQCountRef.get
                      let elapsedMs ← IO.monoMsNow
                      -- Skip exact? if budget exhausted or adaptive time exceeded
                      if eqCount ≥ MAX_EXACT_Q_ATTEMPTS || elapsedMs - startTimeMs > maxExactQTimeMs then
                        pure none
                      else
                        exactQCountRef.set (eqCount + 1)
                        try
                          MetaM.run' (checkExactQuestion mainGoal ti origSpan)
                        catch _ => pure none
                  if let some (shortTac, gt, ts) := finalCandidate.filter (fun (t, _, _) => t != "") then
                    let mut finalTac := shortTac
                    -- For byTactic nodes, the replacement must include `by `
                    if kind == "Lean.Parser.Term.byTactic" then
                      finalTac := s!"by {shortTac}"
                    -- Quality filter: only accept genuine upgrades in elegance
                    -- --no-quality-gate bypasses this for ablation experiments
                    let origText := fileData.extract ⟨startPos.byteIdx⟩ ⟨endPos.byteIdx⟩
                    let env ← getEnv
                    if cfg.noQualityGate || isQualityUpgrade origText finalTac (some env) then
                      -- Filter self-referential exact? suggestions: if the head
                      -- constant was defined in the current file (not in imports),
                      -- it may be the theorem being proved → reject.
                      let isSelfRef := Id.run do
                        let tac := shortTac.trim
                        if !tac.startsWith "exact " then return false
                        let afterExact := (tac.drop 6).trim
                        let headConst := afterExact.takeWhile (fun c =>
                          c != ' ' && c != '(' && c != ')' && c != ',' && c != '[' && c != ']')
                        if headConst.isEmpty then return false
                        let name := if headConst.startsWith "_root_." then headConst.drop 7 else headConst
                        importEnv.find? name.toName |>.isNone
                      if isSelfRef then
                        IO.println s!"[FILTER] self-referential exact?: `{shortTac}`"
                      if !isSelfRef then
                        -- Pretty-print the goal for training data
                        let (gPretty, gState) ← try
                          MetaM.run' (withMCtx ti.mctxBefore do
                            let mvarDecl ← mainGoal.getDecl
                            withLCtx mvarDecl.lctx mvarDecl.localInstances do
                              let ty ← instantiateMVars mvarDecl.type
                              let prettyTy ← Meta.ppExpr ty
                              let goalFmt ← Meta.ppGoal mainGoal
                              return (toString prettyTy, toString goalFmt))
                        catch _ => pure ("", "")
                        let failedTacs ← failedTacticsRef.get
                        let menuSibs ← menuSibsRef.get
                        candsRef.modify (fun l => {
                          startPos := startPos.byteIdx
                          endPos   := endPos.byteIdx
                          newTac   := finalTac
                          goalType := gt
                          goalPretty := gPretty
                          goalState := gState
                          kind     := kind
                          termSize := ts
                          isPropSafe := false
                          failedTactics := failedTacs
                          menuSiblings := menuSibs
                        } :: l)
          return acc
        | _ => return acc
  : CoreM Unit).run ctx state

  match ← eio.toBaseIO with
  | .error e => IO.println s!"[CRASH] {← e.toMessageData.toString}"
  | .ok _ => pure ()

  for p in unusedPos do
    IO.println s!"[UNUSED] {p}"

  let cands ← candsRef.get
  let deadRanges ← deadCodeRef.get
  let dedupMap ← dedupMapRef.get
  let dedupCandCount := cands.filter (fun c => c.kind == "L1_dedup") |>.length
  IO.println s!"[CANDIDATES] {cands.length} tactic candidates ({dedupCandCount} L1 dedup), {deadRanges.length} dead code blocks, {dedupMap.size} unique have-block signatures"

  /-
  Overlap resolution

  Problem: The InfoTree walk visits tactic nodes at every nesting level.
  For `have h := by simp [x]`, we get candidates at:
    - The `simp [x]` node (leaf tactic)
    - The `by simp [x]` node (byTactic wrapper)
  Both may succeed with `rfl`. But if we pick both, or pick the wrong one,
  we get `by rfl rfl` or `:= rfl rfl`.

  Solution: For overlapping candidates, keep only the one with the largest
  span (outermost). This ensures we replace the complete syntactic unit.
  Among equal-span candidates, prefer the one with greater byte savings.
  -/

  -- Sort by span size descending (largest first), then by savings descending
  let candsArr := cands.toArray.qsort (fun a b =>
    let spanA := a.endPos - a.startPos
    let spanB := b.endPos - b.startPos
    if spanA != spanB then spanA > spanB
    else a.savings > b.savings)

  -- Greedy non-overlapping selection: largest span first
  let mut selected : Array Candidate := #[]
  for c in candsArr do
    let mut overlaps := false
    for s in selected do
      if c.startPos < s.endPos && c.endPos > s.startPos then
        overlaps := true
        break
    -- Accept candidates that save bytes, or L1 dedup candidates (which improve
    -- mathematical elegance even at equal length)
    if !overlaps && (c.savings > 0 || c.kind == "L1_dedup") then
      selected := selected.push c

  IO.println s!"[SELECTED] {selected.size} non-overlapping replacements"

  -- Sort selected by position descending for safe bottom-up application
  let selectedDesc := selected.qsort (fun a b => a.startPos > b.startPos)

  -- Log all candidate applications
  for c in selectedDesc do
    let origSpan := fileData.extract ⟨c.startPos⟩ ⟨c.endPos⟩
    IO.println s!"[APPLYING] {c.startPos}-{c.endPos}: `{origSpan.take 60}` → `{c.newTac}` | KIND: {c.kind} | SAVINGS: {c.savings}"

  -- ═════════════════════════════════════════════════════════════════════
  -- Phase 1: Tactic replacement verification loop
  --
  -- All candidates go through verification : no Prop-safe shortcuts.
  -- Proof irrelevance guarantees individual correctness, but combined
  -- application can cause interactions (name shadowing, scope changes).
  -- Verifying everything together catches these interactions.
  -- --skip-phase1 skips the entire verification loop and discards
  -- any L1 dedup candidates collected during the fold.
  -- ═════════════════════════════════════════════════════════════════════

  let MAX_VERIFY_ROUNDS := 4
  let mut activeSet : Array Candidate := #[]
  let mut verified := true
  let mut prevErrCount : Nat := 999999
  let mut verifyRounds : String := "0"
  -- Track permanently excluded candidates (blamed in any round)
  let mut excludedPositions : Std.HashSet (Nat × Nat) := {}
  let mut verifyCands : Array Candidate := if cfg.skipPhase1 then #[] else selectedDesc

  if cfg.skipPhase1 then
    IO.println s!"[PHASE1] Skipped (--skip-phase1)"
  else
    IO.println s!"[PHASE1] {selectedDesc.size} candidates for verification"
    verified := selectedDesc.isEmpty
    verifyRounds := if selectedDesc.isEmpty then "0" else "?"

  -- ─────────────────────────────────────────────────────────────────────
  -- Phase 2a - block-local per-candidate advisory pre-check
  -- (opt-in via `--block-local`). For each candidate we re-elaborate ONLY
  -- the single top-level command containing it. This is
  -- informational: no candidate is ever dropped from `verifyCands` by
  -- this step. The subsequent Phase 2b batch verify is the only authority
  -- on what survives.
  --
  -- Why advisory and not a gate? L1-dedup candidates of the form
  -- `id1 0 1 ⟶ h₁` may only verify when the union of all sibling
  -- substitutions is applied: substituting one alone breaks the surrounding
  -- `linarith` / `ring_nf` argument list, so the proof fails individually
  -- but succeeds jointly. A single-candidate gate would drop such candidates.
  --
  -- The `fast=` count is the number of candidates whose single-command
  -- re-elaboration succeeded; the `deferred=` count is the rest. All
  -- candidates go through Phase 2b.
  -- ─────────────────────────────────────────────────────────────────────
  if !cfg.skipPhase1 && cfg.blockLocal && !verifyCands.isEmpty then do
    let total := verifyCands.size
    let blStartMs ← IO.monoMsNow
    let mut fastPass : Nat := 0
    let mut deferred : Nat := 0
    for c in verifyCands do
      let optData := applyReplacements fileData #[c]
      let errs ← verifyTextBlockLocal cmdCheckpoints importEnv headerEndPos
                  optData path c.startPos c.endPos
      if errs.isEmpty then
        fastPass := fastPass + 1
      else
        deferred := deferred + 1
    let blMs := (← IO.monoMsNow) - blStartMs
    IO.println s!"[PHASE2A_BLOCK_LOCAL] {total} candidates pre-checked (fast={fastPass}, deferred={deferred}) in {blMs}ms - all forwarded to batch verify"

  if !cfg.skipPhase1 then
   for round in [:MAX_VERIFY_ROUNDS] do
    if verifyCands.isEmpty then break
    -- Adaptive time guard: scale with elaboration complexity, not hardcoded
    let nowMs ← IO.monoMsNow
    if nowMs - startTimeMs > maxVerifyTimeMs then
      IO.println s!"[VERIFY] Time budget exceeded ({(nowMs - startTimeMs) / 1000}s > {maxVerifyTimeMs / 1000}s), stopping verification"
      break

    let testSet := verifyCands
    let optData := applyReplacements fileData testSet
    -- Use incremental verification: resume from the last checkpoint before
    -- the first modification, skipping re-elaboration of unmodified preamble.
    let firstModByte := testSet.foldl (fun acc c => min acc c.startPos) fileData.utf8ByteSize
    IO.println s!"[VERIFY] Round {round + 1}: testing {testSet.size} replacements (incremental from byte {firstModByte})..."
    let errors ← verifyTextIncremental cmdCheckpoints importEnv headerEndPos optData path firstModByte

    if errors.isEmpty then
      activeSet := testSet
      verified := true
      verifyRounds := s!"{round + 1}"
      IO.println s!"[VERIFIED] Round {round + 1}: all {testSet.size} tactic replacements compile"
      break

    IO.println s!"[VERIFY] Round {round + 1}: {errors.size} errors found, identifying culprits..."

    -- Map errors to candidate indices : only blame verifyCands (propSafe are unconditional)
    let optData' := optData  -- for the mapping function
    let badIndices := mapErrorsToCandidates verifyCands optData' errors

    -- Detect stuck state: same error count as last round means blame is wrong
    let stuck := errors.size == prevErrCount
    prevErrCount := errors.size

    if badIndices.isEmpty || stuck then
      -- Blame mapping failed or is stuck : force-cut a significant chunk
      let cutFraction := if stuck then 3 else 4  -- more aggressive when stuck
      let cutCount := max 1 (verifyCands.size / cutFraction)
      let bySavings := verifyCands.qsort (fun a b => a.savings > b.savings)
      let removed := bySavings[bySavings.size - cutCount:].toArray
      for c in removed do excludedPositions := excludedPositions.insert (c.startPos, c.endPos)
      verifyCands := bySavings[:bySavings.size - cutCount].toArray
      if stuck then
        IO.println s!"[VERIFY] Round {round + 1}: stuck ({errors.size} errors), force-cut {cutCount} lowest-savings entries → {verifyCands.size}"
      else
        IO.println s!"[VERIFY] Round {round + 1}: no direct mapping, cut {cutCount} lowest-savings entries → {verifyCands.size}"
    else
      let prev := verifyCands.size
      let removedCands := verifyCands.toList.zipIdx.filterMap (fun (c, i) =>
        if badIndices.contains i then some c else none)
      for c in removedCands do excludedPositions := excludedPositions.insert (c.startPos, c.endPos)
      verifyCands := verifyCands.toList.zipIdx.filterMap (fun (c, i) =>
        if badIndices.contains i then none else some c) |>.toArray
      let removed := prev - verifyCands.size
      IO.println s!"[VERIFY] Round {round + 1}: removed {removed} blamed entries, {verifyCands.size} remaining"

      -- Re-selection: fill gaps from the full candidate pool.
      if removed > 0 then
        for c in candsArr do
          -- Skip already selected or permanently excluded candidates
          let isSelected := verifyCands.any (fun s =>
            c.startPos == s.startPos && c.endPos == s.endPos)
          let isExcluded := excludedPositions.contains (c.startPos, c.endPos)
          if isSelected || isExcluded then continue
          -- Check overlap with currently active set
          let mut overlaps := false
          for s in verifyCands do
            if c.startPos < s.endPos && c.endPos > s.startPos then
              overlaps := true
              break
          if !overlaps && (c.savings > 0 || c.kind == "L1_dedup") then
            verifyCands := verifyCands.push c
        verifyCands := verifyCands.qsort (fun a b => a.startPos > b.startPos)
        IO.println s!"[VERIFY] Round {round + 1}: re-selected to {verifyCands.size} verify candidates"

      if removed == 0 then
        -- No progress : force-cut quarter
        let cutCount := max 1 (verifyCands.size / 4)
        let bySavings := verifyCands.qsort (fun a b => a.savings > b.savings)
        let forceCut := bySavings[bySavings.size - cutCount:].toArray
        for c in forceCut do excludedPositions := excludedPositions.insert (c.startPos, c.endPos)
        verifyCands := bySavings[:bySavings.size - cutCount].toArray
        IO.println s!"[VERIFY]   forced cut of {cutCount} entries"

  -- Merge surviving verifyCands into activeSet
  if !verified then
    activeSet := verifyCands
  -- Final attempt if main loop exhausted
  if !verified && !verifyCands.isEmpty then
    let optData := applyReplacements fileData activeSet
    let errors ← verifyText importEnv headerEndPos optData path
    if errors.isEmpty then
      verified := true
      verifyRounds := "final"
      IO.println s!"[VERIFIED] Final: {activeSet.size} tactic replacements compile"
    else
      for (eline, ecol, emsg) in errors do
        IO.println s!"[ERR] line {eline}:{ecol}: {emsg.take 100}"
      activeSet := #[]

  if !verified then
    verified := true
    if activeSet.isEmpty then
      IO.println "[VERIFIED] No surviving tactic replacements; proceeding with dead code / cleanup"
    else
      IO.println s!"[VERIFIED] {activeSet.size} replacements accepted; proceeding"

  traceMem "02_post_phase1" cfg
  -- ═════════════════════════════════════════════════════════════════════
  -- Phase 1.5: L2 Anti-unification pass (Expr-level near-duplicate detection)
  -- Runs after tactic replacement fold, before dead code removal.
  -- Operates on the post-fold proof state where tactics are already simplified.
  -- ═════════════════════════════════════════════════════════════════════

  let haveBlocks ← haveBlocksRef.get
  -- Sort by source position so template (first member) is always the earliest in source.
  -- This ensures the template's hypothesis is in scope for later members (same branch).
  let haveBlocks := haveBlocks.qsort (fun a b => a.startPos < b.startPos)
  let activeSetPreL2 := activeSet  -- save state before L2 modifications
  let mut l2Applied : Nat := 0
  let mut l2Detections : Nat := 0   -- total near-duplicates detected (including non-emitted)
  let mut l2Groups : Nat := 0       -- total anti-unification groups with ≥2 members
  let mut l2LemmaIdx : Nat := 0     -- counter for short lemma names (la0, la1, ...)
  let mut l2G3Rejected : Nat := 0   -- G3: lemma extractions vetoed because the
                                    -- unified body has ≥ as many free variables as the
                                    -- union of the originals (textual factoring, not
                                    -- a real generalization).
  -- Collect existing hypothesis names to prevent lemma name collisions
  let existingHypNames : Std.HashSet String := Id.run do
    let mut names : Std.HashSet String := {}
    for block in haveBlocks do
      names := names.insert block.hypName
    -- Also scan file text for any `la{N}` patterns already present
    let mut idx : Nat := 0
    while idx < 100 do
      let candidate := s!"la{idx}"
      if fileData.containsSubstr candidate then names := names.insert candidate
      else break  -- sequential: stop at first gap
      idx := idx + 1
    names
  let mut l2GroupCandSets : Array (Array Candidate) := #[]  -- per-group candidate tracking for verification fallback
  -- Detection-only training pairs: (arity, memberCount, hypTypeStr, reason, memberPositions)
  let mut l2DetectPairs : Array (Nat × Nat × String × String × Array (Nat × Nat)) := #[]

  if verified && haveBlocks.size >= 2 && !cfg.skipL2 then do
    -- Cap L2 complexity: skip if too many have-blocks (elaboration already expensive)
    if haveBlocks.size > 100 then
      IO.println s!"[L2_ANTIUN] Skipped: {haveBlocks.size} have-blocks exceeds cap of 100"
    else do
    IO.println s!"[L2_ANTIUN] Starting anti-unification on {haveBlocks.size} have-blocks"

    -- Step 3: Fingerprint each proof term using a coarse shape hash.
    -- We hash on (function-head, arity) rather than the full canonicalized expression.
    -- Near-duplicates differ in arguments but share the same function application structure.
    -- This gives us buckets of expressions that might anti-unify well.
    -- Fine-grained filtering happens in Step 4 (groupByAntiUnif).
    let mut fingerprints : Std.HashMap UInt64 (Array (Nat × HaveBlockInfo)) := {}
    for i in [:haveBlocks.size] do
      let block := haveBlocks[i]!
      -- Coarse fingerprint: hash the function head + number of app arguments
      -- For `f a b c`, this hashes (f, 3) regardless of a, b, c values
      let fn := block.proofExpr.getAppFn
      let nArgs := block.proofExpr.getAppNumArgs
      -- Also include the constructor name for non-app expressions
      let fp := hash (fn.ctorName, nArgs, fn.constName?.getD .anonymous)
      let bucket := fingerprints.getD fp #[]
      fingerprints := fingerprints.insert fp (bucket.push (i, block))

    -- Count buckets with potential duplicates
    let mut bucketCount : Nat := 0
    let mut pairCount : Nat := 0
    for (_, bucket) in fingerprints.toList do
      if bucket.size >= 2 then
        bucketCount := bucketCount + 1
        pairCount := pairCount + bucket.size

    IO.println s!"[L2_ANTIUN] {bucketCount} fingerprint buckets with {pairCount} candidate blocks"

    -- Step 4-7: For each bucket, run N-way anti-unification and emit replacements
    for (_, bucket) in fingerprints.toList do
      if bucket.size < 2 then continue
      let bucketBlocks := bucket.map (·.2)
      let groups := groupByAntiUnif bucketBlocks
      IO.println s!"[L2_ANTIUN] Bucket: {bucket.size} blocks → {groups.size} anti-unif groups"

      for group in groups do
        IO.println s!"[L2_ANTIUN]   Group: members={group.members.size}, arity={group.arity}"
        if group.members.size < 2 then continue
        l2Groups := l2Groups + 1
        l2Detections := l2Detections + group.members.size - 1  -- non-template members are detections
        -- Arity gate: skip overly generalized patterns
        if group.arity > 10 then
          IO.println s!"[L2_ANTIUN]   Skipped: arity {group.arity} > 10"
          continue

        let template := group.members[0]!
        IO.println s!"[L2_ANTIUN] Group: arity={group.arity}, members={group.members.size}, template={template.hypName}"

        -- Pre-computed during have-block collection: is the hypothesis type a Prop?
        -- If so, proof irrelevance makes any proof of the same Prop interchangeable,
        -- regardless of which specific sub-expressions differ in the proof terms.
        let isPropType := template.isPropType
        let mut groupEmitted := false  -- track if any L2 emission happened in this group
        let mut l2DetectReason := ""   -- reason for non-emission (for detection training pairs)

        -- For each non-template member, attempt emission
        for mIdx in [1:group.members.size] do
          let member := group.members[mIdx]!
          -- Scoping check: a hypothesis named `template.hypName` exists in the
          -- member's pre-have local context and its type is definitionally equal
          -- to the member's expected hypothesis type. This is the precise
          -- soundness condition for replacing the member's proof with the bare
          -- identifier `template.hypName`: the kernel will resolve the name in
          -- `member.proofLCtx`, infer its type, and check it against `member.hypType`.
          --
          -- Important: we compare `ldecl.type` against `member.hypType` (not against
          -- `template`'s type). The soundness condition is about the member's goal,
          -- and writing it that way removes any reliance on syntactic type-string
          -- equality.
          --
          -- Use `proofLCtx` (pre-have), not `lctx` (post-have): `lctx` includes
          -- the member's own just-defined hypothesis, which collides on userName
          -- when both blocks are named `h₇` and produces a false positive.
          let templateFVarOk ← try
            let eio := (MetaM.run' (withMCtx member.mctx do
            withLCtx member.proofLCtx #[] do
              match member.proofLCtx.findFromUserName? template.hypName.toName with
              | some ldecl =>
                -- Belt-and-suspenders: same FVarId is a fast accept; otherwise
                -- require defEq against the member's expected type.
                match template.lctx.findFromUserName? template.hypName.toName with
                | some tldecl =>
                  if ldecl.fvarId == tldecl.fvarId then return true
                  isDefEq ldecl.type member.hypType
                | none => isDefEq ldecl.type member.hypType
              | none => return false)).run ctx state
            match ← eio.toBaseIO with
            | .ok (r, _) => pure r
            | .error _ => pure false
          catch _ => pure false

          -- Prop-safe matching uses RAW type strings (actual variable names)
          -- to avoid false matches from canonicalization (e.g., |r*a+s*b-e| vs |r*c+s*d-f|
          -- would match after _lvN canonicalization but are different types).
          let sameType := template.hypTypeRaw == member.hypTypeRaw && !template.hypTypeRaw.isEmpty
          let proofText := fileData.extract ⟨member.proofStart⟩ ⟨member.endPos⟩
          let isBy := proofText.trim.startsWith "by " || proofText.trim.startsWith "by\n"
          let mut emitted := false

          -- Path A: Arity 0 (identical proofs) + template in scope → exact
          if group.arity == 0 && templateFVarOk then
            let replacement := if isBy then s!"by exact {template.hypName}" else template.hypName
            if replacement.length < proofText.trim.length then
              -- Preempt overlapping Phase 1 candidates if L2 saves more bytes overall
              let overlapping := activeSet.filter (fun c =>
                member.proofStart < c.endPos && member.endPos > c.startPos)
              let phase1Savings := overlapping.foldl (fun acc c => acc + c.savings) (0 : Int)
              let l2Savings : Int := (proofText.trim.length : Int) - replacement.length
              if overlapping.isEmpty || l2Savings > phase1Savings then
                if !overlapping.isEmpty then
                  activeSet := activeSet.filter (fun c =>
                    !(member.proofStart < c.endPos && member.endPos > c.startPos))
                activeSet := activeSet.push {
                  startPos := member.proofStart
                  endPos := member.endPos
                  newTac := replacement
                  goalType := template.hypName
                  kind := "L2_antiun_exact"
                  termSize := 1
                  isPropSafe := true
                }
                l2Applied := l2Applied + 1
                emitted := true
                groupEmitted := true
                IO.println s!"[L2_EMIT] {member.proofStart}-{member.endPos}: exact dup → `{replacement}`"

          -- Path B: Same Prop type → exact (only when template hypothesis is in scope)
          -- Proof irrelevance permits term swaps for the same Prop, but it does not
          -- license `by assumption` (which requires a hypothesis of that type to be
          -- in scope at the call site -> an unverified assumption here).
          -- We require the template hypothesis to be in scope, and verify below.
          if !emitted && sameType && isPropType && templateFVarOk then
            let replacement := if isBy then s!"by exact {template.hypName}" else template.hypName
            if replacement.length < proofText.trim.length then
              let overlapping := activeSet.filter (fun c =>
                member.proofStart < c.endPos && member.endPos > c.startPos)
              let phase1Savings := overlapping.foldl (fun acc c => acc + c.savings) (0 : Int)
              let l2Savings : Int := (proofText.trim.length : Int) - replacement.length
              if overlapping.isEmpty || l2Savings > phase1Savings then
                if !overlapping.isEmpty then
                  activeSet := activeSet.filter (fun c =>
                    !(member.proofStart < c.endPos && member.endPos > c.startPos))
                activeSet := activeSet.push {
                  startPos := member.proofStart
                  endPos := member.endPos
                  newTac := replacement
                  goalType := s!"L2_arity{group.arity}_prop"
                  kind := "L2_antiun_prop"
                  termSize := 1
                  isPropSafe := true
                }
                l2Applied := l2Applied + 1
                emitted := true
                groupEmitted := true
                IO.println s!"[L2_EMIT] {member.proofStart}-{member.endPos}: Prop-safe → `{replacement}`"

          if !emitted && group.arity > 8 then
            l2DetectReason := "arity_too_high"
            IO.println s!"[L2_DETECT] arity-{group.arity} near-dup (arity > 8, detection only)"

          -- Lemma extraction for arity 0-8:
          -- Runs when per-member paths (exact/assumption) did not fire.
          -- Generates a local helper lemma and call sites for all members.
          -- Runs once per group (gated by mIdx == 1).
          --
          -- For arity 0: no parameters, just a shared proof at a common scope.
          -- For arity 1-8:
          --   (A) Expr-level: all template diffs are printable (FVars or closed terms)
          --       → use ppExpr to render params and build kernel-correct lemma
          --   (B) Text-level fallback: source tactic texts differ only at identifier tokens
          --       → use the differing tokens as parameters directly from source text
          if group.arity ≤ 8 && !emitted && mIdx == 1 then
            let result := antiUnifyExprs template.proofExpr group.members[1]!.proofExpr

            -- Accept any closed sub-expression as a diff parameter,
            -- not just FVars. Tactic-generated proofs (omega, simp, ring) produce
            -- .const/.app/.lit diffs that are printable via ppExpr.
            let allPrintable := result.diffs.all (fun (_, e1Sub, e2Sub) =>
              !e1Sub.hasLooseBVars && !e2Sub.hasLooseBVars)

            let templateProofText := fileData.extract ⟨template.proofStart⟩ ⟨template.endPos⟩
            let tooShort := group.members.size == 2 && templateProofText.trim.length < 8

            if tooShort then
              l2DetectReason := "proof_too_short"
              IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): proof too short for lemma"
            else do
            -- ──────────────────────────────────────────────────────────────
            -- Try text-level diff if Expr-level allFVars fails.
            -- For tactic-generated proofs (omega, simp, ring, nlinarith...),
            -- the elaborated Exprs have lambda/forall/lit diffs that are not
            -- FVars. But the source tactic text may differ only at identifier
            -- tokens (variable names). Text-level diffing catches these.
            -- ──────────────────────────────────────────────────────────────
            let mem1ProofText := fileData.extract ⟨group.members[1]!.proofStart⟩ ⟨group.members[1]!.endPos⟩
            let textDiffResult := textDiff templateProofText.trim mem1ProofText.trim

            -- Determine which path to use:
            -- Expr-level (allPrintable) is preferred when available (more precise).
            -- Text-level is the fallback.
            let useExprLevel := allPrintable
            let useTextLevel := !allPrintable && textDiffResult.isSome &&
              textDiffResult.get!.size ≤ 8 && textDiffResult.get!.size ≥ 1

            if useExprLevel then do
              -- ═══════ PATH A: Expr-level lemma extraction ═══════
              -- Use kernel-level abstraction (mkLambdaFVars/mkForallFVars for FVar
              -- diffs) or manual ∀/fun abstraction (for non-FVar printable diffs)
              -- to produce a mathematically correct lemma.
              -- Meta.check guards against invalid abstractions.
              -- ppExpr produces a verified term-mode body; source-text fallback also added.
              let exprAbstraction : Except String (String × String × Array String) ← try
                let eio := (MetaM.run' (withMCtx template.mctx do
                withLCtx template.proofLCtx #[] do
                  let mut diffFVars : Array Expr := #[]
                  let mut paramOrigNames : Array String := #[]
                  let mut nonFVarDiffs : Array (Nat × Expr) := #[]  -- (index, e1Sub) for non-FVar diffs
                  for ((_, e1Sub, _), idx) in result.diffs.toList.zipIdx do
                    if e1Sub.hasLooseBVars then return Except.error "loose_bvars"
                    if e1Sub.isFVar then
                      -- FVar diff: use mkForallFVars/mkLambdaFVars for kernel-correct abstraction
                      -- Skip let-bounded FVars (from set/let) : mkForallFVars produces
                      -- letE instead of ∀, which is not a meaningful parametric lemma.
                      if let some ldecl := template.proofLCtx.find? e1Sub.fvarId! then
                        if ldecl.isLet then return Except.error "let_bound_fvar"
                      else if let some ldecl := template.lctx.find? e1Sub.fvarId! then
                        if ldecl.isLet then return Except.error "let_bound_fvar"
                      diffFVars := diffFVars.push e1Sub
                      let origName? := match template.proofLCtx.find? e1Sub.fvarId! with
                        | some ldecl => some ldecl.userName.toString
                        | none => match template.lctx.find? e1Sub.fvarId! with
                          | some ldecl => some ldecl.userName.toString
                          | none => none
                      let some origName := origName? | return Except.error "fvar_no_user_name"
                      paramOrigNames := paramOrigNames.push origName
                    else
                      -- Non-FVar diff (const, app, lit, etc.): use ppExpr for name,
                      -- inferType for the parameter type. These are common in
                      -- tactic-generated proofs (omega, simp, ring, norm_num).
                      nonFVarDiffs := nonFVarDiffs.push (idx, e1Sub)
                      let fmt ← Meta.ppExpr e1Sub
                      paramOrigNames := paramOrigNames.push (toString fmt)
                  -- Sort FVar diffs by their declaration order in proofLCtx to ensure
                  -- dependent types are abstracted in the correct order (if B depends
                  -- on A, A must come before B in the forall/lambda binder).
                  if diffFVars.size > 1 then
                    diffFVars := diffFVars.qsort (fun a b =>
                      let aIdx := match template.proofLCtx.find? a.fvarId! with
                        | some d => d.index | none => 0
                      let bIdx := match template.proofLCtx.find? b.fvarId! with
                        | some d => d.index | none => 0
                      aIdx < bIdx)
                  let proofExpr ← instantiateMVars template.proofExpr
                  let hypType ← instantiateMVars template.hypType
                  -- G3 metric: free-variable count of the union of the
                  -- N original member proof expressions. A real generalization
                  -- strictly drops this count after parameter abstraction below.
                  let mut unionFVarSet : Lean.CollectFVars.State := {}
                  for m in group.members do
                    let mProof ← instantiateMVars m.proofExpr
                    unionFVarSet := Lean.collectFVars unionFVarSet mProof
                  let unionFVarCount := unionFVarSet.fvarSet.size
                  if nonFVarDiffs.isEmpty then
                    -- Pure FVar case: use mkForallFVars/mkLambdaFVars (kernel-correct)
                    let abstractedType ← mkForallFVars diffFVars hypType
                    let abstractedProof ← mkLambdaFVars diffFVars proofExpr
                    Meta.check abstractedProof
                    let proofType ← inferType abstractedProof
                    unless ← isDefEq proofType abstractedType do return Except.error "defeq_failed"
                    let unifiedFVarCount := (Lean.collectFVars {} abstractedProof).fvarSet.size
                    -- G3 gate: textual factoring (no real generalization) ⇒ skip.
                    if !cfg.noG3 && unifiedFVarCount >= unionFVarCount then
                      return Except.error s!"g3_no_generalization_{unifiedFVarCount}ge{unionFVarCount}"
                    let typeFmt ← Meta.ppExpr abstractedType
                    let proofFmt ← Meta.ppExpr abstractedProof
                    return Except.ok (toString typeFmt, toString proofFmt, paramOrigNames)
                  else if diffFVars.isEmpty then
                    -- Pure non-FVar case: create fresh FVars for each diff sub-expression,
                    -- substitute them into the proof/type, then use mkForallFVars/mkLambdaFVars.
                    -- This handles tactic-generated proofs where diffs are .const/.app/.lit nodes.
                    let mut allFreshFVars : Array Expr := #[]
                    let mut lctx' := template.proofLCtx
                    let mut proofExpr' := proofExpr
                    let mut hypType' := hypType
                    for ((_, e1Sub), i) in nonFVarDiffs.toList.zipIdx do
                      let ty ← inferType e1Sub
                      let fvarId ← mkFreshFVarId
                      let userName := s!"x_{i}".toName
                      let fv := Lean.mkFVar fvarId
                      lctx' := lctx'.mkLocalDecl fvarId userName ty
                      proofExpr' := proofExpr'.replace (fun e => if e == e1Sub then some fv else none)
                      hypType' := hypType'.replace (fun e => if e == e1Sub then some fv else none)
                      allFreshFVars := allFreshFVars.push fv
                    withLCtx lctx' #[] do
                      let abstractedType ← mkForallFVars allFreshFVars hypType'
                      let abstractedProof ← mkLambdaFVars allFreshFVars proofExpr'
                      Meta.check abstractedProof
                      let proofType ← inferType abstractedProof
                      unless ← isDefEq proofType abstractedType do return Except.error "defeq_failed"
                      let unifiedFVarCount := (Lean.collectFVars {} abstractedProof).fvarSet.size
                      -- G3 gate: in the pure non-FVar case (constant/lit diffs)
                      -- this almost always vetoes, since constants don't contribute to
                      -- FVar counts and abstraction over them yields no new generalization.
                      if !cfg.noG3 && unifiedFVarCount >= unionFVarCount then
                        return Except.error s!"g3_no_generalization_{unifiedFVarCount}ge{unionFVarCount}"
                      let typeFmt ← Meta.ppExpr abstractedType
                      let proofFmt ← Meta.ppExpr abstractedProof
                      return Except.ok (toString typeFmt, toString proofFmt, paramOrigNames)
                  else
                    -- Mixed case: both FVar and non-FVar diffs.
                    -- Fall back to text-level for mixed cases (too complex for kernel abstraction).
                    return Except.error "mixed_diffs"
                )).run ctx state
                match ← eio.toBaseIO with
                | .ok (r, _) => pure r
                | .error e =>
                  let msg ← e.toMessageData.toString
                  pure (Except.error s!"meta_exception_{msg}")
              catch _ => pure (Except.error "outer_exception")

              match exprAbstraction with
              | .error reason =>
                if reason.startsWith "g3_" then
                  l2G3Rejected := l2G3Rejected + 1
                  l2DetectReason := reason
                  IO.println s!"[L2_G3] arity-{group.arity} group ({group.members.size} members): vetoed - {reason}"
                else
                  l2DetectReason := reason
                  IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): Expr abstraction failed ({reason})"
              | .ok (exprTypeStr, exprProofStr, paramOrigNames) =>
                -- Find a collision-free lemma name
                while existingHypNames.contains s!"la{l2LemmaIdx}" do
                  l2LemmaIdx := l2LemmaIdx + 1
                let lemmaName := s!"la{l2LemmaIdx}"
                l2LemmaIdx := l2LemmaIdx + 1

                -- Build lemma body: prefer ppExpr (kernel-correct) when compact;
                -- fall back to source-text tactic body when ppExpr produces large kernel terms.
                -- Meta.check + isDefEq above guarantee the abstraction is mathematically valid.
                -- Per-group verification catches any source-text scoping failures.
                let textBody := Id.run do
                  if paramOrigNames.isEmpty then
                    -- Arity-0: no parameters, body is unchanged template proof
                    return templateProofText.trim
                  let mut body := templateProofText.trim
                  for (origName, i) in paramOrigNames.toList.zipIdx do
                    body := replaceWord body origName s!"x_{i}"
                  let bodyIsTactic := body.startsWith "by " || body.startsWith "by\n"
                  if bodyIsTactic then
                    let afterBy := (body.drop 3).trimLeft
                    let introNames := String.intercalate " " (paramOrigNames.toList.zipIdx.map (fun (_, i) => s!"x_{i}"))
                    return s!"by intro {introNames}; {afterBy}"
                  let introNames := String.intercalate " " (paramOrigNames.toList.zipIdx.map (fun (_, i) => s!"x_{i}"))
                  return s!"fun {introNames} => {body}"
                let proofBodyStr := if exprProofStr.length ≤ textBody.length then exprProofStr else textBody
                let haveLine := s!"have {lemmaName} : {exprTypeStr} := {proofBodyStr}"
                let indent := lineIndent fileData (findLineStart fileData template.startPos)
                let indentStr := String.mk (List.replicate indent ' ')
                let lemmaInsert := s!"{indentStr}{haveLine}\n"

                let mut callCandidates : Array Candidate := #[]

                -- Template call site
                -- Parenthesize args that contain spaces (complex non-FVar terms)
                let paren (s : String) : String := if s.any (· == ' ') then s!"({s})" else s
                let templateCall := if paramOrigNames.isEmpty then lemmaName
                  else s!"{lemmaName} {String.intercalate " " (paramOrigNames.toList.map paren)}"
                let templateCallTac := if templateProofText.trim.startsWith "by " || templateProofText.trim.startsWith "by\n"
                  then s!"by exact {templateCall}" else templateCall
                -- Include template call even if slightly longer (aggregate profitability check later)
                if templateCallTac.length ≤ templateProofText.trim.length + 10 then
                  callCandidates := callCandidates.push {
                    startPos := template.proofStart
                    endPos := template.endPos
                    newTac := templateCallTac
                    goalType := s!"L2_arity{group.arity}_lemma"
                    kind := "L2_antiun_lemma"
                    termSize := 1
                  }

                -- Member call sites (Expr-level arg resolution)
                for mIdx' in [1:group.members.size] do
                  let mem := group.members[mIdx']!
                  let memDiffs := if mIdx' - 1 < group.memberDiffs.size
                    then group.memberDiffs[mIdx' - 1]!
                    else #[]
                  let hasLoose := memDiffs.any (fun (_, _, e2Sub) => e2Sub.hasLooseBVars)
                  let hasMissingFVars := memDiffs.any (fun (_, _, e2Sub) =>
                    let fvState := Lean.collectFVars {} e2Sub
                    fvState.fvarSet.any (fun fvId =>
                      !mem.proofLCtx.contains fvId && !mem.lctx.contains fvId))
                  let memArgs ← if hasLoose || hasMissingFVars then pure none
                  else try
                    let eio := (MetaM.run' (withMCtx mem.mctx do
                    withLCtx mem.proofLCtx #[] do
                      let mut args : Array String := #[]
                      for (_, _, e2Sub) in memDiffs do
                        if e2Sub.isFVar then
                          match mem.proofLCtx.find? e2Sub.fvarId! with
                          | some ldecl => args := args.push ldecl.userName.toString
                          | none =>
                            match mem.lctx.find? e2Sub.fvarId! with
                            | some ldecl => args := args.push ldecl.userName.toString
                            | none =>
                              let fmt ← Meta.ppExpr e2Sub
                              args := args.push (toString fmt)
                        else
                          let fmt ← Meta.ppExpr e2Sub
                          args := args.push (toString fmt)
                      return args)).run ctx state
                    match ← eio.toBaseIO with
                    | .ok (r, _) => pure (some r)
                    | .error _ => pure none
                  catch _ => pure none
                  match memArgs with
                  | some args =>
                    let memProofText := fileData.extract ⟨mem.proofStart⟩ ⟨mem.endPos⟩
                    let isBy' := memProofText.trim.startsWith "by " || memProofText.trim.startsWith "by\n"
                    let callText := if args.isEmpty then lemmaName
                      else s!"{lemmaName} {String.intercalate " " (args.toList.map paren)}"
                    let replacement' := if isBy' then s!"by exact {callText}" else callText
                    -- Include call site even if slightly longer (aggregate profitability check later)
                    if replacement'.length ≤ memProofText.trim.length + 10 then
                      let overlapping' := activeSet.filter (fun c =>
                        mem.proofStart < c.endPos && mem.endPos > c.startPos)
                      let p1Sav := overlapping'.foldl (fun acc c => acc + c.savings) (0 : Int)
                      let l2Sav : Int := (memProofText.trim.length : Int) - replacement'.length
                      if overlapping'.isEmpty || l2Sav > p1Sav then
                        callCandidates := callCandidates.push {
                          startPos := mem.proofStart
                          endPos := mem.endPos
                          newTac := replacement'
                          goalType := s!"L2_arity{group.arity}_lemma"
                          kind := "L2_antiun_lemma"
                          termSize := 1
                        }
                  | none =>
                    pure ()

                if callCandidates.size >= 2 then
                  let totalSavings := callCandidates.foldl (fun acc c => acc + c.savings) (0 : Int)
                  if totalSavings > (lemmaInsert.length : Int) then
                    for cc in callCandidates do
                      activeSet := activeSet.filter (fun c =>
                        !(cc.startPos < c.endPos && cc.endPos > c.startPos))
                    let insertPos := findLineStart fileData template.startPos
                    let insertCand : Candidate := {
                      startPos := insertPos, endPos := insertPos,
                      newTac := lemmaInsert, goalType := "L2_lemma_def",
                      kind := "L2_antiun_lemma_def", termSize := 0
                    }
                    activeSet := activeSet.push insertCand
                    for cc in callCandidates do
                      activeSet := activeSet.push cc
                    l2GroupCandSets := l2GroupCandSets.push (#[insertCand] ++ callCandidates)
                    l2Applied := l2Applied + callCandidates.size
                    groupEmitted := true
                    IO.println s!"[L2_LEMMA] Extracted `{lemmaName}`: {group.arity} params, {callCandidates.size} call sites, ~{totalSavings - (lemmaInsert.length : Int)} bytes saved"
                    IO.println s!"[L2_LEMMA_DEF] {lemmaInsert.trim}"
                    for cc in callCandidates do
                      IO.println s!"[L2_LEMMA_CALL] {cc.startPos}-{cc.endPos}: `{cc.newTac}`"
                  else
                    l2DetectReason := "expr_not_profitable"
                    IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): expr-level lemma not profitable"
                else
                  l2DetectReason := s!"expr_insufficient_calls_{callCandidates.size}of{group.members.size}"
                  IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): {callCandidates.size}/{group.members.size} call sites"

            else if useTextLevel then do
              -- ═══════ PATH B: Text-level lemma extraction (fallback) ═══════
              -- The elaborated proof terms have non-FVar diffs (lambdas, foralls, lits
              -- from automation tactics), but the source text differs only at identifier
              -- tokens. Build the lemma entirely from source text.
              let tDiffs := textDiffResult.get!
              IO.println s!"[L2_TEXT] Attempting text-level extraction: {tDiffs.size} text diffs"

              -- Build parameter info from text diffs.
              -- For type inference, fall back to the hypothesis type of the template
              -- (we cannot easily infer types of arbitrary source identifiers).
              -- Use a catch-all approach: infer types from the goal context.
              let templateRetTypeStr ← try
                let eio := (MetaM.run' (withMCtx template.mctx do
                withLCtx template.proofLCtx #[] do
                  let retTy ← instantiateMVars template.hypType
                  let retFmt ← Meta.ppExpr retTy
                  return toString retFmt)).run ctx state
                match ← eio.toBaseIO with
                | .ok (r, _) => pure (some r)
                | .error _ => pure none
              catch _ => pure none

              match templateRetTypeStr with
              | some retTy => do
                -- Infer types for each differing word from the proof local context
                let mut params : Array (String × String × String) := #[]  -- (paramName, typeStr, origWord)
                let mut allTyped := true
                for ((_, tWord, _), i) in tDiffs.toList.zipIdx do
                  -- Try to find the identifier in the local context for type inference
                  let tyStr ← try
                    let eio := (MetaM.run' (withMCtx template.mctx do
                    withLCtx template.proofLCtx #[] do
                      -- Look up the word as a local hypothesis
                      if let some ldecl := template.proofLCtx.findFromUserName? tWord.toName then
                        let tyFmt ← Meta.ppExpr ldecl.type
                        return some (toString tyFmt)
                      else if let some ldecl := template.lctx.findFromUserName? tWord.toName then
                        let tyFmt ← Meta.ppExpr ldecl.type
                        return some (toString tyFmt)
                      else
                        -- Try resolving as a namespace-qualified constant from the environment
                        let env ← getEnv
                        if let some cinfo := env.find? tWord.toName then
                          let tyFmt ← Meta.ppExpr cinfo.type
                          return some (toString tyFmt)
                        else
                          return none)).run ctx state
                    match ← eio.toBaseIO with
                    | .ok (r, _) => pure r
                    | .error _ => pure none
                  catch _ => pure none
                  match tyStr with
                  | some ts => params := params.push (s!"x_{i}", ts, tWord)
                  | none => allTyped := false; break

                if allTyped && !params.isEmpty then do
                  -- Build lemma body by text substitution
                  let mut lemmaBody := templateProofText.trim
                  let mut paramRetTy := retTy
                  for (paramName, _, origWord) in params do
                    lemmaBody := replaceWord lemmaBody origWord paramName
                    paramRetTy := replaceWord paramRetTy origWord paramName

                  -- Find a collision-free lemma name
                  while existingHypNames.contains s!"la{l2LemmaIdx}" do
                    l2LemmaIdx := l2LemmaIdx + 1
                  let lemmaName := s!"la{l2LemmaIdx}"
                  l2LemmaIdx := l2LemmaIdx + 1
                  let paramDecls := String.intercalate " " (params.toList.map fun (pn, pt, _) => s!"({pn} : {pt})")
                  let introNames := String.intercalate " " (params.toList.map fun (pn, _, _) => pn)

                  let bodyIsTactic := lemmaBody.startsWith "by " || lemmaBody.startsWith "by\n"
                  let lemmaBodyText := if bodyIsTactic then
                    let afterBy := (lemmaBody.drop 3).trimLeft
                    s!"by intro {introNames}; {afterBy}"
                  else
                    s!"fun {introNames} => {lemmaBody}"

                  let haveLine := s!"have {lemmaName} : ∀ {paramDecls}, {paramRetTy} := {lemmaBodyText}"
                  let indent := lineIndent fileData (findLineStart fileData template.startPos)
                  let indentStr := String.mk (List.replicate indent ' ')
                  let lemmaInsert := s!"{indentStr}{haveLine}\n"

                  -- Generate call sites
                  let mut callCandidates : Array Candidate := #[]

                  -- Template call site
                  let templateArgs := params.toList.map fun (_, _, origWord) => origWord
                  let templateCall := s!"{lemmaName} {String.intercalate " " templateArgs}"
                  let templateCallTac := if templateProofText.trim.startsWith "by " || templateProofText.trim.startsWith "by\n"
                    then s!"by exact {templateCall}" else templateCall
                  if templateCallTac.length < templateProofText.trim.length then
                    callCandidates := callCandidates.push {
                      startPos := template.proofStart
                      endPos := template.endPos
                      newTac := templateCallTac
                      goalType := s!"L2_arity{tDiffs.size}_text"
                      kind := "L2_antiun_text_lemma"
                      termSize := 1
                    }

                  -- Member call sites from text diffs
                  for mIdx' in [1:group.members.size] do
                    let mem := group.members[mIdx']!
                    let memProofText := fileData.extract ⟨mem.proofStart⟩ ⟨mem.endPos⟩
                    let memDiffR := textDiff templateProofText.trim memProofText.trim
                    match memDiffR with
                    | some memDiffs =>
                      if memDiffs.size == tDiffs.size then
                        let memArgs := memDiffs.toList.map fun (_, _, mWord) => mWord
                        let isBy' := memProofText.trim.startsWith "by " || memProofText.trim.startsWith "by\n"
                        let callText := s!"{lemmaName} {String.intercalate " " memArgs}"
                        let replacement' := if isBy' then s!"by exact {callText}" else callText
                        if replacement'.length < memProofText.trim.length then
                          let overlapping' := activeSet.filter (fun c =>
                            mem.proofStart < c.endPos && mem.endPos > c.startPos)
                          let p1Sav := overlapping'.foldl (fun acc c => acc + c.savings) (0 : Int)
                          let l2Sav : Int := (memProofText.trim.length : Int) - replacement'.length
                          if overlapping'.isEmpty || l2Sav > p1Sav then
                            callCandidates := callCandidates.push {
                              startPos := mem.proofStart
                              endPos := mem.endPos
                              newTac := replacement'
                              goalType := s!"L2_arity{tDiffs.size}_text"
                              kind := "L2_antiun_text_lemma"
                              termSize := 1
                            }
                    | none => pure ()

                  if callCandidates.size >= 2 then
                    let totalSavings := callCandidates.foldl (fun acc c => acc + c.savings) (0 : Int)
                    if totalSavings > (lemmaInsert.length : Int) then
                      for cc in callCandidates do
                        activeSet := activeSet.filter (fun c =>
                          !(cc.startPos < c.endPos && cc.endPos > c.startPos))
                      let insertPos := findLineStart fileData template.startPos
                      let insertCand : Candidate := {
                        startPos := insertPos, endPos := insertPos,
                        newTac := lemmaInsert, goalType := "L2_lemma_def",
                        kind := "L2_antiun_text_lemma_def", termSize := 0
                      }
                      activeSet := activeSet.push insertCand
                      for cc in callCandidates do
                        activeSet := activeSet.push cc
                      l2GroupCandSets := l2GroupCandSets.push (#[insertCand] ++ callCandidates)
                      l2Applied := l2Applied + callCandidates.size
                      groupEmitted := true
                      IO.println s!"[L2_LEMMA] Text-level `{lemmaName}`: {tDiffs.size} params, {callCandidates.size} call sites, ~{totalSavings - (lemmaInsert.length : Int)} bytes saved"
                    else
                      l2DetectReason := "text_not_profitable"
                      IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): text-level lemma not profitable"
                  else
                    l2DetectReason := s!"text_insufficient_calls_{callCandidates.size}of{group.members.size}"
                    IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): {callCandidates.size}/{group.members.size} text-level call sites"
                else
                  l2DetectReason := "text_type_inference_failed"
                  IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): text-level type inference failed"
              | none =>
                l2DetectReason := "return_type_pp_failed"
                IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): return type pp failed"
            else
              l2DetectReason := "non_extractable_diffs"
              IO.println s!"[L2_DETECT] arity-{group.arity} group ({group.members.size} members): non-extractable diffs"

        -- Collect detection-only training pair if this group had detections but no emission
        if !groupEmitted && group.members.size >= 2 then
          let memberPositions := group.members.map (fun m => (m.proofStart, m.endPos))
          l2DetectPairs := l2DetectPairs.push (group.arity, group.members.size, template.hypTypeStr, l2DetectReason, memberPositions)

    -- If we added L2 candidates, always verify the combined set with the kernel.
    if l2Applied > 0 then do
        IO.println s!"[L2_ANTIUN] {l2Applied} L2 replacements proposed, verifying combined set..."
        let optData := applyReplacements fileData activeSet
        let firstModByte := activeSet.foldl (fun acc c => min acc c.startPos) fileData.utf8ByteSize
        let errors ← verifyTextIncremental cmdCheckpoints importEnv headerEndPos optData path firstModByte
        if errors.isEmpty then
          IO.println s!"[L2_ANTIUN] All {l2Applied} L2 replacements verified"
        else do
          IO.println s!"[L2_ANTIUN] {errors.size} errors in combined set : trying per-group verification..."
          -- Restore pre-L2 activeSet and try each group independently
          activeSet := activeSetPreL2
          l2Applied := 0
          for grpCands in l2GroupCandSets do
            -- Remove Phase 1 candidates that overlap with this group's candidates
            let mut testSet := activeSet
            for cc in grpCands do
              testSet := testSet.filter (fun c =>
                !(cc.startPos < c.endPos && cc.endPos > c.startPos))
            testSet := testSet ++ grpCands
            let testText := applyReplacements fileData testSet
            let firstMod := testSet.foldl (fun acc c => min acc c.startPos) fileData.utf8ByteSize
            let grpErrors ← verifyTextIncremental cmdCheckpoints importEnv headerEndPos testText path firstMod
            if grpErrors.isEmpty then
              -- Accept this group permanently
              for cc in grpCands do
                activeSet := activeSet.filter (fun c =>
                  !(cc.startPos < c.endPos && cc.endPos > c.startPos))
              for gc in grpCands do activeSet := activeSet.push gc
              let emissions := grpCands.filter (fun c => !c.kind.endsWith "_def") |>.size
              l2Applied := l2Applied + emissions
              IO.println s!"[L2_ANTIUN]   L2 group verified ({emissions} replacements)"
            else
              IO.println s!"[L2_ANTIUN]   L2 group failed ({grpErrors.size} errors)"
          if l2Applied > 0 then
            IO.println s!"[L2_ANTIUN] {l2Applied} L2 replacements verified individually"
          else
            IO.println s!"[L2_ANTIUN] No L2 groups verified : all reverted"
    else
      IO.println s!"[L2_ANTIUN] No L2 replacements emitted (detection-only results logged above)"

  IO.println s!"[L2_SUMMARY] {l2Applied} L2 anti-unification replacements applied, {l2Detections} detections in {l2Groups} groups"

  traceMem "03_post_l2" cfg
  -- ═════════════════════════════════════════════════════════════════════
  -- Phase 2: Dead code removal (independent pass on verified text)
  -- ═════════════════════════════════════════════════════════════════════

  let mut deadRemoved : Nat := 0

  if verified && !deadRanges.isEmpty && !cfg.skipDeadCode then
    -- Build dead code deletion candidates (in original proof file positions)
    let mut dcCands : Array Candidate := #[]
    let mut seen : Std.HashSet (Nat × Nat) := {}
    for (s, e) in deadRanges do
      let (s', e') := extendToFullLines fileData s e
      if seen.contains (s', e') then continue
      seen := seen.insert (s', e')
      -- Skip if overlapping any verified tactic replacement
      let overlaps := activeSet.any (fun c => s' < c.endPos && e' > c.startPos)
      if !overlaps then
        dcCands := dcCands.push {
          startPos := s', endPos := e', newTac := "",
          goalType := "dead_code", kind := "dead_have", termSize := 0
          isPropSafe := true  -- DAG proves this block is unreferenced; removal is always safe
        }

    if !dcCands.isEmpty then
      -- Verify dead code batch (DAG analysis proves each block is unreferenced,
      -- but haveI/instance blocks affect type class resolution downstream).
      IO.println s!"[DEAD_CODE] Verifying batch removal of {dcCands.size} dead code blocks..."
      let dcTestSet := activeSet ++ dcCands
      let dcTestText := applyReplacements fileData dcTestSet
      let dcFirstMod := dcTestSet.foldl (fun acc c => min acc c.startPos) fileData.utf8ByteSize
      let dcErrors ← verifyTextIncremental cmdCheckpoints importEnv headerEndPos dcTestText path dcFirstMod
      if dcErrors.isEmpty then
        activeSet := dcTestSet
        deadRemoved := dcCands.size
        IO.println s!"[DEAD_CODE] All {dcCands.size} dead code blocks verified"
      else do
        IO.println s!"[DEAD_CODE] Batch failed ({dcErrors.size} errors) : trying individual blocks..."
        let mut safeDc : Array Candidate := #[]
        for dc in dcCands do
          let indTestSet := activeSet ++ safeDc ++ #[dc]
          let indTestText := applyReplacements fileData indTestSet
          let indFirstMod := indTestSet.foldl (fun acc c => min acc c.startPos) fileData.utf8ByteSize
          let indErrors ← verifyTextIncremental cmdCheckpoints importEnv headerEndPos indTestText path indFirstMod
          if indErrors.isEmpty then
            safeDc := safeDc.push dc
        activeSet := activeSet ++ safeDc
        deadRemoved := safeDc.size
        IO.println s!"[DEAD_CODE] {safeDc.size}/{dcCands.size} dead code blocks verified individually"

  traceMem "04_post_deadcode" cfg
  -- ═════════════════════════════════════════════════════════════════════
  -- Phase 3: Warning-guided cleanup (dead <;> arms, sequence simplification)
  -- Skip entirely if the text has no `<;>` constructs (nothing to clean).
  -- ═════════════════════════════════════════════════════════════════════

  let mut warnsRemoved : Nat := 0
  -- Track per-warning cleanup edits for training pair emission
  -- (lineNo, original_line_text, warning_msg, warning_kind_str)
  let mut cleanupTrainingPairs : Array (Nat × String × String × String) := #[]
  let mut cleanedText : String :=
    if verified && !activeSet.isEmpty then applyReplacements fileData activeSet
    else fileData

  -- Quick check: skip Phase 3 if no <;> in the current text
  let hasSeqCombinator := cleanedText.containsSubstr "<;>"
  if !hasSeqCombinator then
    IO.println "[CLEANUP] No `<;>` constructs : skipping Phase 3"
  if cfg.skipCleanup then
    IO.println "[CLEANUP] Skipped (--skip-cleanup)"

  if hasSeqCombinator && !cfg.skipCleanup then do  -- Phase 3 block
    let MAX_CLEANUP_ROUNDS := 3
    for cleanRound in [:MAX_CLEANUP_ROUNDS] do
      let (collectedErrs, rawWarns) ← elaborateAndCollect importEnv headerEndPos cleanedText path

      -- Only act on warnings we know how to handle
      let locatedWarns := rawWarns.filterMap (fun (bp, line, col, msg) =>
        let kind := classifyWarning msg
        if kind != .other then some { bytePos := bp, line := line, col := col, msg := msg, kind := kind : LocatedWarning }
        else none)

      if locatedWarns.isEmpty then
        if cleanRound == 0 then
          IO.println s!"[CLEANUP] No actionable warnings : text is clean"
        else
          IO.println s!"[CLEANUP] Round {cleanRound}: converged with 0 remaining warnings"
        break

      IO.println s!"[CLEANUP] Round {cleanRound + 1}: {locatedWarns.size} actionable warnings found"
      let deadCount := locatedWarns.filter (fun w => w.kind == .doesNothing || w.kind == .neverExecuted) |>.size
      let seqCount := locatedWarns.filter (fun w => w.kind == .useSemicolon) |>.size
      IO.println s!"[CLEANUP]   dead={deadCount}, semicolon={seqCount}"

      let candidate := removeDeadWarningLines cleanedText locatedWarns
      if candidate == cleanedText then
        IO.println s!"[CLEANUP] Round {cleanRound + 1}: no changes applied : stopping"
        break

      -- Verify the cleaned text compiles.  If elaborateAndCollect already
      -- found errors on the pre-edit text, the source itself is broken and
      -- the candidate is rejected; otherwise the candidate text is fully
      -- re-verified.
      let cleanErrors ← if !collectedErrs.isEmpty then
          -- Source text already had errors : candidate can only be worse
          pure collectedErrs
        else
          verifyText importEnv headerEndPos candidate path
      if cleanErrors.isEmpty then
        let bytesSaved := cleanedText.utf8ByteSize - candidate.utf8ByteSize
        warnsRemoved := warnsRemoved + 1  -- count rounds, not individual removals
        -- Collect per-warning training pairs before updating cleanedText
        let preLines := cleanedText.splitOn "\n" |>.toArray
        for w in locatedWarns do
          let lineIdx := w.line - 1
          if lineIdx < preLines.size then
            let origLine := preLines[lineIdx]!
            let kindStr := match w.kind with
              | .doesNothing => "dead_tactic" | .neverExecuted => "never_executed"
              | .useSemicolon => "use_semicolon" | .other => "other"
            cleanupTrainingPairs := cleanupTrainingPairs.push (w.line, origLine.trim, w.msg, kindStr)
        cleanedText := candidate
        IO.println s!"[CLEANUP] Round {cleanRound + 1}: verified ({bytesSaved} bytes saved)"
      else
        IO.println s!"[CLEANUP] Round {cleanRound + 1}: {cleanErrors.size} errors : reverting"
        for (eLine, eCol, eMsg) in cleanErrors do
          IO.println s!"[CLEANUP]   Error L{eLine}:{eCol}: {eMsg.take 100}"
        break

  traceMem "05_post_phase3" cfg
  -- ═════════════════════════════════════════════════════════════════════
  -- Final safety check: one verification of the complete result.
  -- Catches any text-level emission bugs (indentation, name shadowing, etc.)
  -- that the Prop-safety guarantees do not cover.
  -- ═════════════════════════════════════════════════════════════════════

  -- Final safety check: verify that tactic edits + dead code + cleanups compile together.
  -- Tactic edits were verified in Phase 1, but dead code and cleanup were added later;
  -- this catches any interactions between them.
  if deadRemoved > 0 then
    -- Skip FINAL_CHECK when Phase 3 already verified the complete text
    -- (cleanedText includes tactic edits + dead code + warning cleanups;
    -- Phase 3's last verifyText already proved it compiles).
    if warnsRemoved > 0 then
      IO.println s!"[FINAL_CHECK] Skipped : Phase 3 already verified complete text"
    else do
      IO.println s!"[FINAL_CHECK] Verifying complete result ({activeSet.size} edits + {deadRemoved} dead code removals)..."
      let finalText := if !activeSet.isEmpty then applyReplacements fileData activeSet
                       else fileData
      let finalErrors ← verifyText importEnv headerEndPos finalText path
      if !finalErrors.isEmpty then
        IO.println s!"[FINAL_CHECK] {finalErrors.size} errors : dropping dead code"
        for (eLine, eCol, eMsg) in finalErrors do
          IO.println s!"[FINAL_CHECK]   Error L{eLine}:{eCol}: {eMsg.take 100}"
        -- Dead code was added without verification (DAG-proven); drop it, keep verified tactic edits
        activeSet := activeSet.filter (fun c => c.kind != "dead_have")
        deadRemoved := 0
        cleanedText := if !activeSet.isEmpty then applyReplacements fileData activeSet else fileData
      else
        IO.println s!"[FINAL_CHECK] Complete result verified"

  traceMem "06_post_final_check" cfg
  -- ═════════════════════════════════════════════════════════════════════
  -- Output
  -- ═════════════════════════════════════════════════════════════════════

  let hasTacticChanges := verified && !activeSet.isEmpty
  let hasCleanupChanges := warnsRemoved > 0
  let hasAnyChanges := hasTacticChanges || hasCleanupChanges
  -- ── Schema  ──────────────────────────────
  -- Every TRAINING_PAIR / REJECTED_PAIR row goes through `emitJsonLine`,
  -- which builds via `Lean.Json.mkObj` (RFC-8259-correct escaping) and
  -- prints `<tag> <compressed-json>`.  Control character escapes and
  -- surrogate pairs are handled by the Lean stdlib.
  let gitSha ← gitShaIO
  -- Taxonomy axis: precompute via the syntax-tree classifier (with the
  -- import environment we already have in scope).
  let axisOf : String → String := fun s =>
    (tacticAxisOfSyntax importEnv s).toAxisString
  let provenanceFields : List (String × Lean.Json) :=
    [("schema_version", Lean.toJson trainingPairSchemaVersion),
     ("git_sha",        Lean.toJson gitSha)]

  if hasAnyChanges then
    let outPath :=
      if path.endsWith ".lean" then path.dropRight 5 ++ "_shortened.lean"
      else path ++ "_shortened"
    IO.FS.writeFile outPath cleanedText
    let tacCount := if hasTacticChanges then activeSet.size - deadRemoved else 0
    let bytesOrig := fileData.utf8ByteSize
    let bytesShort := cleanedText.utf8ByteSize
    let tokensOrig := countLeanTokens fileData
    let tokensShort := countLeanTokens cleanedText
    let linesOrig := countNonBlankLines fileData
    let linesShort := countNonBlankLines cleanedText
    IO.println s!"[DONE] {tacCount} tactic replacements + {deadRemoved} dead code removals + {l2Applied} L2 anti-unif + {warnsRemoved} warning cleanups → {outPath}"
    IO.println s!"[METRICS] bytes: {bytesOrig} → {bytesShort} ({100 * (bytesOrig - bytesShort) / max bytesOrig 1}%) | tokens: {tokensOrig} → {tokensShort} ({100 * (tokensOrig - tokensShort) / max tokensOrig 1}%) | lines: {linesOrig} → {linesShort} ({100 * (linesOrig - linesShort) / max linesOrig 1}%)"
    -- Emit per-replacement training pairs with rich metadata.
    -- Each accepted candidate also produces one [REJECTED_PAIR] line per tried-but-failed
    -- tactic, sharing the same `attempt_id`.
    if hasTacticChanges then
      for c in activeSet do
        let origTac := fileData.extract ⟨c.startPos⟩ ⟨c.endPos⟩
        let ctxStart := if c.startPos > 300 then c.startPos - 300 else 0
        let ctxEnd := min (c.endPos + 300) fileData.utf8ByteSize
        let context := fileData.extract ⟨ctxStart⟩ ⟨ctxEnd⟩
        let replType := if c.newTac == "" then "dead_code_removal"
          else if c.kind.startsWith "L2_antiun" then "l2_replacement"
          else "tactic_replacement"
        let lineNo := inputCtx.fileMap.toPosition ⟨c.startPos⟩ |>.line
        let attemptId := s!"{path}:{c.startPos}:{c.endPos}"
        -- failed_tactics: array of bare names (kept for backward compat).
        let failedTacticsJson : Lean.Json :=
          Lean.Json.arr (c.failedTactics.map (fun (t, _, _) => Lean.toJson t))
        -- failed_attempts: array of objects {tac, err, wall_ms}.
        let failedAttemptsJson : Lean.Json :=
          Lean.Json.arr (c.failedTactics.map fun (t, em, dt) =>
            Lean.Json.mkObj [("tac", Lean.toJson t),
                             ("err", Lean.toJson em),
                             ("wall_ms", Lean.toJson dt)])
        let commonFields : List (String × Lean.Json) :=
          [("original",         Lean.toJson origTac),
           ("replacement",      Lean.toJson c.newTac),
           ("goal_type",        Lean.toJson c.goalType),
           ("goal_pretty",      Lean.toJson c.goalPretty),
           ("goal_state",       Lean.toJson c.goalState),
           ("kind",             Lean.toJson c.kind),
           ("savings",          Lean.toJson c.savings),
           ("term_size",        Lean.toJson c.termSize),
           ("context",          Lean.toJson context),
           ("file",             Lean.toJson path),
           ("type",             Lean.toJson replType),
           ("start_byte",       Lean.toJson c.startPos),
           ("end_byte",         Lean.toJson c.endPos),
           ("line",             Lean.toJson lineNo),
           ("bytes_original",   Lean.toJson bytesOrig),
           ("bytes_shortened",  Lean.toJson bytesShort),
           ("tokens_original",  Lean.toJson tokensOrig),
           ("tokens_shortened", Lean.toJson tokensShort),
           ("lines_original",   Lean.toJson linesOrig),
           ("lines_shortened",  Lean.toJson linesShort),
           ("attempt_id",       Lean.toJson attemptId),
           ("axis_orig",        Lean.toJson (axisOf origTac)),
           ("axis_repl",        Lean.toJson (axisOf c.newTac))]
        emitJsonLine "[TRAINING_PAIR]"
          (provenanceFields ++ commonFields ++
           [("failed_tactics",   failedTacticsJson),
            ("failed_attempts",  failedAttemptsJson),
            ("outcome",          Lean.toJson "accepted"),
            ("rank_in_attempt",  Lean.toJson (1 : Nat))] ++
           (if cfg.completeMenu then
              [("menu_mode", Lean.toJson "complete"),
               ("menu_siblings", Lean.Json.arr (c.menuSiblings.map fun (t, lab, em, dt) =>
                  Lean.Json.mkObj [("tac", Lean.toJson t), ("outcome", Lean.toJson lab),
                                   ("err", Lean.toJson em), ("wall_ms", Lean.toJson dt)]))]
            else []))
        -- In complete-menu mode every non-chosen menu candidate becomes a
        -- sibling row with an explicit outcome label (valid_not_chosen,
        -- rejected_kernel, timeout, rejected_quality, rejected_length).
        -- Default mode: only the failures tried before the winner.
        let sibRows : Array (String × String × String × Nat) :=
          if cfg.completeMenu then c.menuSiblings
          else c.failedTactics.map fun (t, em, dt) => (t, "rejected", em, dt)
        let mut rank : Nat := 2
        for (t, lab, em, dt) in sibRows do
          let rejectedFields : List (String × Lean.Json) :=
            [("original",         Lean.toJson origTac),
             ("replacement",      Lean.toJson t),
             ("goal_type",        Lean.toJson c.goalType),
             ("goal_pretty",      Lean.toJson c.goalPretty),
             ("goal_state",       Lean.toJson c.goalState),
             ("kind",             Lean.toJson c.kind),
             ("savings",          Lean.toJson (0 : Nat)),
             ("term_size",        Lean.toJson (0 : Nat)),
             ("context",          Lean.toJson context),
             ("file",             Lean.toJson path),
             ("type",             Lean.toJson "rejected_attempt"),
             ("start_byte",       Lean.toJson c.startPos),
             ("end_byte",         Lean.toJson c.endPos),
             ("line",             Lean.toJson lineNo),
             ("bytes_original",   Lean.toJson bytesOrig),
             ("bytes_shortened",  Lean.toJson bytesShort),
             ("tokens_original",  Lean.toJson tokensOrig),
             ("tokens_shortened", Lean.toJson tokensShort),
             ("lines_original",   Lean.toJson linesOrig),
             ("lines_shortened",  Lean.toJson linesShort),
             ("attempt_id",       Lean.toJson attemptId),
             ("outcome",          Lean.toJson lab),
             ("rank_in_attempt",  Lean.toJson rank),
             ("err_msg",          Lean.toJson em),
             ("wall_ms",          Lean.toJson dt),
             ("axis_orig",        Lean.toJson (axisOf origTac)),
             ("axis_repl",        Lean.toJson (axisOf t))]
          emitJsonLine "[REJECTED_PAIR]" (provenanceFields ++ rejectedFields)
          rank := rank + 1
    -- Emit cleanup training pairs (Phase 3 warning-guided edits)
    if hasCleanupChanges then
      for (lineNo, origLine, warnMsg, kindStr) in cleanupTrainingPairs do
        let cleanupFields : List (String × Lean.Json) :=
          [("original",         Lean.toJson origLine),
           ("replacement",      Lean.toJson ""),
           ("goal_type",        Lean.toJson "cleanup"),
           ("kind",             Lean.toJson s!"cleanup_{kindStr}"),
           ("savings",          Lean.toJson (0 : Nat)),
           ("term_size",        Lean.toJson (0 : Nat)),
           ("context",          Lean.toJson warnMsg),
           ("file",             Lean.toJson path),
           ("type",             Lean.toJson "warning_cleanup"),
           ("start_byte",       Lean.toJson (0 : Nat)),
           ("end_byte",         Lean.toJson (0 : Nat)),
           ("line",             Lean.toJson lineNo),
           ("bytes_original",   Lean.toJson bytesOrig),
           ("bytes_shortened",  Lean.toJson bytesShort),
           ("tokens_original",  Lean.toJson tokensOrig),
           ("tokens_shortened", Lean.toJson tokensShort),
           ("lines_original",   Lean.toJson linesOrig),
           ("lines_shortened",  Lean.toJson linesShort)]
        emitJsonLine "[TRAINING_PAIR]" (provenanceFields ++ cleanupFields)
    let jsonStr := "{" ++ s!"\"applied\": {activeSet.size}, \"verified\": {hasTacticChanges}, \"output\": \"{outPath}\", \"dead_code_detected\": {deadRanges.length}, \"dead_code_removed\": {deadRemoved}, \"l2_antiun_applied\": {l2Applied}, \"l2_detections\": {l2Detections}, \"l2_groups\": {l2Groups}, \"l2_g3_rejected\": {l2G3Rejected}, \"warning_cleanups\": {warnsRemoved}, \"tactic_replacements\": {if hasTacticChanges then activeSet.size - deadRemoved else 0}, \"rounds\": \"{verifyRounds}\", \"bytes_original\": {bytesOrig}, \"bytes_shortened\": {bytesShort}, \"tokens_original\": {tokensOrig}, \"tokens_shortened\": {tokensShort}, \"lines_original\": {linesOrig}, \"lines_shortened\": {linesShort}" ++ "}"
    IO.println s!"[JSON] {jsonStr}"
  else
    IO.println "[DONE] No beneficial replacements found."
    let tokensOrig := countLeanTokens fileData
    let linesOrig := countNonBlankLines fileData
    let bytesOrig := fileData.utf8ByteSize
    IO.println s!"[METRICS] bytes: {bytesOrig} | tokens: {tokensOrig} | lines: {linesOrig} (no changes)"
    let jsonStr := "{" ++ s!"\"applied\": 0, \"verified\": false, \"output\": null, \"dead_code_detected\": {deadRanges.length}, \"dead_code_removed\": 0, \"warning_cleanups\": 0, \"tactic_replacements\": 0, \"bytes_original\": {bytesOrig}, \"tokens_original\": {tokensOrig}, \"lines_original\": {linesOrig}" ++ "}"
    IO.println s!"[JSON] {jsonStr}"

  -- Emit L2 detection-only training pairs unconditionally (even when no changes are made)
  if !l2DetectPairs.isEmpty then
    let bytesOrig := fileData.utf8ByteSize
    let bytesShort := if hasAnyChanges then cleanedText.utf8ByteSize else bytesOrig
    let tokensOrig' := countLeanTokens fileData
    let tokensShort' := if hasAnyChanges then countLeanTokens cleanedText else tokensOrig'
    let linesOrig' := countNonBlankLines fileData
    let linesShort' := if hasAnyChanges then countNonBlankLines cleanedText else linesOrig'
    for (arity, memberCount, hypTypeStr, reason, memberPositions) in l2DetectPairs do
      let posStr := String.intercalate "," (memberPositions.toList.map fun (s, e) => s!"{s}-{e}")
      -- Include proof texts of first 2 members (truncated to 500 chars each)
      let mut memberTexts : Array String := #[]
      for (s, e) in memberPositions.toList.take 2 do
        let txt := fileData.extract ⟨s⟩ ⟨e⟩ |>.trim
        let truncated := if txt.length > 500 then txt.extract ⟨0⟩ ⟨500⟩ ++ "..." else txt
        memberTexts := memberTexts.push truncated
      let member0 := if memberTexts.size > 0 then memberTexts[0]! else ""
      let member1 := if memberTexts.size > 1 then memberTexts[1]! else ""
      -- Skip degenerate detections where both extracted member texts are
      -- byte-identical: such records produce `original == replacement` and
      -- pollute downstream training.
      -- Antiunification has at least two textually-distinct members.
      if member0 == member1 then continue
      let l2Fields : List (String × Lean.Json) :=
        [("original",         Lean.toJson member0),
         ("replacement",      Lean.toJson member1),
         ("goal_type",        Lean.toJson hypTypeStr),
         ("kind",             Lean.toJson "l2_detection"),
         ("savings",          Lean.toJson (0 : Nat)),
         ("term_size",        Lean.toJson arity),
         ("context",          Lean.toJson s!"arity={arity},members={memberCount},reason={reason},positions={posStr}"),
         ("file",             Lean.toJson path),
         ("type",             Lean.toJson "l2_detection"),
         ("start_byte",       Lean.toJson (if memberPositions.size > 0 then memberPositions[0]!.1 else 0)),
         ("end_byte",         Lean.toJson (if memberPositions.size > 0 then memberPositions[0]!.2 else 0)),
         ("line",             Lean.toJson (0 : Nat)),
         ("bytes_original",   Lean.toJson bytesOrig),
         ("bytes_shortened",  Lean.toJson bytesShort),
         ("tokens_original",  Lean.toJson tokensOrig'),
         ("tokens_shortened", Lean.toJson tokensShort'),
         ("lines_original",   Lean.toJson linesOrig'),
         ("lines_shortened",  Lean.toJson linesShort')]
      emitJsonLine "[TRAINING_PAIR]" (provenanceFields ++ l2Fields)

def main (args : List String) : IO UInt32 := do
  -- ── Parse CLI flags ──────────────────────────────────────────────────
  let flags := args.filter (·.startsWith "--")
  let files := args.filter (!·.startsWith "--")
  let cfg : AblationConfig := {
    skipPhase1    := flags.contains "--skip-phase1"
    skipL2        := flags.contains "--skip-l2"
    skipDeadCode  := flags.contains "--skip-dead-code"
    skipCleanup   := flags.contains "--skip-cleanup"
    noQualityGate := flags.contains "--no-quality-gate"
    noG3          := flags.contains "--no-g3"
    memTrace      := flags.contains "--mem-trace"
    completeMenu  := flags.contains "--complete-menu"
    menuTimeoutAll := flags.contains "--menu-timeout-all"
    blockLocal    := flags.contains "--block-local"
    workerMode    := flags.contains "--worker"
  }
  -- Report active ablation flags
  let activeFlags := flags.filter (fun f =>
    f == "--skip-phase1" || f == "--skip-l2" || f == "--skip-dead-code" ||
    f == "--skip-cleanup" || f == "--no-quality-gate" || f == "--no-g3" ||
    f == "--mem-trace" || f == "--block-local" || f == "--worker" ||
    f == "--complete-menu" || f == "--menu-timeout-all")
  if !activeFlags.isEmpty then
    IO.println s!"[ABLATION] Active flags: {activeFlags}"
  -- Check for unknown flags
  let knownFlags := ["--skip-phase1", "--skip-l2", "--skip-dead-code",
                      "--skip-cleanup", "--no-quality-gate", "--no-g3",
                      "--mem-trace", "--block-local", "--worker",
                      "--complete-menu", "--menu-timeout-all"]
  for f in flags do
    if !knownFlags.contains f then
      IO.eprintln s!"[WARN] Unknown flag: {f} (ignored)"

  if files.isEmpty then
    IO.eprintln "Usage: LeanPolish [--skip-phase1] [--skip-l2] [--skip-dead-code] [--skip-cleanup] [--no-quality-gate] [--no-g3] [--mem-trace] [--block-local] [--worker] <bootstrap.lean | file1.lean> [file2.lean ...]"
    IO.eprintln "  --worker BOOTSTRAP : load imports from BOOTSTRAP once, then read one file path per line from stdin until EOF."
    return 1
  -- Load Mathlib imports once from the first file's header
  Lean.initSearchPath (← Lean.findSysroot)
  let firstPath := files.head!
  let firstData ← IO.FS.readFile firstPath
  let firstCtx := Parser.mkInputContext firstData firstPath
  let (header, _, msgs) ← Parser.parseHeader firstCtx
  let loadStartMs ← IO.monoMsNow
  let (importEnv, importMsgs) ← Lean.Elab.processHeader header Options.empty msgs firstCtx
  let loadEndMs ← IO.monoMsNow
  IO.println s!"[IMPORTS LOADED] Shared Mathlib environment ready in {loadEndMs - loadStartMs}ms"
  if importMsgs.hasErrors then
    IO.eprintln "[ERROR] Import loading failed : is LEAN_PATH set? Try: lake env .lake/build/bin/LeanPolish"
    return 1
  if cfg.workerMode then
    -- Persistent worker mode.  The bootstrap path is used only to load imports;
    -- it is not processed.  Subsequent file paths arrive on stdin, one per
    -- line, until EOF.  This lets a Python orchestrator keep N hot workers
    -- and amortise the (slow) Mathlib import cost across an entire corpus.
    --
    -- Soundness: every assigned file must have an import set ⊆ bootstrap's
    -- import set.  The orchestrator is responsible for partitioning files
    -- by header signature; the worker performs no header re-validation
    -- (processFile re-parses the file's header purely to compute
    -- `headerEndPos` and seed `cmdState.messages`, then elaborates the body
    -- against the shared `importEnv`).
    IO.println s!"[WORKER_READY] bootstrapped from {firstPath}"
    (← IO.getStdout).flush
    let stdin ← IO.getStdin
    let mut count : Nat := 0
    let mut wallTotal : Nat := 0
    let mut keepGoing := true
    while keepGoing do
      let line ← stdin.getLine
      if line.isEmpty then
        keepGoing := false  -- EOF
      else
        let path := line.trim
        if !path.isEmpty then
          IO.println s!"\n[FILE] {path}"
          let t0 ← IO.monoMsNow
          try
            processFile importEnv path cfg
            traceMem "07_end" cfg
          catch e =>
            IO.eprintln s!"[FILE_ERROR] {path}: {e}"
            traceMem "07_end_after_error" cfg
          let dt := (← IO.monoMsNow) - t0
          wallTotal := wallTotal + dt
          -- Orchestrator splits the per-file output stream.
          -- Path is JSON-escaped so paths containing
          -- quotes / backslashes round-trip safely.
          let escPath : String :=
            path.replace "\\" "\\\\" |>.replace "\"" "\\\""
                |>.replace "\n" "\\n" |>.replace "\r" "\\r" |>.replace "\t" "\\t"
          IO.println s!"[WORKER_DONE] \"{escPath}\" {dt}"
          (← IO.getStdout).flush
          count := count + 1
    IO.println s!"[WORKER_EXIT] processed {count} files in {wallTotal}ms"
  else
    -- Process all files with the shared environment
    for path in files do
      IO.println s!"\n[FILE] {path}"
      try
        processFile importEnv path cfg
        traceMem "07_end" cfg
      catch e =>
        IO.eprintln s!"[FILE_ERROR] {path}: {e}"
        traceMem "07_end_after_error" cfg
  -- Force-exit to bypass Lean runtime shutdown hang.
  -- GC of the large Mathlib environment can take minutes with no useful work being done.
  (← IO.getStdout).flush
  (← IO.getStderr).flush
  IO.Process.exit 0
