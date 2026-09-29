#!/usr/bin/env python3
"""DPO on LeanPolish rejected-sibling preference pairs.

Policy = merged SFT model + fresh LoRA. Reference = the same model with the
adapter disabled (standard PEFT trick — no second model copy). Hand-rolled
DPO loss (no TRL dependency):

    loss = -log σ( β [ (πc − ρc) − (πr − ρr) ] )

where πx / ρx are policy / reference sequence log-probs summed over the
completion tokens only.

Usage (one GPU):
  python train_dpo_lora.py --pairs dpo_pairs.jsonl \
      --model $CKPT_DIR/leanpolish-sft-7b/merged --out $CKPT_DIR/leanpolish-dpo-7b
"""
from __future__ import annotations

import argparse
import json
import math
import random

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from transformers import (AutoModelForCausalLM, AutoTokenizer,
                          get_cosine_schedule_with_warmup, set_seed)
from peft import LoraConfig, get_peft_model

IGNORE = -100


class PairDataset(Dataset):
    def __init__(self, path, tokenizer, max_len):
        self.rows = []
        skipped = 0
        for line in open(path):
            r = json.loads(line)
            p = tokenizer(r["prompt"], add_special_tokens=True)["input_ids"]
            c = tokenizer(r["chosen"], add_special_tokens=False)["input_ids"] + [tokenizer.eos_token_id]
            j = tokenizer(r["rejected"], add_special_tokens=False)["input_ids"] + [tokenizer.eos_token_id]
            longest = max(len(c), len(j))
            if longest >= max_len - 8:
                skipped += 1
                continue
            keep = max_len - longest
            if len(p) > keep:
                p = p[-keep:]
            self.rows.append({"prompt": p, "chosen": c, "rejected": j})
        print(f"[data] {path}: {len(self.rows)} pairs ({skipped} skipped)")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


def collate(batch, pad_id):
    # 2N sequences: first N chosen, last N rejected
    seqs, labels = [], []
    for key in ("chosen", "rejected"):
        for b in batch:
            ids = b["prompt"] + b[key]
            lab = [IGNORE] * len(b["prompt"]) + list(b[key])
            seqs.append(ids)
            labels.append(lab)
    n = max(len(s) for s in seqs)
    input_ids = [s + [pad_id] * (n - len(s)) for s in seqs]
    labs = [l + [IGNORE] * (n - len(l)) for l in labels]
    attn = [[1] * len(s) + [0] * (n - len(s)) for s in seqs]
    return (torch.tensor(input_ids), torch.tensor(labs), torch.tensor(attn))


def seq_logps(model, input_ids, labels, attn):
    out = model(input_ids=input_ids, attention_mask=attn).logits[:, :-1]
    tgt = labels[:, 1:]
    mask = tgt != IGNORE
    logp = torch.log_softmax(out.float(), dim=-1)
    tok = torch.gather(logp, 2, tgt.clamp_min(0).unsqueeze(-1)).squeeze(-1)
    return (tok * mask).sum(-1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--model", required=True, help="merged SFT model dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--micro-pairs", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=1536)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args()

    set_seed(args.seed)
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    attn_impl = "sdpa"
    try:
        import flash_attn  # noqa: F401
        attn_impl = "flash_attention_2"
    except ImportError:
        pass
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True,
        attn_implementation=attn_impl).cuda()
    model.config.use_cache = False
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05,
                      target_modules="all-linear", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    ds = PairDataset(args.pairs, tok, args.max_len)
    g = torch.Generator().manual_seed(args.seed)
    dl = DataLoader(ds, batch_size=args.micro_pairs, shuffle=True, generator=g,
                    collate_fn=lambda b: collate(b, tok.pad_token_id))

    steps_per_epoch = math.ceil(len(dl) / args.grad_accum)
    total = int(steps_per_epoch * args.epochs) if args.max_steps < 0 else args.max_steps
    opt = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),
                            lr=args.lr, weight_decay=0.0)
    sched = get_cosine_schedule_with_warmup(opt, int(0.03 * total), total)

    step = micro = 0
    acc_stats = []
    model.train()
    done = False
    for epoch in range(math.ceil(args.epochs)):
        if done:
            break
        for batch in dl:
            input_ids, labels, attn = (t.cuda() for t in batch)
            n = input_ids.shape[0] // 2
            pol = seq_logps(model, input_ids, labels, attn)
            with torch.no_grad(), model.disable_adapter():
                ref = seq_logps(model, input_ids, labels, attn)
            margin = args.beta * ((pol[:n] - ref[:n]) - (pol[n:] - ref[n:]))
            loss = -F.logsigmoid(margin).mean() / args.grad_accum
            loss.backward()
            acc_stats.append(((margin > 0).float().mean().item(),
                              loss.item() * args.grad_accum))
            micro += 1
            if micro % args.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    (p for p in model.parameters() if p.requires_grad), 1.0)
                opt.step(); sched.step(); opt.zero_grad()
                step += 1
                if step % 10 == 0:
                    accs = sum(a for a, _ in acc_stats) / len(acc_stats)
                    ls = sum(l for _, l in acc_stats) / len(acc_stats)
                    print(json.dumps({"step": step, "of": total,
                                      "dpo_loss": round(ls, 4),
                                      "pref_acc": round(accs, 4),
                                      "lr": sched.get_last_lr()[0]}), flush=True)
                    acc_stats = []
                if step >= total:
                    done = True
                    break

    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print(f"[done] DPO adapter saved to {args.out}")
    if args.merge:
        merged = model.merge_and_unload()
        merged.save_pretrained(args.out + "/merged", safe_serialization=True)
        tok.save_pretrained(args.out + "/merged")
        print(f"[done] merged model saved to {args.out}/merged")


if __name__ == "__main__":
    main()
