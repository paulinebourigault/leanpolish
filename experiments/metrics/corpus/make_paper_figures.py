#!/usr/bin/env python3
"""Regenerate the paper's released-row and savings figures.

The script reads the released shard manifest and training-pair JSONL files,
then writes the PDF/PNG figures under ``$OUT_DIR`` (default ./figs).
Environment: DATASET_ROOT (local copy of the HF dataset containing shards/; default "."). The plotted counts are
the as-shipped Hugging Face configuration counts, so they can be checked
directly against ``shards/MANIFEST.json`` and the release totals in the paper.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import os
ROOT = Path(os.environ.get("DATASET_ROOT", "."))

ACCENT = "#3B5BDB"
ACCENT_MID = "#C8D2F2"
REJECT_COLOR = "#D6724A"
L2_COLOR = "#F2C94C"
REJECT_DARK = "#B23B25"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["DejaVu Serif", "Times New Roman", "Times"],
    "font.size": 11,
    "axes.titlesize": 12,
    "axes.labelsize": 11,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": "black",
    "axes.labelcolor": "black",
    "text.color": "black",
    "xtick.color": "black",
    "ytick.color": "black",
    "axes.linewidth": 1.0,
    "xtick.major.width": 1.0,
    "ytick.major.width": 1.0,
    "savefig.dpi": 200,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

SHARDS = [
    ("Mathlib", "mathlib"),
    ("Goedel", "goedel"),
    ("miniF2F", "minif2f"),
    ("PutnamBench\nGoedel sample", "putnam_bench"),
    ("PutnamBench\nverified", "putnam_verified"),
    ("Putnam 2025\nAxiom per-file", "putnam2025_per_file"),
    ("Putnam 2025\nAxiom pooled", "putnam2025_pool"),
]


def _load_manifest() -> dict:
    with open(ROOT / "shards" / "MANIFEST.json", "r") as fh:
        return json.load(fh)


def _split_paths(shard: str, split: str) -> list[Path]:
    shard_dir = ROOT / "shards" / shard
    exact = shard_dir / f"{split}.jsonl.gz"
    if exact.exists():
        return [exact]
    return sorted(shard_dir.glob(f"{split}_*.jsonl.gz"))


def _load_savings(shard: str) -> np.ndarray:
    out: list[int] = []
    for path in _split_paths(shard, "training_pairs"):
        with gzip.open(path, "rt") as fh:
            for line in fh:
                row = json.loads(line)
                original = row.get("original") or ""
                replacement = row.get("replacement") or ""
                saved = len(original.encode("utf-8")) - len(replacement.encode("utf-8"))
                if saved > 0:
                    out.append(saved)
    return np.array(out, dtype=int)


def make_released_split_composition(out_pdf: Path) -> None:
    manifest = _load_manifest()
    labels = [label for label, _ in SHARDS]
    accepted = np.array([
        manifest["shards"][shard]["training_pairs"]["rows"]
        for _, shard in SHARDS
    ], dtype=float)
    rejected = np.array([
        manifest["shards"][shard]["rejected_pairs"]["rows"]
        for _, shard in SHARDS
    ], dtype=float)
    l2 = np.array([
        manifest["shards"][shard]["l2_detections"]["rows"]
        for _, shard in SHARDS
    ], dtype=float)
    totals = accepted + rejected + l2
    accepted_pct = accepted / totals * 100.0
    rejected_pct = rejected / totals * 100.0
    l2_pct = l2 / totals * 100.0

    y = np.arange(len(labels))[::-1]
    height = 0.58

    fig, ax = plt.subplots(figsize=(5.9, 3.8))
    ax.barh(y, accepted_pct, height=height, color=ACCENT,
            edgecolor="white", linewidth=0.5, label="accepted")
    ax.barh(y, rejected_pct, left=accepted_pct, height=height, color=REJECT_COLOR,
            edgecolor="white", linewidth=0.5, label="rejected")
    ax.barh(y, l2_pct, left=accepted_pct + rejected_pct, height=height, color=L2_COLOR,
            edgecolor="white", linewidth=0.5, label="L2 detections")

    ax.set_xlim(0, 100)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel("share of released rows (%)")
    ax.tick_params(axis="y", length=0)
    for yi, total in zip(y, totals):
        ax.text(101.2, yi, f"n={int(total):,}", va="center", ha="left",
                fontsize=8.4, color="black", clip_on=False)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.01), ncol=3,
              frameon=False, fontsize=9.5, handlelength=1.4,
              handletextpad=0.5, columnspacing=1.2, borderaxespad=0.0)
    ax.grid(False)
    ax.set_axisbelow(True)

    plt.tight_layout(pad=0.4)
    plt.savefig(out_pdf, bbox_inches="tight", pad_inches=0.02)
    plt.savefig(out_pdf.with_suffix(".png"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def make_per_corpus_savings(out_pdf: Path) -> None:
    data = [_load_savings(shard) for _, shard in SHARDS]
    counts = [len(values) for values in data]
    labels = [f"{label}\n(n={count:,})" for (label, _), count in zip(SHARDS, counts)]
    positions = np.arange(1, len(labels) + 1)

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.boxplot(
        [values if len(values) else np.array([1]) for values in data],
        positions=positions,
        widths=0.55,
        whis=(1, 99),
        showfliers=False,
        patch_artist=True,
        medianprops={"color": "black", "linewidth": 1.8},
        boxprops={"facecolor": ACCENT_MID, "edgecolor": ACCENT, "linewidth": 1.0},
        whiskerprops={"color": "black", "linewidth": 1.0},
        capprops={"color": "black", "linewidth": 1.0},
    )

    maxes = [int(values.max()) if len(values) else 1 for values in data]
    ax.scatter(positions, maxes, marker="*", s=80, color=REJECT_DARK,
               edgecolor="black", linewidth=0.5, zorder=6, label="max")

    ax.set_yscale("log")
    ax.set_ylim(0.7, max(maxes) * 2.0)
    ax.set_ylabel("bytes saved per pair (log)")
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, rotation=28, ha="right", fontsize=9.0)
    ax.set_xlim(0.4, len(labels) + 0.6)
    ax.grid(False)
    ax.set_axisbelow(True)

    plt.tight_layout(pad=0.4)
    plt.savefig(out_pdf, bbox_inches="tight", pad_inches=0.02)
    plt.savefig(out_pdf.with_suffix(".png"), bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def main() -> None:
    figs = Path(os.environ.get("OUT_DIR", "figs"))
    figs.mkdir(parents=True, exist_ok=True)
    make_released_split_composition(figs / "split_composition.pdf")
    make_per_corpus_savings(figs / "per_corpus_savings.pdf")
    print("wrote", figs / "split_composition.pdf")
    print("wrote", figs / "per_corpus_savings.pdf")

    manifest = _load_manifest()
    print("\nVerification (as-shipped HF configuration counts):")
    print(f"  {'config':18s} {'accepted':>8s} {'rejected':>8s} {'l2':>6s} "
          f"{'n_pos':>8s} {'median':>7s} {'p99':>7s} {'max':>7s}")
    for _, shard in SHARDS:
        savings = _load_savings(shard)
        rows = manifest["shards"][shard]
        n_positive = len(savings)
        median = int(np.median(savings)) if len(savings) else 0
        p99 = int(np.percentile(savings, 99)) if len(savings) else 0
        maximum = int(savings.max()) if len(savings) else 0
        print(f"  {shard:18s} {rows['training_pairs']['rows']:8,d} "
              f"{rows['rejected_pairs']['rows']:8,d} "
              f"{rows['l2_detections']['rows']:6,d} "
              f"{n_positive:8,d} {median:7d} {p99:7d} {maximum:7d}")


if __name__ == "__main__":
    main()