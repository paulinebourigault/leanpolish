#!/usr/bin/env python3
"""Whole-proof generation with vLLM (frozen or LoRA). n samples at T=0.7, top_p 0.95, seed 42;
the first 4 samples of each file form the k=4 condition (nested budgets).

--prompt simple : "Rewrite this Lean 4 proof to be shorter while remaining correct. Output the
                  full file." + the full file in a ```lean4 block (the SFT prompt).
--prompt c2     : the controls C2 prompt (experiments/controls gen_c2_whole.build_prompt) on the C2 unit of the
                  file (single-proof files: the whole theorem, header as context); the output
                  declaration is spliced back into the file at the unit span by parse_verify.py.
Items: jsonl {id, corpus, variant, text, [unit]}.  Output: jsonl {id, raw[], gen_tokens[],
finish[], prompt_tokens} + <out>.cost.json.
"""
import argparse, json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
INSTR = "Rewrite this Lean 4 proof to be shorter while remaining correct. Output the full file."
C2_INSTR = (
    "The following Lean 4 declaration (Lean v4.21.0, Mathlib) compiles. Rewrite it so that its "
    "proof is as short as possible (fewest tokens) while still compiling. Keep the declaration "
    "keyword, name and statement exactly unchanged; only change the proof after `:=`. Do not use "
    "`sorry`, `admit`, new axioms or `native_decide`. Earlier declarations of the file are "
    "available and may be used. Output only the complete rewritten declaration in a single "
    "```lean4 code block.")


def prompt_for(it, mode):
    if mode == 'simple':
        return f"{INSTR}\n\n```lean4\n{it['text'].rstrip()}\n```", it['text']
    u = it['unit']
    return (f"{C2_INSTR}\n\nContext (earlier part of the file, for reference only):\n```lean4\n"
            f"{u['context'].rstrip()}\n```\n\nDeclaration to shorten:\n```lean4\n{u['original']}\n```"), u['original']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=os.environ.get('MODEL', 'deepseek-ai/DeepSeek-Prover-V2-7B'))
    ap.add_argument('--lora')
    ap.add_argument('--items', nargs='+', required=True)
    ap.add_argument('--prompt', choices=['simple', 'c2'], default='simple')
    ap.add_argument('--out', required=True)
    ap.add_argument('--n', type=int, default=16)
    ap.add_argument('--max-model-len', type=int, default=32768)
    ap.add_argument('--gpu-mem-util', type=float, default=0.90)
    ap.add_argument('--budget-mult', type=float, default=2.0, help='max new tokens = mult * body tokens + 512')
    args = ap.parse_args()
    t0 = time.time()
    items = [json.loads(l) for p in args.items for l in open(p) if l.strip()]
    if args.prompt == 'c2':
        items = [it for it in items if it.get('unit')]
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model)
    ids, budgets, keep = [], [], []
    for i, it in enumerate(items):
        p, body = prompt_for(it, args.prompt)
        x = tok.apply_chat_template([{'role': 'user', 'content': p}], tokenize=True, add_generation_prompt=True)
        nb = len(tok(body, add_special_tokens=False)['input_ids'])
        need = int(args.budget_mult * nb) + 512
        ids.append(x); budgets.append(need)
        if len(x) + need <= args.max_model_len:
            keep.append(i)
    print(f'[gen] {len(items)} items; {len(items) - len(keep)} skipped (too long for {args.max_model_len} ctx)', flush=True)
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt
    kw = {}
    if args.lora:
        kw = dict(enable_lora=True, max_lora_rank=32, max_loras=1)
    llm = LLM(model=args.model, dtype='bfloat16', seed=42, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_mem_util, **kw)
    lreq = None
    if args.lora:
        from vllm.lora.request import LoRARequest
        lreq = LoRARequest('wp', 1, args.lora)
    t1 = time.time()
    res = llm.generate([TokensPrompt(prompt_token_ids=ids[i]) for i in keep],
                       [SamplingParams(temperature=0.7, top_p=0.95, n=args.n, max_tokens=budgets[i], seed=42)
                        for i in keep], lora_request=lreq)
    t2 = time.time()
    gen_toks = 0
    with open(args.out, 'w') as fo:
        for i, r in zip(keep, res):
            g = [len(o.token_ids) for o in r.outputs]; gen_toks += sum(g)
            fo.write(json.dumps({'id': items[i]['id'], 'raw': [o.text for o in r.outputs], 'gen_tokens': g,
                                 'finish': [o.finish_reason for o in r.outputs], 'prompt_tokens': len(ids[i])},
                                ensure_ascii=False) + '\n')
    cost = {'model': args.model, 'lora': args.lora, 'prompt': args.prompt, 'n': args.n,
            'n_items': len(items), 'n_generated': len(keep),
            'skipped_too_long': [items[i]['id'] for i in range(len(items)) if i not in set(keep)],
            'load_s': round(t1 - t0, 1), 'generate_s': round(t2 - t1, 1), 'gpu_s': round(time.time() - t0, 1),
            'prompt_tokens': sum(len(ids[i]) for i in keep), 'gen_tokens': gen_toks}
    json.dump(cost, open(args.out + '.cost.json', 'w'), indent=1)
    print('[gen] done', cost, flush=True)


if __name__ == '__main__':
    main()
