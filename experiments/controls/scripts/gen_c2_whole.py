#!/usr/bin/env python3
"""C2 generation: a FROZEN model rewrites each whole proof (declaration unit from
c2_build_sites.py) to be shorter; n=16 samples at T=0.7 (top_p 0.95, seed 42).
The first 4 samples form the k=4 condition (nested budgets).

Parsing: take the last fenced code block (or the text after an unclosed fence), drop
`import`/`set_option`/`open` preamble lines echoed before the declaration, and cut the text
so it starts at the original declaration keyword + name. A candidate is kept only if
  * its statement is unchanged: whitespace-normalised text before the first ':=' equals the
    original's (so the model cannot weaken/alter the theorem),
  * it introduces none of sorry/admit/axiom/native_decide/implemented_by/extern/unsafe that
    the original does not already contain.
Rejected / unparsable samples are replaced by the original text (no-op, filtered as "not
shorter" downstream). Writes <out>_k16.jsonl and <out>_k4.jsonl in the hybrid gens schema
{site_id, greedy, samples} (greedy := sample 0; this is a sampling-only condition).
"""
import argparse, json, re, sys, time
from pathlib import Path

INSTR = (
    "The following Lean 4 declaration (Lean v4.21.0, Mathlib) compiles. Rewrite it so that its "
    "proof is as short as possible (fewest tokens) while still compiling. Keep the declaration "
    "keyword, name and statement exactly unchanged; only change the proof after `:=`. Do not use "
    "`sorry`, `admit`, new axioms or `native_decide`. Earlier declarations of the file are "
    "available and may be used. Output only the complete rewritten declaration in a single "
    "```lean4 code block.")
FORBID = ('sorry', 'admit', 'axiom', 'native_decide', 'implemented_by', 'extern', 'unsafe', 'decide := true')


def build_prompt(u):
    return (f"{INSTR}\n\nContext (earlier part of the file, for reference only):\n```lean4\n"
            f"{u['context'].rstrip()}\n```\n\nDeclaration to shorten:\n```lean4\n{u['original']}\n```")


def norm(s):
    return ' '.join(s.split())


def parse(text, u):
    t = text
    if '</think>' in t:
        t = t.split('</think>', 1)[1]
    blocks = re.findall(r'```[A-Za-z0-9_]*[ \t]*\n(.*?)```', t, flags=re.S)
    if blocks:
        code = blocks[-1]
    else:
        m = re.search(r'```[A-Za-z0-9_]*[ \t]*\n', t)
        if not m:
            return None, 'no_code'
        code = t[m.end():]
    # locate the declaration start: first line of the original signature
    first = u['original'].split('\n', 1)[0].strip()
    key = ' '.join(first.split()[:2])  # e.g. "theorem putnam_2018_b3"
    idx = code.find(key)
    if idx < 0:
        return None, 'decl_not_found'
    cand = code[idx:].rstrip()
    if not norm(cand).startswith(norm(u['signature']) + ' :=') and norm(cand.split(':=', 1)[0]) != norm(u['signature']):
        return None, 'statement_changed'
    for w in FORBID:
        if re.search(r'(?<![A-Za-z0-9_])' + re.escape(w) + r'(?![A-Za-z0-9_])', cand) and w not in u['original']:
            return None, 'forbidden:' + w
    return cand, 'ok'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--units', nargs='+', required=True)
    ap.add_argument('--out', required=True, help='prefix; writes <out>_k16.jsonl, <out>_k4.jsonl, <out>_raw.jsonl')
    ap.add_argument('--n', type=int, default=16)
    ap.add_argument('--temperature', type=float, default=0.7)
    ap.add_argument('--max-model-len', type=int, default=16384)
    ap.add_argument('--max-gen', type=int, default=6144)
    ap.add_argument('--gpu-mem-util', type=float, default=0.90)
    ap.add_argument('--tp', type=int, default=1)
    ap.add_argument('--limit', type=int)
    args = ap.parse_args()
    t0 = time.time()
    units = [json.loads(l) for p in args.units for l in open(p) if l.strip()]
    if args.limit: units = units[:args.limit]
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    ids, budgets = [], []
    for u in units:
        msgs = [{'role': 'user', 'content': build_prompt(u)}]
        p = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        x = tok(p, add_special_tokens=False)['input_ids']
        need = min(args.max_gen, int(1.5 * len(tok(u['original'], add_special_tokens=False)['input_ids'])) + 768)
        ids.append(x); budgets.append(need if len(x) + need <= args.max_model_len else
                                      max(0, args.max_model_len - len(x)))
    keep = [i for i in range(len(units))
            if budgets[i] >= len(tok(units[i]['original'], add_special_tokens=False)['input_ids']) + 64]
    print(f'[c2] {len(units)} units; {len(units)-len(keep)} skipped (too long for context)', flush=True)
    from vllm import LLM, SamplingParams
    from vllm.inputs import TokensPrompt
    llm = LLM(model=args.model, dtype='bfloat16', seed=42, max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_mem_util, trust_remote_code=True,
              tensor_parallel_size=args.tp)
    t1 = time.time()
    inp = [TokensPrompt(prompt_token_ids=ids[i]) for i in keep]
    sps = [SamplingParams(temperature=args.temperature, top_p=0.95, n=args.n, max_tokens=budgets[i], seed=42)
           for i in keep]
    res = llm.generate(inp, sps)
    t2 = time.time()
    outs = {i: r for i, r in zip(keep, res)}
    stats, gen_toks = {}, 0
    f16, f4, fr = (open(f'{args.out}_{s}.jsonl', 'w') for s in ('k16', 'k4', 'raw'))
    for i, u in enumerate(units):
        samples, why = [], []
        if i in outs:
            for o in outs[i].outputs:
                gen_toks += len(o.token_ids)
                c, w = parse(o.text, u)
                if c is not None and o.finish_reason == 'length' and not o.text.rstrip().endswith('```'):
                    w = 'ok_truncated'
                why.append(w); stats[w] = stats.get(w, 0) + 1
                samples.append(c if c is not None else u['original'])
            fr.write(json.dumps({'site_id': u['site_id'], 'raw': [o.text[-6000:] for o in outs[i].outputs],
                                 'gen_tokens': [len(o.token_ids) for o in outs[i].outputs],
                                 'prompt_tokens': len(ids[i]),
                                 'why': why, 'finish': [o.finish_reason for o in outs[i].outputs]},
                                ensure_ascii=False) + '\n')
        else:
            stats['skipped_context'] = stats.get('skipped_context', 0) + 1
            samples = [u['original']]
        f16.write(json.dumps({'site_id': u['site_id'], 'greedy': samples[0], 'samples': samples[1:16], 'why': why},
                             ensure_ascii=False) + '\n')
        f4.write(json.dumps({'site_id': u['site_id'], 'greedy': samples[0], 'samples': samples[1:4], 'why': why[:4]},
                            ensure_ascii=False) + '\n')
    for f in (f16, f4, fr): f.close()
    cost = {'stage': 'gen_c2', 'model': args.model, 'n_units': len(units), 'n_generated': len(keep),
            'load_s': round(t1 - t0, 1), 'generate_s': round(t2 - t1, 1), 'gpu_s': round(time.time() - t0, 1),
            'prompt_tokens': sum(len(ids[i]) for i in keep), 'gen_tokens': gen_toks, 'parse_stats': stats}
    open(args.out + '.cost.json', 'w').write(json.dumps(cost, indent=1))
    print('[c2] done', cost, flush=True)


if __name__ == '__main__':
    main()
