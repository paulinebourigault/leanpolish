# Datasheet — LeanPolish Proof Compression Dataset

Following Gebru et al., *Datasheets for Datasets* (2018, updated 2021).
This document describes the *LeanPolish — Lean Proof Compression* dataset.

## 1. Motivation

**Q1.1 For what purpose was the dataset created?**
To provide a large, kernel-verified corpus of *short-vs-long proof
rewrite pairs* for Lean 4 theorem-proving corpora. The dataset is designed for
training models that learn to (a) compress proofs, (b) select more
elegant tactics, and (c) be trained with DPO/RL using the contrastive
`(accepted, rejected)` siblings emitted by `LeanPolish`.

**Q1.2 Who created it?**
Anonymous authors.

**Q1.3 Who funded the creation?**
Withheld for anonymity.

## 2. Composition

**Q2.1 What do the instances represent?**
Each instance is a **proof rewrite candidate**: an `(original,
replacement)` pair, the goal state at the rewrite site, file/byte
location, full provenance, and a per-attempt outcome
(`accepted` / `rejected`). See the Hugging Face dataset card, §"Row schema", for
the full field list.

**Q2.2 How many instances total?**
The released shards contain 33,402 accepted training pairs and 65,596
deduplicated contrastive rejected siblings. These accepted rows cover 12,972
distinct Lean source files; per-shard file counts sum to 12,981 because
the two Putnam 2025 scheduler shards intentionally rerun the same
AxiomProver files while preserving scheduler-specific provenance. The release
also includes 12,468 L2 detection rows.

**Q2.3 Does the dataset contain all possible instances or is it a sample?**
*Sample*. We process every file in each corpus, but a row is only
emitted when `LeanPolish` finds a kernel-verified shortening (or
rejected sibling under the same `attempt_id`). Files that elaborate
to no candidates contribute zero rows.

**Q2.4 What data does each instance consist of?**
Plain-text Lean source fragments (`original`, `replacement`),
pretty-printed goal states, integer counters, classification labels,
and provenance hashes.

**Q2.5 Is there a label or target?**
Yes: `outcome ∈ {accepted, rejected}` and `rank_in_attempt`. For
DPO/RL, the natural target is the contrast between an `accepted`
winner and its sibling `rejected` rows under the same `attempt_id`.

**Q2.6 Is any information missing?**
Some fields are null by construction in particular splits: for example,
accepted training rows do not carry rejected-sibling failure metadata, and
rejected rows do not carry winner-only failed-attempt lists. The 12,468 L2
detection rows are included for auditability and are not part of the primary
accepted/rejected training splits. See *Known limitations* in the dataset card.

**Q2.7 Are there relationships between instances?**
Yes:
- Rows sharing an `attempt_id` belong to the same rewrite attempt
  (one winner + N rejected siblings).
- Rows sharing a `(file, content_sha256)` belong to the same source
  declaration.
- Rows sharing `git_sha` + `mathlib_rev` come from a single reproducible
  optimizer/toolchain provenance block. The `commit_sha` field is null in
  this release; use `git_sha` and `shards/MANIFEST.json`.

**Q2.8 Are there recommended splits?**
Splits are **by source corpus/configuration**, not random. The Hugging Face
configs are `mathlib`, `goedel`, `minif2f`, `putnam_bench`,
`putnam_verified`, `putnam2025_per_file`, and `putnam2025_pool`, each with
`training` and `rejected` splits. See `experiments/metrics/results/dedup_leakage.json` for a
goal-state overlap audit between the recommended training corpora (`goedel`,
`mathlib`) and evaluation corpora (`minif2f`, `putnam_verified`).
The `putnam_bench` and `putnam_verified` configs are PutnamBench-derived;
only the `putnam2025_per_file` and `putnam2025_pool` configs are the Putnam
2025 / AxiomProver competition-problem solutions.

**Q2.9 Are there errors, noise, or sources of redundancy?**
- **No known false-positive accepted rewrites in v1.0.0 under the pinned
  environment**: accepted rows are checked by Lean and by file-level
  re-elaboration under Lean 4.21.0 / Mathlib v4.21.0; L2 merges additionally
  use `Meta.check + isDefEq + G3` where applicable. False *negatives* exist:
  many semantically valid shortenings are not discovered.
- *Whitespace noise*: `goal_state` is the Lean pretty-printer
  output. Cosmetic differences may occur across Lean versions.
- *Time noise*: `failed_attempts[*].wall_ms` is wall-clock and
  hardware-dependent; do not use as a feature.

**Q2.10 Self-contained, or external resources?**
Self-contained for the rows. To fully reproduce the dataset you
need: Lean 4.21.0 + Mathlib v4.21.0 (pinned via
`lake-manifest.json`) + the source corpora (Mathlib4, Goedel-Workbook,
miniF2F, PutnamBench, and Putnam 2025 / AxiomProver). These are documented in
`shards/MANIFEST.json` and the repository README.

**Q2.11 Confidential data?** No.
**Q2.12 Offensive/insulting/threatening content?** No.
**Q2.13 Sub-populations?** N/A — formal mathematical proofs.
**Q2.14 PII?** No personal data is present in proof source.
**Q2.15 Sensitive data?** No.

## 3. Collection process

**Q3.1 How was the data acquired?**
- Mathlib4 v4.21.0 was cloned via `lake update`.
- Goedel-Workbook was downloaded via `download_goedel.py`.
- miniF2F, PutnamBench, and Putnam 2025 / AxiomProver were taken from their
  upstream public repositories or embedded snapshots recorded in the release
  manifest.

**Q3.2 What mechanisms were used to collect the data?**
A custom Lean 4 optimizer pipeline (`LeanPolish`) that:
1. Parses each `.lean` file.
2. Enumerates rewrite candidates via tactic synthesis +
   anti-unification.
3. Runs the Lean 4 kernel to verify each candidate.
4. Emits one JSON line per accepted rewrite and per rejected
   sibling.

**Q3.3 If sampling, what strategy?**
Every input file was processed; no random sampling was used at the file level
for the released rows. The G3 wild-corpus audit statistics in
`experiments/metrics/results/g3_sample.json` use a stratified random sample (seed 42, sizes
1500/250) to estimate veto rate; they do not change the released row counts.

**Q3.4 Who was involved in collection?**
Anonymous authors. The optimizer was run on a Linux CPU server; no GPU is required for the optimizer.

**Q3.5 Over what timeframe?** 2026-02 — 2026-05.

**Q3.6 Ethical review?** Not applicable; no human subjects.

## 4. Preprocessing / cleaning / labelling

**Q4.1 Was preprocessing/cleaning/labelling done?**
Yes:
- Source files with elaboration errors are excluded from accepted rows.
- Identity-replacement candidates (linter trivia) are filtered out
  by `audit_training_pairs.py`.
- Failed or lower-ranked candidates under an `attempt_id` are emitted as
  rejected rows for contrastive training and auditability.

**Q4.2 Was the raw data saved?** Yes. Canonical JSONL shards are released
under `shards/` and pinned by `shards/MANIFEST.json`; run reports and shortened
Lean files are retained in the generation outputs used to build the release.

## 5. Uses

**Q5.1 Has the dataset been used for any tasks already?**
Internal experiments only (training-pair generation pipeline +
elegance gates).

**Q5.2 What other tasks could it be used for?**
- DPO / RLHF for proof tactic selection.
- Tactic-level autoformalisation models.
- Premise-selection ablations (via `goal_state` ↔ `replacement`
  mapping).

**Q5.3 Is there anything that could cause unfair treatment of
individuals or groups?** N/A — formal mathematics.

**Q5.4 Tasks the dataset should NOT be used for?**
- Direct production deployment without re-verification: the dataset
  guarantees rows verified under Lean 4.21.0 + Mathlib v4.21.0.
  Other toolchains may reject them.
- Claims that a model "writes correct Lean proofs" simply by
  fitting these pairs — verification is the property of the kernel,
  not of the model.

## 6. Distribution

**Q6.1 Will the dataset be distributed to third parties?**
Yes: public release on Hugging Face Hub.

**Q6.2 How?** HF dataset, with the dataset card rendered as the
HF README, plus a `croissant.json` metadata file at the root.

**Q6.3 When?** The dataset is available now on the Hugging Face Hub (see Q7.1).

**Q6.4 Subject to copyright/IP?** Apache 2.0 for the rows; upstream
proofs retain their original licenses. See `shards/MANIFEST.json` for
source-corpus license notes.

**Q6.5 Export controls?** None.

## 7. Maintenance

**Q7.1 Who hosts the dataset?** Hugging Face Hub
(`leanpolish-anon/lean-proof-compression`).

**Q7.2 How can the dataset be contacted?** Via the discussion tab of the Hugging Face dataset page.

**Q7.3 Will the dataset be updated?** New releases may follow toolchain
updates (Mathlib v4.x). Each release ships a fresh manifest with optimizer
`git_sha`/build provenance and `mathlib_rev`; versions are unambiguous.

**Q7.4 Will older versions be retained?** Versioned release artifacts are
intended to remain available. The v1.0.0 files are pinned by manifest hashes.

**Q7.5 Mechanism for contributions?** Pull requests on the Hugging Face dataset page.
