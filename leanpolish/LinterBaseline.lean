import Lean
import Mathlib

open Lean Elab Meta Command Parser Term Tactic System Frontend

/-!
# LinterBaseline : Symbolic Linter Baseline

Reference baseline for the symbolic linter described by
Gu et al. (arXiv:2510.15700, §3.2):

  > "we implement a symbolic linter that removes extraneous tactics via Lean's
  >  `linter.unusedTactic` linter, which detects tactics that do not change
  >  the proof state and provides messages like `'norm_num' tactic does nothing`."

The baseline proceeds as follows:

  1. Elaborate the file under a Mathlib import environment with only
     `linter.unusedTactic` enabled (the two related Batteries linters
     `linter.unreachableTactic` and `linter.unnecessarySeqFocus` are
     explicitly disabled so they cannot inflate the baseline).
  2. Splice out the syntactic ranges flagged by `linter.unusedTactic` using
     each warning's own `Position`/`endPosition`.
  3. Verify the splice still type-checks; revert if not.
  4. Iterate to a fixpoint (safety cap = 10 rounds).
  5. Report `bytes/tokens/lines` saved.

Token counts use the Appendix-L lexer of Gu et al. (`countLeanTokensAppL`),
so numbers are directly comparable to the values reported there
(9.2 % miniF2F / 7.4 % PutnamBench).

Usage:
```
lake env .lake/build/bin/LinterBaseline file1.lean file2.lean ...
```
-/

-- ═══════════════════════════════════════════════════════════════════════════
-- §1.  Tokenizer — Appendix L (Gu et al. 2025, Appendix L)
-- ═══════════════════════════════════════════════════════════════════════════

/-- Identifier-character predicate used by the paper's Python lexer
    (`isalnum(ch) or ch in "_.'"`). Note that `.` is part of an identifier,
    so `Foo.bar.baz` is a single token. -/
private def isAppLIdent (c : Char) : Bool :=
  c.isAlphanum || c == '_' || c == '.' || c == '\''

/-- Multi-character operators recognised by Appendix L (longest first). -/
private def appLOps3 : List String := ["...", "<;>"]
private def appLOps2 : List String :=
  [":=", "!=", "&&", "-.", "->", "<-", "..", "::", ":>", ";;",
   "==", "||", "=>", "<=", ">=", "?_"]

/-- Appendix-L token counter (single-pass, no comment stripping,
    the paper's lexer also does not strip comments). -/
def countLeanTokensAppL (s : String) : Nat := Id.run do
  -- Phase 1: per-line scan into single-char-or-identifier tokens.
  let mut toks : Array String := #[]
  for line in s.splitOn "\n" do
    let mut tok := ""
    for c in line.toList do
      if c == ' ' || c == '\t' then
        if tok != "" then toks := toks.push tok; tok := ""
      else if isAppLIdent c then
        tok := tok.push c
      else
        if tok != "" then toks := toks.push tok; tok := ""
        toks := toks.push (String.singleton c)
    if tok != "" then toks := toks.push tok
  -- Phase 2: longest-match merge of multi-character operators.
  let n := toks.size
  let mut count : Nat := 0
  let mut i : Nat := 0
  while i < n do
    if i + 3 ≤ n then
      let three := toks[i]! ++ toks[i+1]! ++ toks[i+2]!
      if appLOps3.contains three then
        count := count + 1; i := i + 3; continue
    if i + 2 ≤ n then
      let two := toks[i]! ++ toks[i+1]!
      if appLOps2.contains two then
        count := count + 1; i := i + 2; continue
    count := count + 1; i := i + 1
  return count

/-- Richer Lean-aware token counter that handles comments and additional
  operators. Kept as a secondary diagnostic metric. -/
private def isLeanTokenIdentChar (c : Char) : Bool :=
  c.isAlpha || c.isDigit || c == '_' || c == '\'' || (c.val ≥ 0x2080 && c.val ≤ 0x2089)

def countLeanTokensRich (s : String) : Nat := Id.run do
  let mut count : Nat := 0
  let mut pos : String.Pos := ⟨0⟩
  let len := s.utf8ByteSize
  while pos.byteIdx < len do
    let c := s.get pos
    if c == ' ' || c == '\t' || c == '\n' || c == '\r' then
      pos := s.next pos; continue
    if c == '-' then
      let p1 := s.next pos
      if p1.byteIdx < len && s.get p1 == '-' then
        pos := s.next p1
        while pos.byteIdx < len && s.get pos != '\n' do pos := s.next pos
        continue
    if c == '/' then
      let p1 := s.next pos
      if p1.byteIdx < len && s.get p1 == '-' then
        pos := s.next p1
        let mut depth : Nat := 1
        while pos.byteIdx < len && depth > 0 do
          let cc := s.get pos; let np := s.next pos
          if cc == '/' && np.byteIdx < len && s.get np == '-' then
            depth := depth + 1; pos := s.next np
          else if cc == '-' && np.byteIdx < len && s.get np == '/' then
            depth := depth - 1; pos := s.next np
          else pos := np
        continue
    if isLeanTokenIdentChar c then
      pos := s.next pos
      while pos.byteIdx < len && isLeanTokenIdentChar (s.get pos) do pos := s.next pos
      count := count + 1; continue
    let p1 := s.next pos
    if p1.byteIdx < len then
      let c1 := s.get p1
      let p2 := s.next p1
      if p2.byteIdx < len then
        let c2 := s.get p2
        if (c == '<' && c1 == ';' && c2 == '>') || (c == '>' && c1 == '>' && c2 == '=') then
          count := count + 1; pos := s.next p2; continue
      if (c == ':' && c1 == '=') || (c == '!' && c1 == '=') || (c == '-' && c1 == '>') ||
         (c == '<' && c1 == '-') || (c == '=' && c1 == '>') || (c == '>' && c1 == '=') ||
         (c == '<' && c1 == '=') || (c == '+' && c1 == '+') || (c == '>' && c1 == '>') ||
         (c == '.' && c1 == '.') || (c == '#' && c1 == '[') then
        count := count + 1; pos := s.next p1; continue
    count := count + 1; pos := s.next pos
  return count

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
      if blockDepth > 0 then
        let np := line.next pos
        if c == '/' && np.byteIdx < lineLen && line.get np == '-' then
          blockDepth := blockDepth + 1; pos := line.next np; continue
        if c == '-' && np.byteIdx < lineLen && line.get np == '/' then
          blockDepth := blockDepth - 1; pos := line.next np; continue
        pos := np; continue
      if c == '/' then
        let np := line.next pos
        if np.byteIdx < lineLen && line.get np == '-' then
          blockDepth := blockDepth + 1; pos := line.next np; continue
      if c == '-' then
        let np := line.next pos
        if np.byteIdx < lineLen && line.get np == '-' then break
      if c != ' ' && c != '\t' && c != '\r' then hasContent := true
      pos := line.next pos
    if hasContent then count := count + 1
  return count

-- ═══════════════════════════════════════════════════════════════════════════
-- §2.  Detect only `linter.unusedTactic` warnings
-- ═══════════════════════════════════════════════════════════════════════════

/-- A warning fires from `linter.unusedTactic` iff the rendered message
    contains the canonical phrase `tactic does nothing`. Mathlib's
    `UnusedTactic.lean` emits exactly:

        `'{stx}' tactic does nothing`

    We additionally disable the two Batteries linters
    (`linter.unreachableTactic`, `linter.unnecessarySeqFocus`) at elaboration
    time so they cannot fire, but this string check is a defence-in-depth
    filter in case a future Lean version changes defaults. -/
def isUnusedTacticWarning (msg : String) : Bool :=
  msg.containsSubstr "tactic does nothing"

/-- A warning located in the source file. `startByte`/`endByte` come from the
    flagged `Syntax`'s own range (via `msg.pos`/`msg.endPos`). -/
structure UnusedWarning where
  startByte : Nat
  endByte   : Nat
  line      : Nat
  col       : Nat
  msg       : String
  deriving Repr

-- ═══════════════════════════════════════════════════════════════════════════
-- §3.  Elaboration with only `linter.unusedTactic` enabled
-- ═══════════════════════════════════════════════════════════════════════════

/-- Options used during the linter pass: only `linter.unusedTactic` is allowed
    to fire; the other two related linters are disabled. -/
private def linterOnlyOpts : Options :=
  Options.empty
    |>.setNat  `maxHeartbeats 800000
    |>.setBool `linter.unusedTactic        true
    |>.setBool `linter.unreachableTactic   false
    |>.setBool `linter.unnecessarySeqFocus false

/-- Options used during verification re-elaboration: silence all linters so
    a previously-clean file does not start flagging itself after a splice. -/
private def verifyOpts : Options :=
  Options.empty
    |>.setNat  `maxHeartbeats 800000
    |>.setBool `linter.unusedTactic        false
    |>.setBool `linter.unreachableTactic   false
    |>.setBool `linter.unnecessarySeqFocus false

/-- Elaborate `text` (with `headerEndPos` already parsed) under `importEnv`,
    running `linter.unusedTactic` and collecting:

      * elaboration errors (line, col, message);
      * `linter.unusedTactic` warnings as `UnusedWarning` records carrying
        the byte range of the flagged `Syntax`. -/
def elaborateAndCollect (importEnv : Environment) (headerEndPos : String.Pos)
    (text : String) (path : String)
    : IO (Array (Nat × Nat × String) × Array UnusedWarning) := do
  let inputCtx := Parser.mkInputContext text path
  let mut cmdState : Command.State := Command.mkState importEnv {} linterOnlyOpts
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
  let mut warnings : Array UnusedWarning := #[]
  for msg in cmdState.messages.toList do
    let data ← msg.data.toString
    if msg.severity == .error then
      errors := errors.push (msg.pos.line, msg.pos.column, data.take 200)
    else if msg.severity == .warning && isUnusedTacticWarning data then
      let startByte := (fileMap.ofPosition msg.pos).byteIdx
      let endByte   := match msg.endPos with
        | some ep => (fileMap.ofPosition ep).byteIdx
        | none    => startByte
      -- Defensive: skip degenerate ranges so we never splice 0 bytes
      -- (a 0-byte splice would loop forever at the fixpoint).
      if endByte > startByte then
        warnings := warnings.push
          { startByte, endByte, line := msg.pos.line, col := msg.pos.column, msg := data }
  return (errors, warnings)

-- ═══════════════════════════════════════════════════════════════════════════
-- §4.  Verification pass : errors only, all linters silenced
-- ═══════════════════════════════════════════════════════════════════════════

def verifyText (importEnv : Environment) (headerEndPos : String.Pos)
    (optText : String) (path : String) : IO (Array (Nat × Nat × String)) := do
  let inputCtx := Parser.mkInputContext optText path
  let mut cmdState : Command.State := Command.mkState importEnv {} verifyOpts
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

-- ═══════════════════════════════════════════════════════════════════════════
-- §5.  Syntax-range splice
-- ═══════════════════════════════════════════════════════════════════════════

/-- Extend a flagged byte-range so we also consume one trailing
    horizontal-whitespace run plus a single tactic separator (`;` or `\n`),
    if present. This avoids leaving a stray `;` between the previous and the
    next tactic in a `tacticSeq`, which would otherwise be a parse error.

    All characters we skip (` `, `\t`, `;`, `\n`) are ASCII (single-byte) so
    incrementing the byte index by 1 is safe. -/
private def extendRangeForSeparator (text : String) (s e : Nat) : Nat × Nat := Id.run do
  let len := text.utf8ByteSize
  let mut e' := e
  -- Skip horizontal whitespace.
  while e' < len do
    let c := text.get ⟨e'⟩
    if c == ' ' || c == '\t' then e' := e' + 1 else break
  -- Consume exactly one separator if one is there.
  if e' < len then
    let c := text.get ⟨e'⟩
    if c == ';' || c == '\n' then e' := e' + 1
  return (s, e')

/-- Splice the given byte-ranges out of `text`. Ranges are processed in
    descending order of start position so earlier offsets remain valid
    after later cuts. Overlapping ranges (which can arise if the linter
    flags a tactic and its enclosing combinator on the same source span)
    are merged conservatively by skipping any range that is entirely inside
    a region already removed. -/
def spliceOutRanges (text : String) (warnings : Array UnusedWarning) : String := Id.run do
  -- Sort descending by start byte so later splices don't invalidate earlier ones.
  let sorted := warnings.qsort (fun a b => a.startByte > b.startByte)
  let mut result := text
  let mut lastStart : Nat := result.utf8ByteSize + 1  -- sentinel
  for w in sorted do
    let (s, e) := extendRangeForSeparator result w.startByte w.endByte
    -- Skip ranges whose end overlaps a previously-cut region (keeps splice
    -- offsets monotonic and avoids double-deleting nested syntax nodes).
    if e ≤ lastStart then
      let before := result.extract 0 ⟨s⟩
      let after  := result.extract ⟨e⟩ ⟨result.utf8ByteSize⟩
      result := before ++ after
      lastStart := s
  return result

-- ═══════════════════════════════════════════════════════════════════════════
-- §6.  File processor : iterate to a fixpoint
-- ═══════════════════════════════════════════════════════════════════════════

/-- Process a single file with the symbolic-linter baseline.

      1. Elaborate to collect `linter.unusedTactic` warnings.
      2. Splice out flagged syntax ranges.
      3. Re-verify; revert if compilation breaks.
      4. Iterate to a fixpoint (cap = 10 rounds for safety; the loop
         terminates earlier as soon as a round produces no change).
      5. Report metrics in the same JSON schema as LeanPolish.
-/
def processFile (importEnv : Environment) (path : String) : IO Unit := do
  let fileData ← IO.FS.readFile path
  let inputCtx := Parser.mkInputContext fileData path
  let (_header, parserState, _msgs) ← Parser.parseHeader inputCtx
  let headerEndPos := parserState.pos

  let startMs ← IO.monoMsNow

  let mut cleanedText := fileData
  let mut totalRemovals : Nat := 0
  let mut trainingPairs : Array (Nat × String × String) := #[]  -- (line, original, warnMsg)
  let MAX_ROUNDS := 10  -- Safety cap; the loop stops earlier at a fixpoint.

  for _round in [:MAX_ROUNDS] do
    let (errors, warnings) ← elaborateAndCollect importEnv headerEndPos cleanedText path
    if !errors.isEmpty then
      IO.eprintln s!"[SKIP] {path}: {errors.size} elaboration error(s)"
      break
    if warnings.isEmpty then break

    let candidate := spliceOutRanges cleanedText warnings
    if candidate == cleanedText then break

    let verifyErrors ← verifyText importEnv headerEndPos candidate path
    if !verifyErrors.isEmpty then
      IO.eprintln s!"[REVERT] {path}: linter splice broke compilation ({verifyErrors.size} error(s))"
      break

    -- Capture per-removal training data before overwriting cleanedText.
    let preLines := cleanedText.splitOn "\n"
    for w in warnings do
      totalRemovals := totalRemovals + 1
      let lineIdx := w.line - 1
      let origLine := if lineIdx < preLines.length then preLines[lineIdx]! else ""
      trainingPairs := trainingPairs.push (w.line, origLine, w.msg)

    cleanedText := candidate

  let endMs ← IO.monoMsNow
  let esc (s : String) : String :=
    s.replace "\\" "\\\\" |>.replace "\"" "\\\""
     |>.replace "\n" "\\n" |>.replace "\r" "\\r"
     |>.replace "\t" "\\t" |>.replace "\x00" "\\u0000"

  let bytesOrig    := fileData.utf8ByteSize
  let bytesShort   := cleanedText.utf8ByteSize
  let tokensOrig   := countLeanTokensAppL fileData      -- Main comparable metric.
  let tokensShort  := countLeanTokensAppL cleanedText
  let tokensRichO  := countLeanTokensRich fileData      -- Diagnostic metric.
  let tokensRichS  := countLeanTokensRich cleanedText
  let linesOrig    := countNonBlankLines fileData
  let linesShort   := countNonBlankLines cleanedText

  if cleanedText != fileData then
    let outPath :=
      if path.endsWith ".lean" then path.dropRight 5 ++ "_linter.lean"
      else path ++ "_linter"
    IO.FS.writeFile outPath cleanedText
    IO.println s!"[DONE] {totalRemovals} linter removals → {outPath} ({endMs - startMs}ms)"
    IO.println s!"[METRICS] bytes: {bytesOrig} → {bytesShort} ({100 * (bytesOrig - bytesShort) / max bytesOrig 1}%) | tokensAppL: {tokensOrig} → {tokensShort} ({100 * (tokensOrig - tokensShort) / max tokensOrig 1}%) | tokensRich: {tokensRichO} → {tokensRichS} | lines: {linesOrig} → {linesShort} ({100 * (linesOrig - linesShort) / max linesOrig 1}%)"
    for (lineNo, origLine, warnMsg) in trainingPairs do
      IO.println s!"[TRAINING_PAIR] \{\"original\": \"{esc origLine}\", \"replacement\": \"\", \"goal_type\": \"linter\", \"kind\": \"linter_unused_tactic\", \"savings\": 0, \"term_size\": 0, \"context\": \"{esc warnMsg}\", \"file\": \"{esc path}\", \"type\": \"linter_removal\", \"start_byte\": 0, \"end_byte\": 0, \"line\": {lineNo}, \"bytes_original\": {bytesOrig}, \"bytes_shortened\": {bytesShort}, \"tokens_original\": {tokensOrig}, \"tokens_shortened\": {tokensShort}, \"lines_original\": {linesOrig}, \"lines_shortened\": {linesShort}}"
    let jsonStr := "{" ++ s!"\"linter_removals\": {totalRemovals}, \"verified\": true, \"output\": \"{esc outPath}\", \"bytes_original\": {bytesOrig}, \"bytes_shortened\": {bytesShort}, \"bytes_saved\": {bytesOrig - bytesShort}, \"tokens_original\": {tokensOrig}, \"tokens_shortened\": {tokensShort}, \"tokens_saved\": {tokensOrig - tokensShort}, \"tokens_rich_original\": {tokensRichO}, \"tokens_rich_shortened\": {tokensRichS}, \"lines_original\": {linesOrig}, \"lines_shortened\": {linesShort}, \"lines_saved\": {linesOrig - linesShort}, \"time_ms\": {endMs - startMs}, \"tokenizer\": \"AppendixL\"" ++ "}"
    IO.println s!"[JSON] {jsonStr}"
  else
    IO.println s!"[DONE] No linter warnings found ({endMs - startMs}ms)"
    IO.println s!"[METRICS] bytes: {bytesOrig} | tokensAppL: {tokensOrig} | tokensRich: {tokensRichO} | lines: {linesOrig} (no changes)"
    let jsonStr := "{" ++ s!"\"linter_removals\": 0, \"verified\": true, \"output\": null, \"bytes_original\": {bytesOrig}, \"bytes_shortened\": {bytesOrig}, \"bytes_saved\": 0, \"tokens_original\": {tokensOrig}, \"tokens_shortened\": {tokensOrig}, \"tokens_saved\": 0, \"tokens_rich_original\": {tokensRichO}, \"tokens_rich_shortened\": {tokensRichO}, \"lines_original\": {linesOrig}, \"lines_shortened\": {linesOrig}, \"lines_saved\": 0, \"time_ms\": {endMs - startMs}, \"tokenizer\": \"AppendixL\"" ++ "}"
    IO.println s!"[JSON] {jsonStr}"

-- ═══════════════════════════════════════════════════════════════════════════
-- §7.  Main
-- ═══════════════════════════════════════════════════════════════════════════

def main (args : List String) : IO UInt32 := do
  let files := args.filter (!·.startsWith "--")
  if files.isEmpty then
    IO.eprintln "Usage: LinterBaseline <file1.lean> [file2.lean] ..."
    IO.eprintln ""
    IO.eprintln "Reference baseline for the symbolic linter in arXiv:2510.15700 §3.2"
    IO.eprintln "Removes only `linter.unusedTactic` hits;"
    IO.eprintln "the related Batteries linters are disabled. Token counts use the"
    IO.eprintln "Appendix-L lexer for direct comparability with the paper."
    return 1

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
    IO.eprintln "[ERROR] Import loading failed — is LEAN_PATH set? Try: lake env .lake/build/bin/LinterBaseline"
    return 1

  for path in files do
    IO.println s!"\n[FILE] {path}"
    try
      processFile importEnv path
    catch e =>
      IO.eprintln s!"[FILE_ERROR] {path}: {e}"

  (← IO.getStdout).flush
  (← IO.getStderr).flush
  IO.Process.exit 0
