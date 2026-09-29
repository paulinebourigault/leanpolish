#!/usr/bin/env python3
"""Frozen few-shot baseline: chat-templated k=4 in-context local-edit demos.

Control experiment: a strong *frozen* (not fine-tuned) baseline.
Each eval site is presented to the model through its own chat template as a
multi-turn conversation:

    user: <demo_1 prompt>   assistant: <demo_1 target>
    ...                     (k = 4 demos: 2 tactic-replacement, 2 deletion)
    user: <eval-site prompt>

Demo prompts/targets are the verbatim SFT-format rows from
sft_train.jsonl (built by experiments/sft/build_sft_data.py) (same instruction, [GOAL],
[LOCAL CONTEXT], [ORIGINAL FRAGMENT], [REPLACEMENT] layout as the eval
prompts), chosen deterministically (seed 0) from "short" rows. The demo set
is fixed across all sites and both models. Greedy decoding only.

Output parsing (parse_output): strip code fences, drop an echoed
"[REPLACEMENT]" header, cut at the first blank line or at the first
closing / section marker ([GOAL], [ORIGINAL FRAGMENT], ..., <|..., </s>,
```), strip; an output starting with <DELETE> maps to "" (deletion).

Whitespace re-anchoring (default ON, --no-anchor to disable): dead-code
sites span a whole line including leading indentation and the trailing
newline; a non-empty model answer is re-indented with the original's
leading whitespace and given the trailing newline so a line-level rewrite
is not penalized for layout. This can only help the baseline.

Modes:
  --dump-demos-only   write the demo set + rendered prompt examples and exit
                      (needs only `transformers` for the tokenizer)
  default             vLLM generation for all sites -> candidates jsonl

Usage:
  python gen_fewshot.py --model deepseek-ai/DeepSeek-Prover-V2-7B \
      --tag fewshot_deepseek --sites data/eval_sites_*.jsonl \
      --train data/sft_train.jsonl --out cands_fewshot_deepseek.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

DELETE_TOKEN = "<DELETE>"
SECTION_MARKERS = ("[GOAL]", "[LOCAL CONTEXT]", "[ORIGINAL FRAGMENT]",
                   "[REPLACEMENT]", "You are editing a Lean 4 proof")
STOP_MARKERS = ("<|", "</s>", "<｜", "```", "<end_of", "<eos>")

HERE = Path(__file__).resolve().parent


# ─────────────────────────────── demo selection ──────────────────────────────

def fragment_of(prompt: str) -> str:
    return prompt.split("[ORIGINAL FRAGMENT]\n", 1)[1].rsplit(
        "\n\n[REPLACEMENT]", 1)[0]


def select_demos(train_path: str, seed: int = 0, n_tactic: int = 2,
                 n_delete: int = 2, max_prompt_chars: int = 900,
                 max_target_chars: int = 80) -> list[dict]:
    """Deterministic demo selection.

    Pools (from sft_train.jsonl, file order, then sorted for determinism):
      tactic: type == tactic_replacement, target != <DELETE>, non-empty,
              len(prompt) <= max_prompt_chars, len(target) <= max_target_chars,
              target strictly shorter (chars) than the original fragment
      delete: type == dead_code_removal, target == <DELETE>,
              len(prompt) <= max_prompt_chars
    rng = random.Random(seed); sample n_tactic from tactic pool, then
    n_delete from delete pool. Order in the conversation: T, D, T, D.
    """
    rows = [json.loads(l) for l in open(train_path) if l.strip()]
    tac, dele = [], []
    for r in rows:
        p, t = r["prompt"], r["target"]
        if len(p) > max_prompt_chars:
            continue
        if r.get("type") == "tactic_replacement" and t and t != DELETE_TOKEN \
                and len(t) <= max_target_chars \
                and len(t.strip()) < len(fragment_of(p).strip()):
            tac.append(r)
        elif r.get("type") == "dead_code_removal" and t == DELETE_TOKEN:
            dele.append(r)
    key = lambda r: (r.get("file") or "", r["prompt"], r["target"])
    tac.sort(key=key)
    dele.sort(key=key)
    rng = random.Random(seed)
    t_pick = rng.sample(tac, n_tactic)
    d_pick = rng.sample(dele, n_delete)
    demos = []
    for i in range(max(n_tactic, n_delete)):
        if i < n_tactic:
            demos.append(t_pick[i])
        if i < n_delete:
            demos.append(d_pick[i])
    return [{"prompt": d["prompt"], "target": d["target"],
             "type": d["type"], "file": d.get("file")} for d in demos]


def build_messages(demos: list[dict], site_prompt: str) -> list[dict]:
    msgs = []
    for d in demos:
        msgs.append({"role": "user", "content": d["prompt"]})
        msgs.append({"role": "assistant", "content": d["target"]})
    msgs.append({"role": "user", "content": site_prompt})
    return msgs


def render(tok, msgs) -> str:
    return tok.apply_chat_template(msgs, tokenize=False,
                                   add_generation_prompt=True)


# ─────────────────────────────── output parsing ──────────────────────────────

def parse_output(text: str) -> str:
    """Model text -> replacement string ("" for deletion)."""
    t = text
    # strip a leading reasoning block if a model emits one
    if "</think>" in t:
        t = t.split("</think>", 1)[1]
    t = t.lstrip()
    # opening code fence (```lean / ```lean4 / ```) -> drop the fence line
    m = re.match(r"```[A-Za-z0-9_+-]*[ \t]*\n?", t)
    if m:
        t = t[m.end():]
    # echoed header
    if t.startswith("[REPLACEMENT]"):
        t = t[len("[REPLACEMENT]"):].lstrip("\n")
    t = t.lstrip("\n")
    if t.strip().startswith(DELETE_TOKEN):
        return ""
    # cut at first blank line
    t = re.split(r"\n[ \t]*\n", t, maxsplit=1)[0]
    # cut at first stop / section marker
    cut = len(t)
    for mk in STOP_MARKERS + SECTION_MARKERS:
        i = t.find(mk)
        if i != -1:
            cut = min(cut, i)
    t = t[:cut]
    t = t.strip()
    if t.startswith(DELETE_TOKEN):
        return ""
    return t


def anchor(replacement: str, original: str) -> str:
    """Re-apply the original span's leading indentation / trailing newline
    to a non-empty replacement (line-spanning dead-code sites)."""
    if not replacement:
        return replacement
    lead = original[:len(original) - len(original.lstrip(" \t"))]
    trail = "\n" if original.endswith("\n") else ""
    if not lead and not trail:
        return replacement
    lines = replacement.split("\n")
    body = lead + lines[0].lstrip(" \t") + "".join(
        "\n" + (lead + l.lstrip(" \t") if l.strip() else l) for l in lines[1:])
    return body + trail


# ──────────────────────────────────── main ───────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sites", nargs="+", required=True)
    ap.add_argument("--train", required=True, help="sft_train.jsonl (demo pool)")
    ap.add_argument("--out", required=False)
    ap.add_argument("--demo-seed", type=int, default=0)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-mem-util", type=float, default=0.90)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--enforce-eager", action="store_true")
    ap.add_argument("--no-anchor", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="first N sites (smoke)")
    ap.add_argument("--dump-demos-only", action="store_true")
    args = ap.parse_args()

    demos = select_demos(args.train, seed=args.demo_seed)
    demo_path = HERE / "fewshot_demos.json"
    demo_path.write_text(json.dumps(demos, indent=2, ensure_ascii=False))

    sites = []
    for path in args.sites:
        with open(path) as f:
            for line in f:
                if line.strip():
                    sites.append(json.loads(line))
    if args.limit:
        sites = sites[:args.limit]
    print(f"[fewshot] {len(sites)} sites, {len(demos)} demos, model={args.model}")

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    prompts = [render(tok, build_messages(demos, s["prompt"])) for s in sites]
    lens = [len(tok(p, add_special_tokens=False)["input_ids"]) for p in prompts]
    print(f"[fewshot] prompt tokens: min {min(lens)} max {max(lens)} "
          f"mean {sum(lens)/len(lens):.0f}")
    too_long = sum(1 for n in lens if n + args.max_new_tokens > args.max_model_len)
    if too_long:
        print(f"[fewshot] ERROR: {too_long} prompts exceed max_model_len", file=sys.stderr)
        sys.exit(1)
    safe = args.tag.replace("/", "_")
    (HERE / f"fewshot_prompt_rendered_{safe}.txt").write_text(prompts[0])
    if args.dump_demos_only:
        print(f"[fewshot] wrote {demo_path} and rendered example; exiting")
        return

    from vllm import LLM, SamplingParams
    llm = LLM(model=args.model, dtype="bfloat16", seed=args.seed,
              max_model_len=args.max_model_len,
              gpu_memory_utilization=args.gpu_mem_util,
              trust_remote_code=True, enforce_eager=args.enforce_eager)
    greedy = SamplingParams(temperature=0.0, max_tokens=args.max_new_tokens)
    # prompts are already chat-templated strings incl. BOS where the template
    # adds it; vLLM would add BOS again for some tokenizers -> pass token ids.
    ids = [tok(p, add_special_tokens=False)["input_ids"] for p in prompts]
    try:
        from vllm.inputs import TokensPrompt
        inputs = [TokensPrompt(prompt_token_ids=i) for i in ids]
    except ImportError:
        inputs = [{"prompt_token_ids": i} for i in ids]
    outs = llm.generate(inputs, greedy)

    n_del = n_empty_tac = 0
    with open(args.out, "w") as f:
        for site, res in zip(sites, outs):
            raw = res.outputs[0].text
            rep0 = parse_output(raw)
            rep = rep0 if args.no_anchor else (
                anchor(rep0, site["original"])
                if site["type"] == "dead_code_removal" else rep0)
            n_del += rep == ""
            f.write(json.dumps({
                "model_tag": args.tag, "model": args.model,
                "decoding_index": "greedy",
                "corpus": site["corpus"], "file": site["file"],
                "start_byte": site["start_byte"], "end_byte": site["end_byte"],
                "original": site["original"], "replacement": rep,
                "replacement_parsed": rep0, "raw_output": raw[:2000],
                "content_sha256": site.get("content_sha256"),
                "type": site["type"], "kind": site.get("kind"),
                "attempt_id": site.get("attempt_id"),
                "reference_replacement": site.get("reference_replacement"),
                "tokens_original": site.get("tokens_original"),
                "prompt_tokens": len(res.prompt_token_ids),
                "finish_reason": res.outputs[0].finish_reason,
            }, ensure_ascii=False) + "\n")
    print(f"[fewshot] wrote {len(sites)} candidates -> {args.out} "
          f"({n_del} deletions)")


if __name__ == "__main__":
    main()
