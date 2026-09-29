#!/usr/bin/env python3
"""BF16 LoRA SFT of DeepSeek-Prover-V2-7B on LeanPolish local proof edits.

Loss is computed on target tokens only. Hyperparameters follow the paper
(rank 32, alpha 64, dropout 0.05, all-linear, 2 epochs,
lr 1e-4 cosine, warmup 3%, weight decay 0.01, effective batch 64, seed 42).

Usage (one GPU):
  python train_sft_lora.py --train sft_train.jsonl --val sft_val.jsonl \
      --model deepseek-ai/DeepSeek-Prover-V2-7B --out $CKPT_DIR/leanpolish-sft-7b
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
from pathlib import Path

import torch
from torch.utils.data import Dataset

from transformers import (AutoModelForCausalLM, AutoTokenizer, Trainer,
                          TrainingArguments, set_seed)
from peft import LoraConfig, get_peft_model

IGNORE = -100


class EditDataset(Dataset):
    def __init__(self, path: str, tokenizer, max_len: int):
        self.rows = []
        skipped = 0
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                prompt_ids = tokenizer(r["prompt"], add_special_tokens=True)["input_ids"]
                target_ids = tokenizer(r["target"], add_special_tokens=False)["input_ids"]
                target_ids = target_ids + [tokenizer.eos_token_id]
                if len(target_ids) >= max_len - 8:
                    skipped += 1
                    continue
                if len(prompt_ids) + len(target_ids) > max_len:
                    # keep the tail of the prompt: it holds the ORIGINAL
                    # FRAGMENT and the [REPLACEMENT] marker
                    keep = max_len - len(target_ids)
                    prompt_ids = prompt_ids[-keep:]
                input_ids = prompt_ids + target_ids
                labels = [IGNORE] * len(prompt_ids) + list(target_ids)
                self.rows.append({"input_ids": input_ids, "labels": labels,
                                  "length": len(input_ids)})
        print(f"[data] {path}: {len(self.rows)} rows ({skipped} skipped, "
              f"len p50={sorted(r['length'] for r in self.rows)[len(self.rows)//2]})")

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


def collate(batch, pad_id: int):
    n = max(len(b["input_ids"]) for b in batch)
    input_ids, labels, attn = [], [], []
    for b in batch:
        pad = n - len(b["input_ids"])
        input_ids.append(b["input_ids"] + [pad_id] * pad)
        labels.append(b["labels"] + [IGNORE] * pad)
        attn.append([1] * len(b["input_ids"]) + [0] * pad)
    return {
        "input_ids": torch.tensor(input_ids),
        "labels": torch.tensor(labels),
        "attention_mask": torch.tensor(attn),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-Prover-V2-7B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-len", type=int, default=2048)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--micro-batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-steps", type=int, default=-1,
                    help="override for throughput benchmarking")
    ap.add_argument("--no-grad-ckpt", action="store_true",
                    help="disable gradient checkpointing: numerically identical, faster")
    ap.add_argument("--merge", action="store_true",
                    help="save a merged full model for vLLM at <out>/merged")
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
    print(f"[model] attn={attn_impl}")

    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, trust_remote_code=True,
        attn_implementation=attn_impl)
    model.config.use_cache = False
    model.enable_input_require_grads()

    lora = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05,
                      target_modules="all-linear", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_ds = EditDataset(args.train, tok, args.max_len)
    val_ds = EditDataset(args.val, tok, args.max_len)

    targs = TrainingArguments(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.micro_batch,
        per_device_eval_batch_size=args.micro_batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        bf16=True,
        gradient_checkpointing=not args.no_grad_ckpt,
        group_by_length=True,
        length_column_name="length",
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="epoch",
        save_total_limit=2,
        report_to=[],
        seed=args.seed,
        dataloader_num_workers=4,
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model, args=targs,
        train_dataset=train_ds, eval_dataset=val_ds,
        data_collator=lambda b: collate(b, tok.pad_token_id),
    )
    trainer.train()
    trainer.save_model(args.out)
    tok.save_pretrained(args.out)
    print(f"[done] adapter saved to {args.out}")

    if args.merge:
        del trainer
        torch.cuda.empty_cache()
        merged = model.merge_and_unload()
        merged_dir = os.path.join(args.out, "merged")
        merged.save_pretrained(merged_dir, safe_serialization=True)
        tok.save_pretrained(merged_dir)
        print(f"[done] merged model saved to {merged_dir}")


if __name__ == "__main__":
    main()
