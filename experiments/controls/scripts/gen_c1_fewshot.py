#!/usr/bin/env python3
"""C1 "frozen hybrid": the neural editor of Algorithm 2 replaced by a FROZEN model prompted
with the fixed few-shot chat prompt of experiments/fewshot (same 4 demos, same parse_output).

Everything else is identical to the main hybrid run (experiments/hybrid):
  * same sites (sites_<corpus>_base.jsonl, site prompt = exact SFT prompt template)
  * same decoding as experiments/hybrid/scripts/gen_sites.py: greedy + k=4 samples
    (T=0.6, top_p=0.95, seed 42), max 256 new tokens
  * output rows {site_id, greedy, greedy_raw, samples} consumed unchanged by the hybrid
    screen_sites.py / compose.py.
No whitespace re-anchoring (tactic sites carry no leading indentation / trailing newline).
"""
import os as _os, sys as _sys
from pathlib import Path as _Path
# Release root (contains leanpolish/ and experiments/); override with LEANPOLISH_ROOT.
ROOT = _Path(_os.environ.get('LEANPOLISH_ROOT', _Path(__file__).resolve().parents[3]))
_sys.path.insert(0, str(ROOT / 'experiments' / 'hybrid' / 'scripts'))
_sys.path.insert(0, str(ROOT / 'leanpolish'))
LEAN_PROJECT = _os.environ.get('LEAN_PROJECT', str(ROOT / 'leanpolish'))  # Lake project with Mathlib built
REPL_BIN = _os.environ.get('REPL_BIN', 'repl')  # leanprover-community/repl binary

import argparse, json, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'experiments' / 'fewshot'))
from gen_fewshot import build_messages, render, parse_output  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--sites', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--demos', default=str(HERE / 'fewshot_demos.json'))
    ap.add_argument('--k', type=int, default=4)
    ap.add_argument('--max-model-len', type=int, default=8192)
    ap.add_argument('--gpu-mem-util', type=float, default=0.80)
    ap.add_argument('--limit', type=int)
    args = ap.parse_args()
    t0 = time.time()
    demos = json.load(open(args.demos))
    rows = [json.loads(l) for p in args.sites for l in open(p) if l.strip()]
    if args.limit: rows = rows[:args.limit]
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    prompts = [render(tok, build_messages(demos, r['prompt'])) for r in rows]
    ids = [tok(p, add_special_tokens=False)['input_ids'] for p in prompts]
    keep = [i for i, x in enumerate(ids) if len(x) + 256 <= args.max_model_len]
    print(f'[c1] {len(rows)} sites, {len(rows)-len(keep)} over length (-> no proposal)', flush=True)
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt
    llm = LLM(model=args.model, dtype='bfloat16', seed=42, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_mem_util, trust_remote_code=True)
    t1 = time.time()
    inp = [TokensPrompt(prompt_token_ids=ids[i]) for i in keep]
    g = llm.generate(inp, SamplingParams(temperature=0.0, max_tokens=256))
    s = llm.generate(inp, SamplingParams(temperature=0.6, top_p=0.95, n=args.k, max_tokens=256, seed=42))
    t2 = time.time()
    gi = {i: (g[j], s[j]) for j, i in enumerate(keep)}
    gen_toks = 0
    with open(args.out, 'w') as f:
        for i, r in enumerate(rows):
            o = {'site_id': r['site_id'], 'model': args.model}
            if i in gi:
                gg, ss = gi[i]
                gen_toks += len(gg.outputs[0].token_ids) + sum(len(x.token_ids) for x in ss.outputs)
                o.update(greedy=parse_output(gg.outputs[0].text), greedy_raw=gg.outputs[0].text[:1000],
                         gen_tokens=len(gg.outputs[0].token_ids) + sum(len(x.token_ids) for x in ss.outputs),
                         prompt_tokens=len(ids[i]),
                         samples=[parse_output(x.text) for x in ss.outputs])
            else:
                o.update(greedy=r['original'], greedy_raw='<over_length>', samples=[])
            f.write(json.dumps(o, ensure_ascii=False) + '\n')
    cost = {'stage': 'gen_c1', 'model': args.model, 'sites': args.sites, 'n_sites': len(rows),
            'load_s': round(t1 - t0, 1), 'generate_s': round(t2 - t1, 1), 'gpu_s': round(time.time() - t0, 1),
            'prompt_tokens': sum(len(ids[i]) for i in keep), 'gen_tokens': gen_toks}
    open(args.out + '.cost.json', 'w').write(json.dumps(cost, indent=1))
    print('[c1] done', cost, flush=True)


if __name__ == '__main__':
    main()
