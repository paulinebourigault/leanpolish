#!/usr/bin/env python3
"""Join screening results onto candidates and emit verify_pair.py work chunks.

Selection: every unique candidate whose screen verdict is `pass` or
`screen_baseline_broken` (the REPL lane could not judge those) goes to the
exact verify_pair.py lane. Optionally add an agreement-check sample drawn
across ALL screened verdict classes.

content_sha256 is dropped from rows whose corpus is in --strip-sha (source
snapshots that drifted in bytes outside all edit spans; span equality is
still enforced byte-exactly by verify_pair.py).

Chunks are written as chunk_NNN.jsonl for resumable verification: a chunk is
done when chunk_NNN.kernel_verified.jsonl exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path


def ckey(c) -> str:
    return hashlib.sha256(
        f"{c['file']}:{c['start_byte']}:{c['end_byte']}:{c['replacement']}"
        .encode()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cands", nargs="+", required=True)
    ap.add_argument("--screen", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--chunk-size", type=int, default=150)
    ap.add_argument("--strip-sha", nargs="*", default=[])
    ap.add_argument("--agreement-sample", type=int, default=0,
                    help="also emit agreement_NNN.jsonl chunks sampled across "
                         "screen verdict classes (pass/fail/reference/noop)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    screen = {}
    with open(args.screen) as f:
        for line in f:
            r = json.loads(line)
            screen[r["key"]] = r

    seen = set()
    to_verify, agreement_pool = [], []
    verdict_counts = Counter()
    for path in args.cands:
        with open(path) as f:
            for line in f:
                c = json.loads(line)
                k = ckey(c)
                if k in seen:
                    continue
                seen.add(k)
                sv = screen.get(k, {}).get("screen_verdict", "missing")
                verdict_counts[sv] += 1
                row = {kk: vv for kk, vv in c.items()
                       if kk not in ("raw_output",)}
                row["key"] = k
                row["screen_verdict"] = sv
                if c["corpus"] in args.strip_sha:
                    row.pop("content_sha256", None)
                if sv in ("pass", "screen_baseline_broken"):
                    to_verify.append(row)
                if sv in ("pass", "fail", "matches_reference", "noop"):
                    agreement_pool.append(row)

    print(f"[prep] unique candidates: {len(seen)}  screen verdicts: "
          f"{dict(verdict_counts)}")
    print(f"[prep] to exact verification: {len(to_verify)}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    to_verify.sort(key=lambda r: (r["file"], r["start_byte"], r["key"]))
    for i in range(0, len(to_verify), args.chunk_size):
        p = out / f"chunk_{i//args.chunk_size:03d}.jsonl"
        with p.open("w") as f:
            for r in to_verify[i:i + args.chunk_size]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n_chunks = (len(to_verify) + args.chunk_size - 1) // args.chunk_size
    print(f"[prep] wrote {n_chunks} chunks to {out}")

    if args.agreement_sample:
        rng = random.Random(args.seed)
        by_class = {}
        for r in agreement_pool:
            by_class.setdefault(r["screen_verdict"], []).append(r)
        sample = []
        per = max(1, args.agreement_sample // max(1, len(by_class)))
        for cls, rows in sorted(by_class.items()):
            sample.extend(rng.sample(rows, min(per, len(rows))))
        keys_in_verify = {r["key"] for r in to_verify}
        sample = [r for r in sample if r["key"] not in keys_in_verify]
        for i in range(0, len(sample), args.chunk_size):
            p = out / f"agreement_{i//args.chunk_size:03d}.jsonl"
            with p.open("w") as f:
                for r in sample[i:i + args.chunk_size]:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[prep] agreement sample (excl. already-verified): {len(sample)}")


if __name__ == "__main__":
    main()
