#!/usr/bin/env python3
"""Score every run candidate of the held-out complete pools with a model.

--method frozen_lp : mean token log-prob of the candidate continuation (final_tac)
                     under frozen DeepSeek-Prover-V2-7B given [GOAL]/[ORIGINAL]/[CANDIDATE] prompt
--method ranker    : two-head LoRA ranker (--adapter); writes <name>_valid, <name>_best logits
Output jsonl: {"key": site_key|menu_idx, "<name>...": score}
Inputs: --pools (gzipped/plain pool jsonl from extract_pools.py); --adapter for --method ranker.
"""
import argparse
import os
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import PROMPT_TEMPLATE, cand_text, goal_text, load_sites, pool_candidates, site_key  # noqa


def batches(order, items, bs):
    for b in range(0, len(order), bs):
        yield order[b:b + bs]


def pad(seqs, pad_id):
    L = max(len(s) for s in seqs)
    x = torch.full((len(seqs), L), pad_id, dtype=torch.long)
    a = torch.zeros((len(seqs), L), dtype=torch.long)
    for j, s in enumerate(seqs):
        x[j, :len(s)] = torch.tensor(s)
        a[j, :len(s)] = 1
    return x.cuda(), a.cuda()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", nargs="+", required=True)
    ap.add_argument("--method", choices=["frozen_lp", "ranker"], required=True)
    ap.add_argument("--name", default=None)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--no-goal", action="store_true")
    ap.add_argument("--model", default=os.environ.get("BASE_MODEL", "deepseek-ai/DeepSeek-Prover-V2-7B"),
                    help="HF id or local path (env BASE_MODEL)")
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--attn", default="sdpa")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    name = args.name or args.method
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.adapter or args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    items = []  # (key, ids, n_cont)
    for p in args.pools:
        for s in load_sites(p):
            for c in pool_candidates(s):
                key = f"{site_key(s)}|{c['menu_idx']}"
                if args.method == "frozen_lp":
                    prompt = PROMPT_TEMPLATE.format(goal=goal_text(s), original=s["original"])
                    p_ids = tok(prompt)["input_ids"]
                    c_ids = tok(c["final_tac"], add_special_tokens=False)["input_ids"] or [tok.eos_token_id]
                    c_ids = c_ids[: args.max_len - 1]
                    ids = p_ids + c_ids
                    if len(ids) > args.max_len:
                        keep = max(1, args.max_len - len(c_ids))
                        ids = [p_ids[0]] + p_ids[len(p_ids) - keep + 1:] + c_ids
                    items.append((key, ids, len(c_ids)))
                else:
                    tok.truncation_side = "left"
                    ids = tok(cand_text(s, c, not args.no_goal), truncation=True,
                              max_length=args.max_len)["input_ids"]
                    items.append((key, ids, 0))
    print(f"{len(items)} candidates", flush=True)
    order = sorted(range(len(items)), key=lambda i: len(items[i][1]))
    out = {}
    t0 = time.time()
    if args.method == "frozen_lp":
        from transformers import AutoModelForCausalLM
        model = AutoModelForCausalLM.from_pretrained(
            args.model, torch_dtype=torch.bfloat16, attn_implementation=args.attn).cuda().eval()
        with torch.inference_mode():
            for k, idxs in enumerate(batches(order, items, args.bs)):
                x, a = pad([items[i][1] for i in idxs], tok.eos_token_id)
                lp = torch.log_softmax(model(input_ids=x, attention_mask=a).logits.float(), -1)
                for j, i in enumerate(idxs):
                    key, ids, n = items[i]
                    L = len(ids)
                    tgt = torch.tensor(ids[L - n:], device=lp.device)
                    v = lp[j, L - n - 1:L - 1].gather(-1, tgt.unsqueeze(-1)).squeeze(-1)
                    out[key] = {name: v.mean().item(), name + "_sum": v.sum().item()}
                if k % 50 == 0:
                    print(f"{k*args.bs}/{len(items)} {time.time()-t0:.0f}s", flush=True)
    else:
        from peft import PeftModel
        from transformers import AutoModelForSequenceClassification
        base = AutoModelForSequenceClassification.from_pretrained(
            args.model, num_labels=2, torch_dtype=torch.bfloat16, attn_implementation=args.attn)
        base.config.pad_token_id = tok.pad_token_id
        model = PeftModel.from_pretrained(base, args.adapter).cuda().eval()
        with torch.inference_mode():
            for k, idxs in enumerate(batches(order, items, args.bs)):
                x, a = pad([items[i][1] for i in idxs], tok.pad_token_id)
                lg = model(input_ids=x, attention_mask=a).logits.float()
                # right padding: sequence classification pools the last non-pad token
                for j, i in enumerate(idxs):
                    out[items[i][0]] = {f"{name}_valid": lg[j, 0].item(),
                                        f"{name}_best": lg[j, 1].item()}
                if k % 50 == 0:
                    print(f"{k*args.bs}/{len(items)} {time.time()-t0:.0f}s", flush=True)
    with open(args.out, "w") as f:
        for key, v in out.items():
            f.write(json.dumps({"key": key, **v}) + "\n")
    print(f"done {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
