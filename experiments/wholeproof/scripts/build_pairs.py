#!/usr/bin/env python3
"""Build whole-proof (original file -> LeanPolish-shortened file) SFT pairs from Goedel-Workbook.

Reconstruction of the teacher-shortened file from the accepted-edit shard
(<SHARDS_ROOT>/shards/goedel/training_pairs.jsonl):
  * span edits (tactic_replacement / dead_code_removal / l2_replacement) are applied in
    DESCENDING start_byte order; before applying each, the bytes at [start,end) must equal the
    row's `original` text and spans must not overlap -> otherwise the file is dropped;
  * warning_cleanup rows carry no byte span (start=end=0) but a 1-based `line`; after the span
    edits, each distinct (line, original) is removed (whole line if the stripped line equals it,
    else the substring), bottom-up; failure -> file dropped;
  * VALIDATION: the reconstructed file's byte length must equal the shard's per-file
    `bytes_shortened` (the teacher's own output size) -> otherwise dropped.
Only files in the SFT TRAIN split (experiments/sft data/sft_train.jsonl file set, which is
the seed-42 file-level split of build_sft_data.py; sft_val files excluded) are used.
No-change pairs: ~10% of pairs are (teacher-shortened -> teacher-shortened) on further train
files, teaching the model to leave already-polished proofs alone.
Length cap: prompt+target <= MAXLEN DeepSeek tokens.
"""
import collections, json, os, random, sys
from pathlib import Path

# usage: build_pairs.py OUT_DIR   (env SHARDS_ROOT: dataset root containing shards/;
#        SFT_DATA: directory with sft_train.jsonl / sft_val.jsonl from experiments/sft/build_sft_data.py)
RO = Path(os.environ.get('SHARDS_ROOT', 'data'))
SPLIT = Path(os.environ.get('SFT_DATA', 'data/sft'))
OUT = Path(sys.argv[1])
MAXLEN = 8192
TOK = 'deepseek-ai/DeepSeek-Prover-V2-7B'
INSTR = "Rewrite this Lean 4 proof to be shorter while remaining correct. Output the full file."


def prompt_text(src):
    return f"{INSTR}\n\n```lean4\n{src.rstrip()}\n```"


def target_text(dst):
    return f"```lean4\n{dst.rstrip()}\n```"


def wc_apply(b, wc):
    lines = b.decode().split('\n')
    for ln, o in sorted({(r['line'], r['original']) for r in wc}, reverse=True):
        i = ln - 1
        if i >= len(lines) or o not in lines[i]:
            return None
        if lines[i].strip() == o:
            del lines[i]
        else:
            lines[i] = lines[i].replace(o, '', 1).rstrip()
            if not lines[i].strip():
                del lines[i]
    return '\n'.join(lines).encode()


def reconstruct(src, rs):
    sp = sorted([r for r in rs if r['type'] != 'warning_cleanup'], key=lambda r: -r['start_byte'])
    wc = [r for r in rs if r['type'] == 'warning_cleanup']
    b, prev = src, None
    for r in sp:
        if prev is not None and r['end_byte'] > prev:
            return None, 'overlap'
        if b[r['start_byte']:r['end_byte']] != r['original'].encode():
            return None, 'span_mismatch'
        b = b[:r['start_byte']] + r['replacement'].encode() + b[r['end_byte']:]
        prev = r['start_byte']
    if wc:
        b = wc_apply(b, wc)
        if b is None:
            return None, 'cleanup_line_mismatch'
    if len(b) != rs[0]['bytes_shortened']:
        return None, 'size_neq_bytes_shortened'
    return b, 'ok'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    train_files = {json.loads(l)['file'] for l in open(SPLIT / 'sft_train.jsonl')}
    val_files = {json.loads(l)['file'] for l in open(SPLIT / 'sft_val.jsonl')}
    rows = collections.defaultdict(list)
    for l in open(RO / 'shards/goedel/training_pairs.jsonl'):
        r = json.loads(l)
        if r.get('outcome') == 'accepted':
            rows[r['file']].append(r)
    st = collections.Counter()
    good = []
    for f, rs in sorted(rows.items()):
        if f in val_files:
            st['skip_val_split'] += 1; continue
        if f not in train_files:
            st['skip_not_in_train_split'] += 1; continue
        p = RO / f
        if not p.exists():
            st['skip_missing_source'] += 1; continue
        src = p.read_bytes()
        dst, why = reconstruct(src, rs)
        st['recon_' + why] += 1
        if dst is None:
            continue
        if dst == src:
            st['recon_identical'] += 1; continue
        good.append((f, src.decode(), dst.decode()))
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(TOK)

    def n_tokens(s, t):
        msgs = [{'role': 'user', 'content': prompt_text(s)}, {'role': 'assistant', 'content': target_text(t)}]
        return len(tok.apply_chat_template(msgs, tokenize=True))
    rng = random.Random(42)
    rng.shuffle(good)
    pairs = []
    for f, s, t in good:
        n = n_tokens(s, t)
        if n > MAXLEN:
            st['drop_too_long'] += 1; continue
        pairs.append({'file': f, 'kind': 'shorten', 'source': s, 'target': t, 'n_tokens': n})
    # no-change pairs: teacher output -> itself, on a disjoint 10% slice
    n_nc = round(len(pairs) / 9)
    nc, sh = pairs[:n_nc], pairs[n_nc:]
    nc = [{'file': p['file'], 'kind': 'nochange', 'source': p['target'], 'target': p['target'],
           'n_tokens': n_tokens(p['target'], p['target'])} for p in nc]
    allp = sh + nc
    rng.shuffle(allp)
    with open(OUT / 'wp_train.jsonl', 'w') as fo:
        for p in allp:
            fo.write(json.dumps({'file': p['file'], 'kind': p['kind'],
                                 'messages': [{'role': 'user', 'content': prompt_text(p['source'])},
                                              {'role': 'assistant', 'content': target_text(p['target'])}],
                                 'n_tokens': p['n_tokens']}, ensure_ascii=False) + '\n')
    tot = sum(p['n_tokens'] for p in allp)
    st.update({'pairs_shorten': len(sh), 'pairs_nochange': len(nc), 'pairs_total': len(allp),
               'total_tokens': tot, 'mean_tokens': round(tot / len(allp), 1),
               'max_tokens': max(p['n_tokens'] for p in allp)})
    json.dump(dict(st), open(OUT / 'build_stats.json', 'w'), indent=1)
    print(dict(st))


if __name__ == '__main__':
    main()
