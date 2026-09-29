#!/usr/bin/env python3
"""Run LeanPolish on individual files or directory batches.

The Python wrapper invokes the Lean executable, collects structured output,
writes shortened files and per-file reports, and consolidates accepted and
rejected edit rows for dataset construction. The Lean executable performs the
candidate generation and verification; this wrapper handles process control,
timeouts, batching, and report aggregation.

Usage:
    python leanpolish.py <lean-file>
    python leanpolish.py --batch <dir>
    python leanpolish.py --batch --server <dir>
    python leanpolish.py --batch --collect-only <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence, Tuple


# ===================================
# Provenance: commit SHA + content hashes
# ===================================
#
# Every emitted training pair is enriched with three provenance fields so the
# downstream kernel verifier (and human readers) can detect file-version drift:
#
#   commit_sha       : git rev-parse HEAD of the project at run time
#   mathlib_rev      : revision recorded in lake-manifest.json for `mathlib`
#   content_sha256   : SHA-256 of the source .lean file at run time
#
# If the source file changes between the optimizer run and the kernel
# verifier run, splices no longer line up. With these fields the verifier can
# report a mismatch verdict before attempting to splice.

def _git_rev_parse(repo_dir: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True,
            timeout=5, check=False,
        )
        if out.returncode == 0:
            sha = out.stdout.strip()
            return sha or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return None


def _read_mathlib_rev(project_root: Path) -> Optional[str]:
    """Read mathlib revision from lake-manifest.json (no git call needed)."""
    manifest = project_root / "lake-manifest.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for pkg in data.get("packages", []):
        if pkg.get("name") == "mathlib":
            return pkg.get("rev")
    return None


@lru_cache(maxsize=4096)
def _file_sha256(path_str: str) -> Optional[str]:
    """SHA-256 of a file's bytes, cached per absolute path."""
    try:
        h = hashlib.sha256()
        with open(path_str, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


_PROVENANCE_CACHE: dict = {}

def _project_provenance(project_root: Path) -> dict:
    """Memoised (commit_sha, mathlib_rev) for a given project root."""
    key = str(project_root.resolve())
    if key not in _PROVENANCE_CACHE:
        _PROVENANCE_CACHE[key] = {
            "commit_sha": _git_rev_parse(project_root),
            "mathlib_rev": _read_mathlib_rev(project_root),
        }
    return _PROVENANCE_CACHE[key]


def _enrich_pair_with_provenance(pair: dict, project_root: Path) -> None:
    """Add commit_sha, mathlib_rev, content_sha256 fields in-place.

    Resolves the source file relative to project_root using the pair's `file`
    field. Missing files (renamed, deleted) leave content_sha256 as None;
    downstream tools should treat None as "unverifiable" rather than "valid".
    """
    prov = _project_provenance(project_root)
    pair.setdefault("commit_sha", prov["commit_sha"])
    pair.setdefault("mathlib_rev", prov["mathlib_rev"])
    src_rel = pair.get("file")
    if src_rel:
        src_abs = (project_root / src_rel).resolve()
        pair.setdefault("content_sha256", _file_sha256(str(src_abs)))
    else:
        pair.setdefault("content_sha256", None)


# ===================================
# Result types
# ===================================

# Files that live in the project root or in source subtrees but are
# infrastructure (the optimizer itself, the linter harness, build glue)
# and must never be passed to the optimizer as input.
_INFRA_FILE_NAMES = frozenset({
    "lakefile.lean",
    "LeanPolish.lean",
    "MetaprogramProofShortener.lean",
    "LinterBaseline.lean",
})


@dataclass
class OptimizationResult:
    source_file: str
    output_file: Optional[str] = None
    original_lines: int = 0
    optimized_lines: int = 0
    replacements_applied: int = 0
    dead_code_blocks: int = 0
    verified: bool = False
    error: Optional[str] = None
    bytes_original: int = 0
    bytes_shortened: int = 0
    tokens_original: int = 0
    tokens_shortened: int = 0
    lines_original: int = 0      # non-blank, non-comment
    lines_shortened: int = 0     # non-blank, non-comment
    bisect_dropped: int = 0      # number of edits dropped by post-verify bisect
    training_pairs: List[dict] = field(default_factory=list)

    @property
    def bytes_saved(self) -> int:
        return self.bytes_original - self.bytes_shortened

    @property
    def tokens_saved(self) -> int:
        return self.tokens_original - self.tokens_shortened

    @property
    def lines_saved(self) -> int:
        return self.lines_original - self.lines_shortened

    def summary(self) -> str:
        if self.error:
            return f"FAIL {self.source_file}: {self.error}"
        if self.verified:
            status = "OK"
        else:
            # No error and not verified <=> orchestrator produced no shortened
            # file (nothing to shorten, or all candidates dropped).
            status = "--"
        bisect_note = f", bisect-dropped {self.bisect_dropped}" if self.bisect_dropped else ""
        return (
            f"{status} {self.source_file}: "
            f"{self.replacements_applied} replacements, "
            f"{self.bytes_saved} bytes saved ({self.bytes_original}→{self.bytes_shortened}), "
            f"{self.tokens_saved} tokens saved ({self.tokens_original}→{self.tokens_shortened}), "
            f"{self.dead_code_blocks} dead code blocks{bisect_note}"
        )


# ===================================
# Core logic
# ===================================

def _find_lake_root(search_dir: Path) -> Path:
    """Walk up from search_dir to find the directory containing lakefile.lean."""
    p = search_dir.resolve()
    while p != p.parent:
        if (p / "lakefile.lean").exists():
            return p
        p = p.parent
    raise FileNotFoundError(f"No lakefile.lean found at or above {search_dir}")


# Alias for single-file mode (takes a file, searches from its parent)
def find_workspace_dir(lean_file: Path) -> Path:
    return _find_lake_root(lean_file.parent)


# ===================================
# Independent post-verification
# ===================================

# Set LEANPOLISH_SKIP_POSTVERIFY=1 to bypass (e.g. for ablation studies).
# Default is to run a fresh `lake env lean` on every shortened file. If it
# fails, the *_shortened.lean and *_report.json are quarantined so downstream
# tools never see an unverified output. This catches false-positives from the
# in-process verifier (e.g. L2 anti-unification skipping kernel checks under
# proof-irrelevance assumptions that don't hold for tactics like `assumption`).
def _postverify_shortened(lean_file: Path, opt_file: Path,
                          timeout: int = 900) -> Tuple[bool, str]:
    """Run a fresh `lake env lean` on opt_file. Returns (ok, stderr_tail)."""
    if os.environ.get("LEANPOLISH_SKIP_POSTVERIFY") == "1":
        return True, "skipped"
    try:
        lake_root = _find_lake_root(lean_file.parent)
    except FileNotFoundError:
        return False, "no lakefile"
    try:
        proc = subprocess.run(
            ["lake", "env", "lean", str(opt_file.resolve())],
            cwd=str(lake_root), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"postverify timeout ({timeout}s)"
    except FileNotFoundError:
        return False, "lake not found in PATH"
    combined = (proc.stdout or "") + (proc.stderr or "")
    has_error = (": error:" in combined) or (proc.returncode != 0)
    if has_error:
        err_lines = [ln for ln in combined.splitlines() if ": error:" in ln]
        tail = "\n".join(err_lines[:5]) if err_lines else combined[-400:]
        return False, tail
    return True, "ok"


def _quarantine_unverified(lean_file: Path, opt_file: Path, reason: str) -> Path:
    """Move opt_file (and its sibling *_report.json) to a _quarantine/ dir."""
    qdir = lean_file.parent / "_quarantine_unverified"
    qdir.mkdir(exist_ok=True)
    moved = []
    for f in (opt_file, lean_file.with_name(lean_file.stem + "_report.json")):
        if f.exists():
            target = qdir / f.name
            try:
                f.rename(target)
                moved.append(target.name)
            except OSError:
                pass
    note = qdir / (opt_file.stem + ".reason.txt")
    note.write_text(f"source: {lean_file}\nmoved: {moved}\nreason:\n{reason}\n")
    return qdir


# ---------------------------------------------------------------------------
# Bisecting post-verify: recover yield from files where the in-process
# verifier missed an edit that fresh `lake env lean` rejects.
#
# Architecture
#   1. The Lean orchestrator emits a `_shortened.lean` (= original with a set
#      of N non-overlapping byte-range edits applied) plus a `_report.json`
#      whose `training_pairs` list records each edit as
#      (start_byte, end_byte, original, replacement, savings, ...).
#   2. `_postverify_shortened` runs fresh `lake env lean` on the output. If
#      the in-process verifier and the from-scratch elaboration agree (>= 98%
#      of files), we keep the full set of edits and move on.
#   3. If they disagree (rare: tactic substitution perturbing downstream
#      instance synthesis), we bisect on the edit set to keep the maximal
#      subset that passes fresh re-elaboration. Source file is never touched.
#
# Soundness invariant
#   A `_shortened.lean` adjacent to its source <=> fresh `lake env lean` on
#   that file produced no errors. The bisect step uses the same fresh kernel
#   as oracle, so the invariant is preserved by construction.
#
# Cost
#   Best case (1 edit OK):           1 verification (the original gate)
#   Worst case (n edits, k bad):     <= 2n verifications, k typically 1
#   Mean across a corpus:            +5–10% verification budget on the ≈1%
#                                    of files that need bisecting; 0% on the
#                                    rest.
# ---------------------------------------------------------------------------

def _apply_edits(orig_text: str, edits: List[dict]) -> str:
    """Apply non-overlapping byte-range edits to `orig_text`.

    Each edit is a dict with keys `start_byte`, `end_byte`, `replacement`.
    Edits are applied in reverse byte order so earlier byte indices remain
    valid throughout the rewrite. Caller must ensure edits do not overlap;
    we sanity-check and raise on overlap because an overlap means the
    orchestrator emitted a malformed report.
    """
    if not edits:
        return orig_text
    sorted_edits = sorted(edits, key=lambda e: e["start_byte"])
    for a, b in zip(sorted_edits, sorted_edits[1:]):
        if a["end_byte"] > b["start_byte"]:
            raise ValueError(
                f"overlapping edits at bytes {a['start_byte']}-{a['end_byte']} "
                f"and {b['start_byte']}-{b['end_byte']}")
    data = orig_text.encode()
    for e in reversed(sorted_edits):
        s, t = int(e["start_byte"]), int(e["end_byte"])
        rep = e["replacement"].encode()
        data = data[:s] + rep + data[t:]
    return data.decode()


def _verify_text(text: str, lean_file: Path, lake_root: Path,
                 timeout: int) -> bool:
    """Write `text` to a unique sibling of `lean_file` and run `lake env lean`.

    Returns True iff fresh elaboration produced no errors. The temp file
    lives in the same directory so all relative imports resolve identically
    to the production `_shortened.lean`. Always cleaned up.
    """
    tmp = lean_file.with_name(
        f"_bisect_{os.getpid()}_{threading.get_ident()}_{lean_file.stem}.lean")
    try:
        tmp.write_text(text)
        proc = subprocess.run(
            ["lake", "env", "lean", str(tmp.resolve())],
            cwd=str(lake_root), capture_output=True, text=True,
            timeout=timeout,
        )
        combined = (proc.stdout or "") + (proc.stderr or "")
        return (": error:" not in combined) and (proc.returncode == 0)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _maximal_sound_subset(orig_text: str, edits: List[dict],
                          verify_fn) -> List[dict]:
    """Return a large sound subset of `edits` (largest by `savings` on ties).

    Divide-and-conquer: if the full set verifies, keep all. Otherwise split,
    recurse on each half, then try the union. If the union fails (cross-half
    interaction), keep the half with greater savings. Verifications: O(n) in
    the worst case, 1 in the common (already-sound) case.

    Correctness: every returned subset has been verified by `verify_fn` at
    least once during the recursion (either as the full set, the union of
    sub-results, or one of two halves picked when the union fails).
    """
    if not edits:
        return []
    if verify_fn(_apply_edits(orig_text, edits)):
        return list(edits)
    if len(edits) == 1:
        return []  # single edit fails on its own
    mid = len(edits) // 2
    left = _maximal_sound_subset(orig_text, edits[:mid], verify_fn)
    right = _maximal_sound_subset(orig_text, edits[mid:], verify_fn)
    if left and right:
        union = left + right
        if verify_fn(_apply_edits(orig_text, union)):
            return union
    sav_l = sum(e.get("savings", 0) for e in left)
    sav_r = sum(e.get("savings", 0) for e in right)
    return left if sav_l >= sav_r else right


def _bisect_recover(lean_file: Path, opt_file: Path,
                    edits: List[dict], timeout: int = 900
                    ) -> Tuple[List[dict], str]:
    """Find the maximal subset of `edits` whose application passes fresh re-elab.

    Returns (kept_edits, status_msg). On success, rewrites `opt_file` in
    place to reflect the kept subset. If `kept_edits` is empty, the caller
    should remove `opt_file` (caller's responsibility to avoid emitting a
    no-op shortened file equal to the original).
    """
    try:
        lake_root = _find_lake_root(lean_file.parent)
    except FileNotFoundError:
        return list(edits), "no lakefile (skipped bisect)"

    # Filter to edits that carry the byte-range info we need. 
    usable = [e for e in edits
              if "start_byte" in e and "end_byte" in e and "replacement" in e]
    if not usable:
        return [], "no edits with byte-range info"

    orig_text = lean_file.read_text()

    def verify(text: str) -> bool:
        return _verify_text(text, lean_file, lake_root, timeout=timeout)

    # Sort by source byte position for deterministic bisect ordering.
    usable.sort(key=lambda e: e["start_byte"])
    kept = _maximal_sound_subset(orig_text, usable, verify)

    if kept:
        new_text = _apply_edits(orig_text, kept)
        # Final defensive verify of the file we are about to write.
        if not verify(new_text):
            return [], "internal error: kept subset failed final verify"
        opt_file.write_text(new_text)
        dropped = len(usable) - len(kept)
        return kept, (f"bisect kept {len(kept)}/{len(usable)} edits "
                      f"(dropped {dropped})")
    return [], f"bisect found no sound subset of {len(usable)} edits"


def _postverify_with_bisect(lean_file: Path, opt_file: Path,
                            training_pairs: List[dict]
                            ) -> Tuple[bool, str, Optional[List[dict]]]:
    """Run fresh-kernel post-verify; on failure, bisect to recover a sound
    subset of the orchestrator's edits. Rewrites `opt_file` in place when a
    proper subset is kept. Quarantines `opt_file` only when no sound subset
    of the applied edits exists.

    Returns (verified, status_msg, kept_edits) where:
      - verified : the file at `opt_file` (if it exists) is fresh-kernel sound
      - status_msg : suitable for surfacing in the OptimizationResult.error
      - kept_edits : the edit subset actually present in `opt_file` after
        bisect, or None if no bisect ran (i.e. original output was already
        sound, in which case the caller should keep the orchestrator's full
        training_pairs list).
    """
    ok, reason = _postverify_shortened(lean_file, opt_file)
    if ok:
        return True, "ok", None

    if os.environ.get("LEANPOLISH_SKIP_BISECT") == "1" or not training_pairs:
        qdir = _quarantine_unverified(lean_file, opt_file, reason)
        return False, f"[postverify] FAIL -> quarantined to {qdir}: {reason[:200]}", None

    print(f"  [postverify] FAIL on {opt_file.name}; bisecting "
          f"{len(training_pairs)} edits...", flush=True)
    kept, status = _bisect_recover(lean_file, opt_file, training_pairs)
    if kept:
        print(f"  [postverify] {status}", flush=True)
        return True, f"recovered via bisect: {status}", kept

    qdir = _quarantine_unverified(lean_file, opt_file, reason)
    return False, (f"[postverify] FAIL -> quarantined to {qdir}: "
                   f"{reason[:200]} ({status})"), None


def run_lean_optimizer(workspace_dir: Path, lean_file: Path, timeout: int = 1800,
                       extra_lean_args: Optional[Sequence[str]] = None) -> Tuple[str, int]:
    """
    Run the Lean LeanPolish executable on a file.
    Returns (stdout, exit_code).

    Uses streaming I/O so the user sees real-time progress instead of a
    silent wait.  Default timeout is 1800s (30 min) : safety net for heavy
    proofs.  The Lean optimizer has its own adaptive time guards internally.

    extra_lean_args: ablation flags forwarded verbatim to the Lean binary
    (e.g. ['--skip-phase1', '--no-g3']).
    """
    rel_path = lean_file.resolve().relative_to(workspace_dir.resolve())
    extra = list(extra_lean_args or [])
    # Use compiled binary (much faster than interpreter mode).
    # Falls back to interpreter if binary not found.
    binary = workspace_dir / ".lake" / "build" / "bin" / "LeanPolish"
    if binary.exists():
        cmd = ["stdbuf", "-oL", "lake", "env", str(binary), *extra, str(rel_path)]
    else:
        cmd = ["stdbuf", "-oL", "lake", "env", "lean", "--threads=4",
               "--run", "LeanPolish.lean", *extra, str(rel_path)]
    proc = None
    output_lines: List[str] = []
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(workspace_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            start_new_session=True,
        )
        assert proc.stdout is not None

        def _kill_group():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()

        timer = threading.Timer(timeout, _kill_group)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)
                if line.startswith("[FILE] ") or line.startswith("[IMPORTS LOADED]") or \
                   line.startswith("[DONE]") or line.startswith("[AST ELABORATED]") or \
                   line.startswith("[VERIFIED]") or line.startswith("[FILE_ERROR]") or \
                   line.startswith("[TIMEOUT]"):
                    print(f"  {line}", flush=True)
        finally:
            timer.cancel()

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_group()
            proc.wait(timeout=5)

        output = "\n".join(output_lines)
        return output, proc.returncode or 0
    except subprocess.TimeoutExpired:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                if proc: proc.kill()
        return f"[TIMEOUT] LeanPolish exceeded {timeout}s", 1
    except Exception as e:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return f"[ERROR] {e}", 1


def parse_optimizer_output(output: str) -> dict:
    """Parse structured info from LeanPolish stdout."""
    info = {
        "applied": 0,
        "candidates": 0,
        "selected": 0,
        "dead_code_detected": 0,
        "dead_code_removed": 0,
        "tactic_replacements": 0,
        "output_file": None,
        "applying": [],
        "training_pairs": [],
    }
    for line in output.splitlines():
        if line.startswith("[CANDIDATES]"):
            m = re.search(r"(\d+)", line)
            if m:
                info["candidates"] = int(m.group(1))
        elif line.startswith("[SELECTED]"):
            m = re.search(r"(\d+)", line)
            if m:
                info["selected"] = int(m.group(1))
        elif line.startswith("[DONE]"):
            m = re.search(r"(\d+) replacements", line)
            if m:
                info["applied"] = int(m.group(1))
        elif line.startswith("[NATIVE_DEAD_CODE]"):
            info["dead_code_detected"] = info.get("dead_code_detected", 0) + 1
        elif line.startswith("[APPLYING]"):
            info["applying"].append(line)
        elif line.startswith("[TRAINING_PAIR]"):
            try:
                pair = json.loads(line[len("[TRAINING_PAIR]"):].strip())
                info["training_pairs"].append(pair)
            except json.JSONDecodeError:
                pass
        elif line.startswith("[REJECTED_PAIR]"):
            # Negative-example pair emitted alongside an accepted candidate.
            # Shares `attempt_id` with its winner so RL pipelines can build
            # contrastive (chosen, rejected) tuples per goal state.
            try:
                pair = json.loads(line[len("[REJECTED_PAIR]"):].strip())
                info["training_pairs"].append(pair)
            except json.JSONDecodeError:
                pass
        elif line.startswith("[JSON]"):
            try:
                j = json.loads(line[6:].strip())
                info.update(j)
            except json.JSONDecodeError:
                pass
    return info


def split_multi_file_output(output: str) -> dict:
    """Split multi-file output by [FILE] markers. Returns {rel_path: section_output}."""
    sections = {}
    current_path = None
    current_lines = []
    for line in output.splitlines():
        if line.startswith("[FILE] "):
            if current_path is not None:
                sections[current_path] = "\n".join(current_lines)
            current_path = line[7:].strip()
            current_lines = []
        elif current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        sections[current_path] = "\n".join(current_lines)
    return sections


def _finalise_result(lean_file: Path, original_text: str,
                     info: dict, result: OptimizationResult) -> dict:
    """Post-verify, bisect, fill `result`, and write `<stem>_report.json`.

    Shared between single-file (`optimize_file`) and batched
    (`_build_result_from_section`) entry points so that the two paths
    cannot drift in their handling of soundness, fields, or report shape.

    `info` is the parsed orchestrator output (see `parse_optimizer_output`).
    Caller is responsible for any pre-checks (file existence, completion
    marker, exit code). On entry `result` should already have
    `source_file`, `original_lines`, and any pre-existing `error` string set.

    Returns the report dict that was written to disk (callers may want to
    log/append it; not strictly required).
    """
    original_lines = result.original_lines
    result.replacements_applied = info.get("applied", 0)
    result.dead_code_blocks = info.get("dead_code_removed", 0)
    # Initial value from the in-process verifier; soundness is established
    # by the fresh `lake env lean` post-verify step below.
    result.verified = bool(info.get("verified", False))

    opt_file = lean_file.with_name(lean_file.stem + "_shortened.lean")
    if opt_file.exists():
        verified, msg, kept = _postverify_with_bisect(
            lean_file, opt_file, info.get("training_pairs", []))
        if verified:
            result.verified = True
            if kept is not None:
                # Bisect dropped some edits; reflect ground truth.
                result.bisect_dropped = (
                    len(info.get("training_pairs", [])) - len(kept))
                info["training_pairs"] = kept
                info["tactic_replacements"] = len(kept)
                result.replacements_applied = len(kept)
        else:
            result.verified = False
            result.error = msg if not result.error else f"{result.error}; {msg}"
        if opt_file.exists():
            opt_text = opt_file.read_text()
            result.optimized_lines = len(opt_text.splitlines())
            result.output_file = str(opt_file)
        else:
            result.optimized_lines = original_lines
    else:
        result.optimized_lines = original_lines

    result.bytes_original = info.get("bytes_original", len(original_text.encode()))
    result.bytes_shortened = (
        len(opt_file.read_text().encode()) if opt_file.exists()
        else info.get("bytes_shortened", result.bytes_original)
    )
    result.tokens_original = info.get("tokens_original", 0)
    result.tokens_shortened = info.get("tokens_shortened", result.tokens_original)
    result.lines_original = info.get("lines_original", 0)
    result.lines_shortened = info.get("lines_shortened", result.lines_original)
    # Provenance enrichment: stamp every accepted+rejected pair with
    # commit_sha, mathlib_rev, and content_sha256 of its source file.
    # See module-level `_enrich_pair_with_provenance` for the failure mode
    # (file-version drift) this defends against.
    project_root = _find_lake_root(lean_file.parent)
    for pair in info.get("training_pairs", []):
        _enrich_pair_with_provenance(pair, project_root)
    result.training_pairs = info.get("training_pairs", [])

    report = {
        "file": str(lean_file),
        "bytes_original": result.bytes_original,
        "bytes_shortened": result.bytes_shortened,
        "bytes_saved": result.bytes_saved,
        "tokens_original": result.tokens_original,
        "tokens_shortened": result.tokens_shortened,
        "tokens_saved": result.tokens_saved,
        "lines_original": result.lines_original,
        "lines_shortened": result.lines_shortened,
        "lines_saved": result.lines_saved,
        "tactic_replacements": info.get("tactic_replacements", result.replacements_applied),
        "dead_code_detected": info.get("dead_code_detected", 0),
        "dead_code_removed": result.dead_code_blocks,
        "bisect_dropped": result.bisect_dropped,
        "verified": result.verified,
        "rounds": info.get("rounds", "?"),
        # L2 anti-unification + G3 generalization gate stats
        # (passed through from the binary's [JSON] line).
        "l2_antiun_applied": info.get("l2_antiun_applied", 0),
        "l2_detections": info.get("l2_detections", 0),
        "l2_groups": info.get("l2_groups", 0),
        "l2_g3_rejected": info.get("l2_g3_rejected", 0),
        "warning_cleanups": info.get("warning_cleanups", 0),
        "training_pairs": result.training_pairs,
    }
    report_file = lean_file.with_name(lean_file.stem + "_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    return report


def _build_result_from_section(lean_file: Path, section_output: str, workspace_dir: Path) -> OptimizationResult:
    """Build an OptimizationResult from a single file's optimizer output section."""
    lean_file = lean_file.resolve()
    if not lean_file.exists():
        return OptimizationResult(source_file=str(lean_file), error="File not found")

    original_text = lean_file.read_text()
    original_lines = len(original_text.splitlines())
    result = OptimizationResult(source_file=str(lean_file), original_lines=original_lines)

    if not section_output or ("[DONE]" not in section_output and "[JSON]" not in section_output):
        result.error = (
            f"No completion marker: {section_output[:300]}"
            if section_output else "No output from optimizer"
        )
        return result

    info = parse_optimizer_output(section_output)
    _finalise_result(lean_file, original_text, info, result)
    return result


def _run_file_group(workspace_dir: Path, group_files: List[Path],
                    threads: int = 2, timeout_per_file: int = 300,
                    extra_lean_args: Optional[Sequence[str]] = None) -> List[OptimizationResult]:
    """Run optimizer on a group of files with shared Mathlib (one Lean process).

    Streams Lean stdout/stderr line-by-line so the user sees real-time progress
    ([IMPORTS LOADED], [FILE], [DONE], etc.) instead of a silent wait.
    """
    # Find the Lake project root (directory containing lakefile.lean)
    lake_root = _find_lake_root(workspace_dir)
    rel_paths = [str(f.resolve().relative_to(lake_root.resolve())) for f in group_files]
    extra = list(extra_lean_args or [])
    binary = lake_root / ".lake" / "build" / "bin" / "LeanPolish"
    if binary.exists():
        cmd = ["stdbuf", "-oL", "lake", "env", str(binary), *extra] + rel_paths
    else:
        cmd = ["stdbuf", "-oL", "lake", "env", "lean",
               f"--threads={threads}", "--run", "LeanPolish.lean", *extra] + rel_paths
    timeout_total = timeout_per_file * len(group_files) + 120  # +120s for Mathlib load

    output_lines: List[str] = []
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(lake_root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,  # line-buffered
            start_new_session=True,  # new process group so we can kill all children
        )
        assert proc.stdout is not None
        # Watchdog timer: kill entire process group if timeout exceeded
        # (plain proc.kill only kills stdbuf; lake/lean survive as orphans).
        def _kill_group():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        timer = threading.Timer(timeout_total, _kill_group)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)
                # Print progress markers so the user sees something
                if line.startswith("[FILE] ") or line.startswith("[IMPORTS LOADED]") or \
                   line.startswith("[DONE]") or line.startswith("[AST ELABORATED]") or \
                   line.startswith("[FILE_ERROR]") or line.startswith("[TIMEOUT]"):
                    print(f"  [lean] {line}", flush=True)
        finally:
            timer.cancel()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            # Lean runtime hung on shutdown : kill the whole group
            print("  [lean] Process hung on shutdown, killing", flush=True)
            _kill_group()
            proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        return [OptimizationResult(source_file=str(f), error="Group timeout") for f in group_files]
    except Exception as e:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return [OptimizationResult(source_file=str(f), error=str(e)) for f in group_files]

    output = "\n".join(output_lines)
    sections = split_multi_file_output(output)
    results = []
    for f in group_files:
        rel = str(f.resolve().relative_to(lake_root.resolve()))
        section = sections.get(rel, "")
        r = _build_result_from_section(f, section, lake_root)
        results.append(r)
    return results


def optimize_file(lean_file: Path, lean_timeout: int = 1800,
                  extra_lean_args: Optional[Sequence[str]] = None) -> OptimizationResult:
    """
    Full optimization pipeline for a single Lean file.

    LeanPolish handles verification in-process (re-elaborating with the
    already-loaded Mathlib environment).  The Python side just orchestrates
    the call and reports results.
    """
    lean_file = Path(lean_file).resolve()
    if not lean_file.exists():
        return OptimizationResult(
            source_file=str(lean_file),
            error=f"File not found: {lean_file}",
        )

    workspace_dir = find_workspace_dir(lean_file)
    original_text = lean_file.read_text()
    original_lines = len(original_text.splitlines())

    result = OptimizationResult(
        source_file=str(lean_file),
        original_lines=original_lines,
    )

    # Remove any stale _shortened.lean / _report.json left by a previous run.
    # The orchestrator emits no output for a file with nothing to shorten, so
    # a leftover artifact would otherwise be re-validated by post-verify.
    pre_opt = lean_file.with_name(lean_file.stem + "_shortened.lean")
    pre_rep = lean_file.with_name(lean_file.stem + "_report.json")
    for stale in (pre_opt, pre_rep):
        try:
            if stale.exists():
                stale.unlink()
        except OSError:
            pass

    # Run Lean optimizer (includes in-process verification)
    print(f"Running LeanPolish on {lean_file.name}...")
    output, exit_code = run_lean_optimizer(workspace_dir, lean_file, timeout=lean_timeout,
                                           extra_lean_args=extra_lean_args)

    if exit_code != 0 and "[DONE]" not in output:
        result.error = f"LeanPolish failed (exit {exit_code}): {output[:500]}"
        return result

    info = parse_optimizer_output(output)
    _finalise_result(lean_file, original_text, info, result)

    report_file = lean_file.with_name(lean_file.stem + "_report.json")
    print(f"  Report → {report_file.name}")

    # Append training pairs to rl_training_data.jsonl in the workspace
    training_pairs = result.training_pairs
    if training_pairs:
        rl_file = workspace_dir / "rl_training_data.jsonl"
        with open(rl_file, "a") as f:
            for pair in training_pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        print(f"  Training data → {rl_file.name} (+{len(training_pairs)} pairs)")

    # Display comparison stats
    print(f"  {info.get('candidates', '?')} candidates → {info.get('selected', '?')} selected → "
          f"{result.replacements_applied} verified ({info.get('rounds', '?')} rounds)")
    print(f"  Bytes:  {result.bytes_original} → {result.bytes_shortened} "
          f"({result.bytes_saved} saved, {result.bytes_saved*100//max(result.bytes_original,1)}%)")
    if result.tokens_original > 0:
        print(f"  Tokens: {result.tokens_original} → {result.tokens_shortened} "
              f"({result.tokens_saved} saved, {result.tokens_saved*100//max(result.tokens_original,1)}%)")
    if result.lines_original > 0:
        print(f"  Lines:  {result.lines_original} → {result.lines_shortened} "
              f"({result.lines_saved} saved, {result.lines_saved*100//max(result.lines_original,1)}%)")
    if training_pairs:
        categories: dict = {}
        for pair in training_pairs:
            kind = pair.get("kind", "?")
            if kind == "dead_have":
                categories["dead_code_removal"] = categories.get("dead_code_removal", 0) + 1
            else:
                repl = pair.get("replacement", "?")
                core = repl[3:].strip() if repl.startswith("by ") else repl
                categories[core] = categories.get(core, 0) + 1
        cats_str = ", ".join(f"{t}: {n}" for t, n in sorted(categories.items(), key=lambda x: -x[1]))
        print(f"  Categories: {cats_str}")
    print(f"  Dead code: {info.get('dead_code_detected', 0)} detected, "
          f"{result.dead_code_blocks} removed")
    if result.bisect_dropped:
        print(f"  Bisect: dropped {result.bisect_dropped} edits to keep file fresh-kernel sound")

    return result


def batch_optimize(workspace_dir: Path, chunk_size: int = 20,
                   threads: int = 2, timeout_per_file: int = 300,
                   extra_lean_args: Optional[Sequence[str]] = None) -> List[OptimizationResult]:
    """Optimize all .lean proof files found under the workspace.

    Files are processed in chunks of `chunk_size`.  Each chunk spawns one Lean
    process that loads Mathlib once and processes all files sequentially.  After
    each chunk the Lean process exits and its memory is freed.
    """
    workspace_dir = Path(workspace_dir).resolve()
    lean_files = _discover_proof_files(workspace_dir)

    if not lean_files:
        print(f"No .lean proof files found under {workspace_dir}")
        return []

    # Skip files that already have a _report.json
    remaining = []
    skipped = 0
    for f in lean_files:
        report = f.with_name(f.stem + "_report.json")
        if report.exists():
            skipped += 1
        else:
            remaining.append(f)

    if skipped:
        print(f"Skipping {skipped} already-processed files (have _report.json).")
    lean_files = remaining

    if not lean_files:
        print("All files already processed.")
        return []

    # Split into chunks
    chunks = [lean_files[i:i + chunk_size] for i in range(0, len(lean_files), chunk_size)]
    n_chunks = len(chunks)
    mathlib_overhead = n_chunks * 12  # ~12s per Mathlib load (cached oleans)
    print(f"Found {len(lean_files)} proof files → {n_chunks} chunk(s) of ≤{chunk_size} "
          f"(Mathlib loaded {n_chunks} time(s), ~{mathlib_overhead}s import overhead).\n",
          flush=True)
    results: List[OptimizationResult] = []
    done_count = 0

    for ci, chunk in enumerate(chunks, 1):
        print(f"\n── Chunk {ci}/{n_chunks} ({len(chunk)} files) ──", flush=True)
        chunk_results = _run_file_group(workspace_dir, chunk,
                                        threads=threads,
                                        timeout_per_file=timeout_per_file,
                                        extra_lean_args=extra_lean_args)
        for r in chunk_results:
            done_count += 1
            results.append(r)
            print(f"[{done_count}/{len(lean_files)}] {r.summary()}", flush=True)

    _print_batch_summary(results, workspace_dir)

    return results


def _discover_proof_files(workspace_dir: Path) -> List[Path]:
    """Find all .lean proof files under workspace_dir, excluding generated/infra files."""
    return sorted(
        f for f in workspace_dir.rglob("*.lean")
        if not f.name.endswith("_shortened.lean")
        and not f.name.endswith("_report.lean")
        and f.name not in _INFRA_FILE_NAMES
        and ".lake" not in f.parts
    )


def _worker_run_chunk(args_tuple):
    """Top-level function for ProcessPoolExecutor (must be picklable).
    Runs a chunk of files in a single Lean process (shared Mathlib load).
    Returns a list of serializable result dicts (not OptimizationResult objects,
    because dataclasses with complex fields don't always pickle cleanly).
    """
    # Accept both 5-tuples (no extra_lean_args) and 6-tuples.
    if len(args_tuple) == 5:
        workspace_dir, chunk_files, threads, timeout_per_file, worker_id = args_tuple
        extra = []
    else:
        workspace_dir, chunk_files, threads, timeout_per_file, worker_id, extra = args_tuple
        extra = list(extra or [])
    workspace_dir = Path(workspace_dir)
    chunk_files = [Path(f) for f in chunk_files]
    lake_root = _find_lake_root(workspace_dir)

    rel_paths = [str(f.resolve().relative_to(lake_root.resolve())) for f in chunk_files]
    binary = lake_root / ".lake" / "build" / "bin" / "LeanPolish"
    if binary.exists():
        cmd = ["stdbuf", "-oL", "lake", "env", str(binary), *extra] + rel_paths
    else:
        cmd = ["stdbuf", "-oL", "lake", "env", "lean",
               f"--threads={threads}", "--run", "LeanPolish.lean", *extra] + rel_paths
    timeout_total = timeout_per_file * len(chunk_files) + 120

    _t_chunk0 = time.monotonic()
    output_lines = []
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(lake_root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            start_new_session=True,
        )
        assert proc.stdout is not None
        def _kill_group():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        timer = threading.Timer(timeout_total, _kill_group)
        timer.start()
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                output_lines.append(line)
                if line.startswith("[FILE] ") or line.startswith("[DONE]") or \
                   line.startswith("[FILE_ERROR]") or line.startswith("[TIMEOUT]"):
                    print(f"  [W{worker_id}] {line}", flush=True)
        finally:
            timer.cancel()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            print(f"  [W{worker_id}] Process hung on shutdown, killing", flush=True)
            _kill_group()
            proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
        return [{"source_file": str(f), "error": "Timeout"} for f in chunk_files]
    except Exception as e:
        if proc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
        return [{"source_file": str(f), "error": str(e)} for f in chunk_files]

    output = "\n".join(output_lines)
    # Optionally dump the raw Lean stdout (incl. [MENU_POOL] lines) and the
    # chunk wall-clock (= per-file wall-clock with --chunk-size 1).
    _rawdir = os.environ.get("LEANPOLISH_RAWLOG_DIR")
    if _rawdir:
        try:
            os.makedirs(_rawdir, exist_ok=True)
            _tag = rel_paths[0].replace("/", "__")
            with open(os.path.join(_rawdir, _tag + ".log"), "w") as _fh:
                _fh.write(f"[CHUNK_FILES] {json.dumps(rel_paths)}\n")
                _fh.write(f"[CHUNK_WALL_S] {time.monotonic() - _t_chunk0:.1f}\n")
                _fh.write(output)
        except OSError:
            pass
    sections = split_multi_file_output(output)

    results = []
    for f in chunk_files:
        rel = str(f.resolve().relative_to(lake_root.resolve()))
        section = sections.get(rel, "")
        r = _build_result_from_section(f, section, lake_root)
        results.append({
            "source_file": r.source_file,
            "output_file": r.output_file,
            "original_lines": r.original_lines,
            "optimized_lines": r.optimized_lines,
            "replacements_applied": r.replacements_applied,
            "dead_code_blocks": r.dead_code_blocks,
            "verified": r.verified,
            "error": r.error,
            "bytes_original": r.bytes_original,
            "bytes_shortened": r.bytes_shortened,
            "training_pairs": r.training_pairs,
        })
    return results


def parallel_batch_optimize(workspace_dir: Path, workers: int = 4,
                            chunk_size: int = 5, threads: int = 2,
                            timeout_per_file: int = 300,
                            extra_lean_args: Optional[Sequence[str]] = None) -> List[OptimizationResult]:
    """Optimize all proofs using multiple parallel Lean processes.

    Each worker spawns one Lean process that loads Mathlib once, then processes
    its chunk of files sequentially.  Multiple workers run simultaneously via
    ProcessPoolExecutor, giving true OS-level parallelism.

    Optimal settings:
      - workers: number of parallel Lean processes (1 per ~4 CPU cores)
      - chunk_size: files per Lean process (5-10 balances Mathlib load vs memory)
      - threads: Lean threads per process (2-4)
      - Total CPU usage: workers * threads cores
    """
    workspace_dir = Path(workspace_dir).resolve()
    lean_files = _discover_proof_files(workspace_dir)

    if not lean_files:
        print(f"No .lean proof files found under {workspace_dir}")
        return []

    # Skip already-processed files
    remaining = []
    skipped = 0
    for f in lean_files:
        report = f.with_name(f.stem + "_report.json")
        if report.exists():
            skipped += 1
        else:
            remaining.append(f)

    if skipped:
        print(f"Skipping {skipped} already-processed files (have _report.json).")
    lean_files = remaining

    if not lean_files:
        print("All files already processed.")
        return []

    # Split into chunks, then distribute chunks across workers
    chunks = [lean_files[i:i + chunk_size] for i in range(0, len(lean_files), chunk_size)]
    n_chunks = len(chunks)
    effective_workers = min(workers, n_chunks)

    est_mathlib_loads = n_chunks  # one per chunk
    est_time_serial = len(lean_files) * 100  # ~100s per proof average
    est_time_parallel = (est_time_serial / effective_workers) + (est_mathlib_loads / effective_workers * 12)

    print(f"Found {len(lean_files)} proof files -> {n_chunks} chunks of <={chunk_size}")
    print(f"Workers: {effective_workers} parallel Lean processes x {threads} threads each")
    print(f"Estimated: ~{est_time_parallel/60:.0f} min parallel vs ~{est_time_serial/60:.0f} min serial")
    print(flush=True)

    # Build worker arguments. Tuple includes extra_lean_args (ablation flags
    # forwarded verbatim to the Lean binary).
    extra = list(extra_lean_args or [])
    worker_args = [
        (str(workspace_dir), [str(f) for f in chunk], threads, timeout_per_file, i % effective_workers, extra)
        for i, chunk in enumerate(chunks)
    ]

    results: List[OptimizationResult] = []
    start_time = time.monotonic()

    with ProcessPoolExecutor(max_workers=effective_workers) as executor:
        futures = {executor.submit(_worker_run_chunk, args): args for args in worker_args}
        done_count = 0
        for future in as_completed(futures):
            try:
                chunk_results = future.result()
            except Exception as e:
                args = futures[future]
                chunk_results = [{"source_file": f, "error": str(e)} for f in args[1]]

            for rd in chunk_results:
                done_count += 1
                r = OptimizationResult(
                    source_file=rd["source_file"],
                    output_file=rd.get("output_file"),
                    original_lines=int(rd.get("original_lines", 0)),
                    optimized_lines=int(rd.get("optimized_lines", 0)),
                    replacements_applied=int(rd.get("replacements_applied", 0)),
                    dead_code_blocks=int(rd.get("dead_code_blocks", 0)),
                    verified=bool(rd.get("verified", False)),
                    error=rd.get("error"),
                    bytes_original=int(rd.get("bytes_original", 0)),
                    bytes_shortened=int(rd.get("bytes_shortened", 0)),
                    training_pairs=rd.get("training_pairs") or [],  # type: ignore[arg-type]
                )
                results.append(r)
                print(f"[{done_count}/{len(lean_files)}] {r.summary()}", flush=True)

    elapsed = time.monotonic() - start_time

    # Print summary
    _print_batch_summary(results, workspace_dir, elapsed)
    return results


def _print_batch_summary(results: List[OptimizationResult], workspace_dir: Path,
                         elapsed: float = 0):
    """Print summary and write consolidated outputs."""
    print(f"\n{'='*60}")
    print("BATCH SUMMARY")
    print(f"{'='*60}")
    total_bytes_orig = sum(r.bytes_original for r in results)
    total_bytes_short = sum(r.bytes_shortened for r in results)
    total_bytes_saved = total_bytes_orig - total_bytes_short
    total_tokens_orig = sum(r.tokens_original for r in results)
    total_tokens_short = sum(r.tokens_shortened for r in results)
    total_tokens_saved = total_tokens_orig - total_tokens_short
    total_lines_orig = sum(r.lines_original for r in results)
    total_lines_short = sum(r.lines_shortened for r in results)
    total_lines_saved = total_lines_orig - total_lines_short
    total_replacements = sum(r.replacements_applied for r in results)
    total_dead = sum(r.dead_code_blocks for r in results)
    verified_count = sum(1 for r in results if r.verified)
    error_count = sum(1 for r in results if r.error)
    total_pairs = sum(len(r.training_pairs) for r in results)
    print(f"Files processed:   {len(results)}")
    print(f"Verified:          {verified_count}/{len(results)}")
    if error_count:
        print(f"Errors:            {error_count}")
    print(f"Replacements:      {total_replacements}")
    print(f"Bytes:             {total_bytes_orig} -> {total_bytes_short} ({total_bytes_saved} saved, {total_bytes_saved*100//max(total_bytes_orig,1)}%)")
    if total_tokens_orig > 0:
        print(f"Tokens:            {total_tokens_orig} -> {total_tokens_short} ({total_tokens_saved} saved, {total_tokens_saved*100//max(total_tokens_orig,1)}%)")
    if total_lines_orig > 0:
        print(f"Lines:             {total_lines_orig} -> {total_lines_short} ({total_lines_saved} saved, {total_lines_saved*100//max(total_lines_orig,1)}%)")
    print(f"Dead code blocks:  {total_dead}")
    print(f"Training pairs:    {total_pairs}")
    if elapsed > 0:
        print(f"Wall time:         {elapsed/60:.1f} min ({elapsed/max(len(results),1):.1f}s/file avg)")

    # Aggregate categories
    all_cats: dict = {}
    for r in results:
        for pair in r.training_pairs:
            repl = pair.get("replacement", "?")
            core = repl[3:].strip() if repl.startswith("by ") else repl
            all_cats[core] = all_cats.get(core, 0) + 1
    if all_cats:
        cats_str = ", ".join(f"{t}: {n}" for t, n in sorted(all_cats.items(), key=lambda x: -x[1]))
        print(f"Categories:        {cats_str}")

    # Write consolidated report and training data
    _write_consolidated_outputs(results, workspace_dir)


def _write_consolidated_outputs(results: List[OptimizationResult], workspace_dir: Path):
    """Write optimization_report.json and rl_training_data.jsonl from results."""
    all_pairs = []
    file_summaries = []
    for r in results:
        file_summaries.append({
            "file": r.source_file,
            "bytes_saved": r.bytes_saved,
            "tokens_saved": r.tokens_saved,
            "lines_saved": r.lines_saved,
            "tactic_replacements": r.replacements_applied,
            "dead_code_removed": r.dead_code_blocks,
            "verified": r.verified,
            "error": r.error,
        })
        all_pairs.extend(r.training_pairs)

    # Also pull in any existing _report.json files not in current results
    processed_files = {r.source_file for r in results}
    for rf in sorted(workspace_dir.rglob("*_report.json")):
        try:
            file_report = json.loads(rf.read_text())
            src = file_report.get("file", "")
            if src not in processed_files:
                file_summaries.append({
                    "file": src,
                    "bytes_saved": file_report.get("bytes_saved", 0),
                    "tactic_replacements": file_report.get("tactic_replacements", 0),
                    "dead_code_removed": file_report.get("dead_code_removed", 0),
                })
                all_pairs.extend(file_report.get("training_pairs", []))
        except (json.JSONDecodeError, OSError):
            pass

    combined_report = {
        "total_files": len(file_summaries),
        "total_bytes_saved": sum(f.get("bytes_saved", 0) for f in file_summaries),
        "total_tokens_saved": sum(f.get("tokens_saved", 0) for f in file_summaries),
        "total_lines_saved": sum(f.get("lines_saved", 0) for f in file_summaries),
        "total_replacements": sum(f.get("tactic_replacements", 0) for f in file_summaries),
        "total_dead_code_removed": sum(f.get("dead_code_removed", 0) for f in file_summaries),
        "total_training_pairs": len(all_pairs),
        "files": file_summaries,
    }
    combined_path = workspace_dir / "optimization_report.json"
    with open(combined_path, "w") as f:
        json.dump(combined_report, f, indent=2)
    print(f"\nCombined report: {combined_path}")

    # Write consolidated rl_training_data.jsonl
    rl_path = workspace_dir / "rl_training_data.jsonl"
    with open(rl_path, "w") as f:
        for pair in all_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"Training data: {len(all_pairs)} pairs -> {rl_path}")


# ===================================
# CLI
# ===================================

def main():
    parser = argparse.ArgumentParser(
        description="Run LeanPolish on a Lean file or corpus directory"
    )
    parser.add_argument(
        "target",
        help="Path to a .lean file or workspace directory (with --batch)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Optimize all .lean proof files under the target directory",
    )
    parser.add_argument(
        "--chunk-size", "-c",
        type=int,
        default=None,
        help="Files per Lean process (default 20). Smaller = less memory.",
    )
    parser.add_argument(
        "--threads", "-t",
        type=int,
        default=None,
        help="Lean threads per process (default 2).",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help="Number of parallel Lean processes (default 1). Each loads Mathlib "
             "independently. Set to N_CPUs / threads for best throughput.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Timeout per file in seconds (default 300).",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Do not run LeanPolish. Collect existing _report.json files into "
             "optimization_report.json and rl_training_data.jsonl.",
    )
    parser.add_argument(
        "--laptop",
        action="store_true",
        help="Local preset: --workers=1 --threads=1 --chunk-size=5 --timeout=300. "
             "Processes 5 files per Lean process to reduce Mathlib reload overhead.",
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="Medium parallel preset: --workers=8 --threads=4 --chunk-size=5 --timeout=600. "
             "Uses 32 cores total (8 processes x 4 threads).",
    )
    parser.add_argument(
        "--cluster",
        action="store_true",
        help="Large parallel preset: --workers=16 --threads=4 --chunk-size=5 --timeout=900. "
             "Uses 64 cores total (16 processes x 4 threads).",
    )
    # ----- Phase / quality ablation flags -----
    # Forwarded verbatim to the LeanPolish binary (parsed in `main` of
    # LeanPolish.lean).
    parser.add_argument("--skip-phase1", action="store_true",
        help="Ablation: disable Phase 1 (tactic replacement).")
    parser.add_argument("--skip-l2", action="store_true",
        help="Ablation: disable Phase 1.5 (L2 anti-unification + G3 gate).")
    parser.add_argument("--skip-dead-code", action="store_true",
        help="Ablation: disable Phase 2 (dead-code removal).")
    parser.add_argument("--skip-cleanup", action="store_true",
        help="Ablation: disable Phase 3 (warning-guided cleanup).")
    parser.add_argument("--no-quality-gate", action="store_true",
        help="Ablation: accept shortest valid tactic regardless of specificity tier.")
    parser.add_argument("--no-g3", action="store_true",
        help="Ablation: disable G3 generalization gate inside L2.")
    parser.add_argument("--complete-menu", action="store_true",
        help="Complete-menu mode: try the whole automation menu and keep the shortest quality-passing success.")
    parser.add_argument("--menu-timeout-all", action="store_true",
        help="Apply a 5 s budget to every menu entry (use with --complete-menu).")
    args = parser.parse_args()

    # Resolve presets. Explicit user flags (anything that survived as a
    # non-None value) always win over preset defaults.
    DEFAULTS = {"workers": 1, "threads": 2, "chunk_size": 20, "timeout": 300}
    PRESETS = {
        "laptop":  {"workers": 1,  "threads": 1, "chunk_size": 5, "timeout": 300},
        "server":  {"workers": 8,  "threads": 4, "chunk_size": 5, "timeout": 600},
        "cluster": {"workers": 16, "threads": 4, "chunk_size": 5, "timeout": 900},
    }
    chosen = next((p for p in ("laptop", "server", "cluster") if getattr(args, p)), None)
    preset = PRESETS[chosen] if chosen else {}
    for key, default_val in DEFAULTS.items():
        if getattr(args, key) is None:
            setattr(args, key, preset.get(key, default_val))

    # Collect ablation flags to forward to the Lean binary.
    extra_lean_args: List[str] = []
    for flag, attr in [
        ("--skip-phase1",     "skip_phase1"),
        ("--skip-l2",         "skip_l2"),
        ("--skip-dead-code",  "skip_dead_code"),
        ("--skip-cleanup",    "skip_cleanup"),
        ("--no-quality-gate", "no_quality_gate"),
        ("--no-g3",           "no_g3"),
        ("--complete-menu",   "complete_menu"),
        ("--menu-timeout-all", "menu_timeout_all"),
    ]:
        if getattr(args, attr, False):
            extra_lean_args.append(flag)
    if extra_lean_args:
        print(f"[ABLATION] Forwarding to Lean: {' '.join(extra_lean_args)}", flush=True)

    target = Path(args.target).resolve()

    if args.collect_only:
        if not target.is_dir():
            print(f"Error: {target} is not a directory", file=sys.stderr)
            sys.exit(1)
        # Just collect existing reports
        dummy_results: List[OptimizationResult] = []
        for rf in sorted(target.rglob("*_report.json")):
            try:
                rpt = json.loads(rf.read_text())
                dummy_results.append(OptimizationResult(
                    source_file=rpt.get("file", str(rf)),
                    bytes_original=rpt.get("bytes_original", 0),
                    bytes_shortened=rpt.get("bytes_shortened", 0),
                    replacements_applied=rpt.get("tactic_replacements", 0),
                    dead_code_blocks=rpt.get("dead_code_removed", 0),
                    verified=rpt.get("verified", False),
                    training_pairs=rpt.get("training_pairs", []),
                ))
            except (json.JSONDecodeError, OSError):
                pass
        _print_batch_summary(dummy_results, target)
        sys.exit(0)

    if args.batch:
        if not target.is_dir():
            print(f"Error: {target} is not a directory", file=sys.stderr)
            sys.exit(1)
        print(f"Config: workers={args.workers}, threads={args.threads}, "
              f"chunk_size={args.chunk_size}, timeout={args.timeout}s/file", flush=True)
        if args.workers > 1:
            results = parallel_batch_optimize(
                target, workers=args.workers, chunk_size=args.chunk_size,
                threads=args.threads, timeout_per_file=args.timeout,
                extra_lean_args=extra_lean_args)
        else:
            results = batch_optimize(target, chunk_size=args.chunk_size,
                                     threads=args.threads,
                                     timeout_per_file=args.timeout,
                                     extra_lean_args=extra_lean_args)
        # Exit code policy:
        #   0 = every file either fresh-kernel verified OR had nothing to
        #       shorten (no error). Quarantines and orchestrator failures
        #       count as failure.
        sys.exit(0 if all(r.verified or r.error is None for r in results) else 1)
    else:
        if not target.is_file():
            print(f"Error: {target} is not a file", file=sys.stderr)
            sys.exit(1)

        result = optimize_file(target, lean_timeout=args.timeout,
                               extra_lean_args=extra_lean_args)
        print(f"\n{result.summary()}")
        # Same policy as the batch path above.
        sys.exit(0 if result.verified or result.error is None else 1)


if __name__ == "__main__":
    main()
