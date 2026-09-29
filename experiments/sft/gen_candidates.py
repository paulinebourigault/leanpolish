#!/usr/bin/env python3
"""Generate replacement candidates for eval sites with vLLM.

For each eval site and each model condition, produce:
  - 1 greedy sample (decoding_index = "greedy")
  - 4 stochastic samples (temperature 0.6, top-p 0.95, decoding_index 0..3)
All decoding budgets identical across conditions (max 256 new tokens).

<DELETE> outputs are converted to the empty string. Output rows carry all
fields needed by verify_pair.py plus model/decoding metadata.

Usage:
  python gen_candidates.py --model <hf-id-or-merged-dir> --tag frozen \
      --sites eval_sites_minif2f.jsonl [more...] --out cands_frozen.jsonl
"""
from __future__ import annotations

import argparse
import json

DELETE_TOKEN = "<DELETE>"


def clean(text: str) -> tuple[str, str]:
    """Return (replacement, raw). Strips whitespace; maps <DELETE> to ''. """
    raw = text
    t = text.strip()
    if t.startswith(DELETE_TOKEN):
        return "", raw
    return t, raw


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True, help="model condition label, e.g. frozen / sft")
    ap.add_argument("--sites", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-model-len", type=int, default=4096)
    ap.add_argument("--gpu-mem-util", type=float, default=0.90)
    ap.add_argument("--enforce-eager", action="store_true",
                    help="skip torch.compile (nodes without ninja/libcuda)")
    args = ap.parse_args()

    from vllm import LLM, SamplingParams

    sites = []
    for path in args.sites:
        with open(path) as f:
            for line in f:
                sites.append(json.loads(line))
    print(f"[gen] {len(sites)} sites, model={args.model} tag={args.tag}")

    llm = LLM(model=args.model, dtype="bfloat16", seed=args.seed,
              max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_mem_util,
              trust_remote_code=True,
              enforce_eager=args.enforce_eager)

    prompts = [s["prompt"] for s in sites]
    greedy = SamplingParams(temperature=0.0, max_tokens=args.max_new_tokens)
    sampled = SamplingParams(temperature=args.temperature, top_p=args.top_p,
                             n=args.k, max_tokens=args.max_new_tokens,
                             seed=args.seed)

    out_rows = []

    def emit(site, text, decoding_index):
        replacement, raw = clean(text)
        out_rows.append({
            "model_tag": args.tag,
            "model": args.model,
            "decoding_index": decoding_index,
            "corpus": site["corpus"],
            "file": site["file"],
            "start_byte": site["start_byte"],
            "end_byte": site["end_byte"],
            "original": site["original"],
            "replacement": replacement,
            "raw_output": raw[:2000],
            "content_sha256": site.get("content_sha256"),
            "type": site["type"],
            "kind": site.get("kind"),
            "attempt_id": site["attempt_id"],
            "reference_replacement": site.get("reference_replacement"),
            "tokens_original": site.get("tokens_original"),
        })

    print("[gen] greedy pass")
    for site, res in zip(sites, llm.generate(prompts, greedy)):
        emit(site, res.outputs[0].text, "greedy")

    print(f"[gen] sampled pass (n={args.k}, T={args.temperature})")
    for site, res in zip(sites, llm.generate(prompts, sampled)):
        for j, o in enumerate(res.outputs):
            emit(site, o.text, j)

    with open(args.out, "w") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[gen] wrote {len(out_rows)} candidates -> {args.out}")


if __name__ == "__main__":
    main()
