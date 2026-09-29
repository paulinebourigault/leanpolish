#!/usr/bin/env python3
"""LoRA-SFT of DeepSeek-Prover-V2-7B as a whole-proof rewriter.
rank 32, alpha 64, dropout 0.05, all linear proj; lr 1e-4 cosine, warmup 3%; bf16; gradient
checkpointing; seed 42. Loss only on the assistant turn (the prompt tokens are masked).
Batching: length-grouped dynamic batches of <= TOKENS_PER_BATCH padded tokens (no cross-sample
packing, so no attention leakage between samples)."""
import argparse, json, math, os, random, time
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model

ap = argparse.ArgumentParser()
ap.add_argument('--model', default=os.environ.get('MODEL', 'deepseek-ai/DeepSeek-Prover-V2-7B'))
ap.add_argument('--data', default='data/wp_train.jsonl')
ap.add_argument('--out', default=os.environ.get('ADAPTER', 'adapter'))
ap.add_argument('--epochs', type=int, default=2)
ap.add_argument('--lr', type=float, default=1e-4)
ap.add_argument('--tokens-per-batch', type=int, default=32768)
ap.add_argument('--micro-tokens', type=int, default=16384)
ap.add_argument('--max-hours', type=float, default=2.4)
args = ap.parse_args()
random.seed(42); torch.manual_seed(42)
tok = AutoTokenizer.from_pretrained(args.model)
rows = [json.loads(l) for l in open(args.data)]
data = []
for r in rows:
    full = tok.apply_chat_template(r['messages'], tokenize=True)
    pre = tok.apply_chat_template(r['messages'][:1], tokenize=True, add_generation_prompt=True)
    assert full[:len(pre)] == pre, 'template prefix mismatch'
    labels = [-100] * len(pre) + full[len(pre):]
    data.append((full, labels))
print(f'{len(data)} samples, {sum(len(d[0]) for d in data)} tokens', flush=True)


def make_batches(epoch):
    rng = random.Random(42 + epoch)
    idx = list(range(len(data))); rng.shuffle(idx)
    # sort within chunks of 256 for length grouping
    batches = []
    for c in range(0, len(idx), 256):
        chunk = sorted(idx[c:c + 256], key=lambda i: len(data[i][0]))
        cur = []
        for i in chunk:
            L = max([len(data[j][0]) for j in cur + [i]])
            if cur and L * (len(cur) + 1) > args.micro_tokens:
                batches.append(cur); cur = []
            cur.append(i)
        if cur: batches.append(cur)
    rng.shuffle(batches)
    return batches


model = AutoModelForCausalLM.from_pretrained(args.model, torch_dtype=torch.bfloat16,
                                             attn_implementation='sdpa').cuda()
model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
model.enable_input_require_grads()
model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, task_type='CAUSAL_LM',
                                         target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj',
                                                         'gate_proj', 'up_proj', 'down_proj']))
model.print_trainable_parameters()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0)
all_b = [make_batches(e) for e in range(args.epochs)]
# accumulate micro-batches to ~tokens_per_batch real tokens per optimizer step
accum = max(1, args.tokens_per_batch // args.micro_tokens)
steps = sum(math.ceil(len(b) / accum) for b in all_b)
sched = get_cosine_schedule_with_warmup(opt, int(0.03 * steps), steps)
print(f'{steps} optimizer steps, accum {accum}', flush=True)
t0 = time.time(); step = 0; seen_tok = 0
model.train()
stop = False
for ep, batches in enumerate(all_b):
    for bi in range(0, len(batches), accum):
        group = batches[bi:bi + accum]
        ntgt = sum(sum(1 for x in data[i][1] if x != -100) for b in group for i in b)
        tot_loss = 0.0
        for b in group:
            L = max(len(data[i][0]) for i in b)
            ids = torch.full((len(b), L), tok.pad_token_id or 0, dtype=torch.long)
            lab = torch.full((len(b), L), -100, dtype=torch.long)
            att = torch.zeros((len(b), L), dtype=torch.long)
            for k, i in enumerate(b):
                x, y = data[i]
                ids[k, :len(x)] = torch.tensor(x); lab[k, :len(y)] = torch.tensor(y); att[k, :len(x)] = 1
                seen_tok += len(x)
            ids, lab, att = ids.cuda(), lab.cuda(), att.cuda()
            logits = model(input_ids=ids, attention_mask=att).logits[:, :-1].float()
            loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), lab[:, 1:].reshape(-1),
                                                     ignore_index=-100, reduction='sum') / ntgt
            loss.backward(); tot_loss += loss.item()
            del logits, loss
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True); step += 1
        el = time.time() - t0
        if step % 10 == 0 or step == 1:
            print(f'ep {ep} step {step}/{steps} loss {tot_loss:.4f} lr {sched.get_last_lr()[0]:.2e} '
                  f'tok/s {seen_tok / el:.0f} elapsed {el / 60:.1f}m eta {el / step * (steps - step) / 60:.1f}m', flush=True)
        if el > args.max_hours * 3600:
            print('time budget hit; stopping', flush=True); stop = True; break
    model.save_pretrained(f'{args.out}_ep{ep}')
    if stop: break
model.save_pretrained(args.out)
json.dump({'steps': step, 'planned_steps': steps, 'train_s': time.time() - t0, 'seen_tokens': seen_tok,
           'stopped_early': stop}, open(args.out + '_trainstats.json', 'w'))
print('DONE', flush=True)
