#!/usr/bin/env python3
"""Train a two-head pointwise candidate ranker on complete-menu pools.

Backbone and adapter: DeepSeek-Prover-V2-7B + LoRA r16/alpha32 all-linear + score head,
bf16, max_len 1024 left-truncated, lr 1e-4 cosine, 3% warmup, 1 epoch, seed 42.
Pointwise with num_labels=2:
  head 0 = P(valid)   (BCE on `valid`)
  head 1 = P(best)    (BCE on `best` = shortest acceptable candidate)
--no-goal trains on `text_nogoal` ([ORIGINAL]/[CANDIDATE] only).
"""
from __future__ import annotations

import argparse
import os
import json
import math
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default=os.environ.get("BASE_MODEL", "deepseek-ai/DeepSeek-Prover-V2-7B"),
                    help="HF id or local path (env BASE_MODEL)")
    ap.add_argument("--no-goal", action="store_true")
    ap.add_argument("--max-len", type=int, default=1024)
    ap.add_argument("--max-samples", type=int, default=0)
    ap.add_argument("--micro", type=int, default=16)
    ap.add_argument("--effective", type=int, default=64)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--attn", default="sdpa")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)

    rows = [json.loads(l) for l in args.train.open()]
    if args.max_samples and len(rows) > args.max_samples:
        # subsample whole sites to keep pools intact
        sites = sorted({r["site"] for r in rows})
        rng.shuffle(sites)
        keep, n = set(), 0
        cnt = {}
        for r in rows:
            cnt[r["site"]] = cnt.get(r["site"], 0) + 1
        for s in sites:
            if n >= args.max_samples:
                break
            keep.add(s)
            n += cnt[s]
        rows = [r for r in rows if r["site"] in keep]
    key = "text_nogoal" if args.no_goal else "text"
    print(f"{len(rows)} samples; valid+ {sum(r['valid'] for r in rows)} best+ "
          f"{sum(r['best'] for r in rows)}; field={key}", flush=True)

    tok = AutoTokenizer.from_pretrained(args.model)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.truncation_side = "left"
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=2, torch_dtype=torch.bfloat16, attn_implementation=args.attn)
    model.config.pad_token_id = tok.pad_token_id
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear",
        task_type="SEQ_CLS", modules_to_save=["score"]))
    model.print_trainable_parameters()
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model.cuda()

    ids = tok([r[key] for r in rows], truncation=True, max_length=args.max_len)["input_ids"]
    labels = torch.tensor([[r["valid"], r["best"]] for r in rows], dtype=torch.float)
    # class weighting for the rare `best` label (pos_weight capped at 10)
    pv = labels.mean(0).clamp(min=1e-4)
    pos_weight = ((1 - pv) / pv).clamp(max=10.0).cuda()
    print("pos rates", pv.tolist(), "pos_weight", pos_weight.tolist(), flush=True)

    order = sorted(range(len(rows)), key=lambda i: len(ids[i]))
    mbs = [order[i:i + args.micro] for i in range(0, len(order), args.micro)]
    rng.shuffle(mbs)
    accum = max(1, args.effective // args.micro)
    n_steps = math.ceil(len(mbs) / accum) * args.epochs
    warm = max(1, int(0.03 * n_steps))
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: s / warm if s < warm else
        0.5 * (1 + math.cos(math.pi * min(1.0, (s - warm) / max(1, n_steps - warm)))))
    print(f"{len(mbs)} micro-batches, {n_steps} steps", flush=True)

    model.train()
    step, t0, hist = 0, time.time(), []
    wl, wn = 0.0, 0
    for ep in range(args.epochs):
        for bi, mb in enumerate(mbs):
            seqs = [ids[i] for i in mb]
            L = max(len(s) for s in seqs)
            x = torch.full((len(seqs), L), tok.pad_token_id, dtype=torch.long)
            a = torch.zeros((len(seqs), L), dtype=torch.long)
            for j, s in enumerate(seqs):
                x[j, :len(s)] = torch.tensor(s)
                a[j, :len(s)] = 1
            y = labels[mb].cuda()
            logits = model(input_ids=x.cuda(), attention_mask=a.cuda()).logits.float()
            loss = F.binary_cross_entropy_with_logits(logits, y, pos_weight=pos_weight)
            (loss / accum).backward()
            wl += loss.item(); wn += 1
            if (bi + 1) % accum == 0 or bi + 1 == len(mbs):
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
                step += 1
                if step % 20 == 0 or step == n_steps:
                    rec = {"step": step, "of": n_steps, "loss": wl / wn,
                           "elapsed_s": round(time.time() - t0, 1)}
                    hist.append(rec); print(json.dumps(rec), flush=True)
                    wl, wn = 0.0, 0
    (args.out / "train_log.json").write_text(json.dumps(hist, indent=2))
    model.save_pretrained(args.out / "adapter")
    tok.save_pretrained(args.out / "adapter")
    print(f"saved; {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
