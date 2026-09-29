#!/usr/bin/env python3
"""vLLM generation with an SFT LoRA adapter (loaded as a vLLM LoRA, not merged).
Decoding as in experiments/sft/gen_candidates.py: greedy + --k samples (default 4; T=0.6,
top_p=0.95, seed 42), max 256 new tokens, max_model_len 4096. A <DELETE> answer becomes "".
Input rows need 'prompt' and an id field (site_id, or attempt_id for the held-out teacher sites).
"""
import argparse, json

def clean(t):
    t = t.strip()
    return '' if t.startswith('<DELETE>') else t

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='deepseek-ai/DeepSeek-Prover-V2-7B')
    ap.add_argument('--adapter', required=True)
    ap.add_argument('--sites', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--greedy-only', action='store_true')
    ap.add_argument('--k', type=int, default=4)
    ap.add_argument('--gpu-mem-util', type=float, default=0.85)
    args = ap.parse_args()
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest
    rows = [json.loads(l) for p in args.sites for l in open(p)]
    print(f'[gen] {len(rows)} prompts', flush=True)
    llm = LLM(model=args.base, dtype='bfloat16', seed=42, max_model_len=4096,
              gpu_memory_utilization=args.gpu_mem_util, trust_remote_code=True,
              enable_lora=True, max_lora_rank=32, max_loras=1)
    lr = LoRARequest('sft', 1, args.adapter)
    prompts = [r['prompt'] for r in rows]
    g = llm.generate(prompts, SamplingParams(temperature=0.0, max_tokens=256), lora_request=lr)
    samp = None
    if not args.greedy_only:
        samp = llm.generate(prompts, SamplingParams(temperature=0.6, top_p=0.95, n=args.k,
                                                    max_tokens=256, seed=42), lora_request=lr)
    with open(args.out, 'w') as f:
        for i, r in enumerate(rows):
            o = {'site_id': r.get('site_id') or r.get('attempt_id'),
                 'greedy': clean(g[i].outputs[0].text), 'greedy_raw': g[i].outputs[0].text[:1000]}
            if samp is not None:
                o['samples'] = [clean(x.text) for x in samp[i].outputs]
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    print('[gen] done', flush=True)

if __name__ == '__main__':
    main()
