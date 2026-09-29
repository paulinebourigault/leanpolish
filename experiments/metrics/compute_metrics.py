#!/usr/bin/env python3
"""Unified whole-corpus token metrics for the LeanPolish paper.

Two counters, both applied to the SAME reconstructed text:
  A = `count_lean_tokens`  (Python port of LeanPolish.lean `countLeanTokens`;
      comment-skipping, Lean-aware; leanpolish/lean_counter.py)
  B = `count_appL`         (released Python tokenizer, leanpolish/retokenize_appendixL.py; counts comments)

For every corpus: an explicit input-file list (written to file_lists/<corpus>.txt), the
original text, and the teacher-shortened text reconstructed from the released accepted edits
(shards/<corpus>/training_pairs.jsonl):
  * span edits (start_byte<end_byte) applied in DESCENDING byte order, each checked
    `src[start:end] == original` (mismatch/overlap -> edit skipped and counted);
  * warning_cleanup rows carry no span (start=end=0): candidate texts are built (distinct rows /
    all rows / all occurrences / none, plus the archived *_shortened.lean if shipped) and the one
    whose countLeanTokens equals LeanPolish's own file-level tokens_shortened field is kept; if
    none matches the file is UNRESOLVED (A numerator then taken from that field; B best-effort).
Unshortened input files count 0 saved tokens.

Inputs (environment variables):
  CORPUS_ROOT  LeanPolish run directory: Lake project with .lake/packages/mathlib, corpus sources
               (goedel_workbook/, putnam_bench_proofs/, Putnam2025_AxiomProver/) and the released
               shards/<corpus>/training_pairs.jsonl (default ./corpus)
  EVAL_ROOT    held-out corpora root containing goedel_eval/ (default $CORPUS_ROOT)
  HYBRID_DATA  hybrid run directory with files/<corpus>/<lane>/ (HF experiments/beyond_teacher;
               optional, default ./beyond_teacher)
Outputs: results/metrics.json, results/per_file.json, file_lists/<corpus>.txt.

Usage: python3 experiments/metrics/compute_metrics.py   (~5-10 min, CPU)
"""
from __future__ import annotations
import collections, glob, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('LEANPOLISH_ROOT', HERE.parents[1]))
sys.path.insert(0, str(ROOT / 'leanpolish'))
from lean_counter import count_lean_tokens as cA          # noqa: E402
from retokenize_appendixL import count_appL as cB          # noqa: E402

RO = Path(os.environ.get('CORPUS_ROOT', 'corpus'))
EV = Path(os.environ.get('EVAL_ROOT', RO))
ML = RO / '.lake/packages/mathlib'
BT = Path(os.environ.get('HYBRID_DATA', 'beyond_teacher'))
(HERE / 'results').mkdir(exist_ok=True)
(HERE / 'file_lists').mkdir(exist_ok=True)


def is_artifact(name):
    return name.endswith('_shortened.lean') or name.endswith('_linter.lean')


# ---------------------------------------------------------------- input file sets
def inputs_eval(sub):
    d = EV / 'goedel_eval' / sub
    return {f'goedel_eval/{sub}/{p.name}': p for p in sorted(d.glob('*.lean')) if not is_artifact(p.name)}


def has_theorem(p):
    return re.search(r'^(theorem|lemma)\b', p.read_text(), re.M) is not None


def mathlib_discovery():
    """Exact re-implementation of run_mathlib.discover_mathlib_files() (no subdir, no limit)
    at the Mathlib rev pinned in leanpolish/lake-manifest.json (308445d, v4.21.0)."""
    src = ML / 'Mathlib'
    skip_dirs = {"Tactic", "Lean", "Init", "Control", "Testing"}
    skip = {"Init.lean", "Tactic.lean", "Lean.lean"}
    tre = re.compile(r'\b(by$|:= by\b|simp|ring|omega|linarith|norm_num|decide|exact|rfl|'
                     r'apply|intro|have |obtain|rw |calc|induction|cases)', re.M)
    out = {}
    for f in sorted(src.rglob('*.lean')):
        if f.name in skip:
            continue
        rel = f.relative_to(src)
        if any(p in skip_dirs for p in rel.parts):
            continue
        try:
            t = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if len(tre.findall(t)) >= 3:
            out[f'mathlib_optimization/Mathlib/{rel}'] = f
    return out


PV_CRASH = {'putnam_1978_a5.lean', 'putnam_2010_a4.lean', 'putnam_2018_b3.lean'}  # base_compiles=False (beyond_teacher/compose)


def corpus_specs():
    mf = inputs_eval('minif2f_verified')                      # 351 (3 *_linter.lean artifacts excluded)
    pv_all = inputs_eval('putnam_verified')                   # 22 non-artifact files; 19 after the filters below
    pv = {k: p for k, p in pv_all.items() if has_theorem(p) and p.name not in PV_CRASH}
    ax = {f'Putnam2025_AxiomProver/{p.parent.name}/solution.lean': p
          for p in sorted((RO / 'Putnam2025_AxiomProver').glob('*/solution.lean'))
          if not p.parent.name.startswith('_')}
    gw = {f'goedel_workbook/{p.name}': p for p in sorted((RO / 'goedel_workbook').glob('*.lean'))
          if not is_artifact(p.name)}
    pb = {}
    for sub in ('goedel_solutions_round_0', 'bourbaki-putnam'):
        for p in sorted((RO / 'putnam_bench_proofs' / sub).glob('*.lean')):
            if not is_artifact(p.name):
                pb[f'putnam_bench_proofs/{sub}/{p.name}'] = p
    return [
        ('minif2f', 'minif2f', mf, {'pv_all': None}),
        ('putnam_verified', 'putnam_verified', pv, {'all24': pv_all}),
        ('putnam2025', 'putnam2025_per_file', ax, {}),
        ('putnam2025_pool', 'putnam2025_pool', ax, {}),
        ('goedel', 'goedel', gw, {}),
        ('mathlib', 'mathlib', mathlib_discovery(), {}),
        ('putnam_bench', 'putnam_bench', pb, {}),
    ]


# ---------------------------------------------------------------- reconstruction
def reconstruct(src: str, rows, st):
    b = src.encode()
    spans = [r for r in rows if r['end_byte'] > r['start_byte']]
    cleanups = [r for r in rows if r['end_byte'] <= r['start_byte']]
    applied = []
    last = len(b) + 1
    for r in sorted(spans, key=lambda r: (r['start_byte'], r['end_byte']), reverse=True):
        s, e = r['start_byte'], r['end_byte']
        if e > last:
            st['span_overlap_skipped'] += 1
            continue
        if b[s:e].decode('utf-8', 'replace') != r['original']:
            st['span_mismatch_skipped'] += 1
            continue
        b = b[:s] + r['replacement'].encode() + b[e:]
        last = s
        applied.append(r)
        st['span_applied'] += 1
    t = b.decode()
    if not cleanups:
        return {'spans_only': (t, applied)}
    # cleanup rows have no span: build the candidate texts; the caller keeps the one whose
    # countLeanTokens equals LeanPolish's own file-level tokens_shortened field.
    variants = {}
    t1, ap1, seen = t, list(applied), set()
    for r in cleanups:                                   # (1) distinct rows, first occurrence
        k = (r['original'], r['replacement'])
        if k in seen or not r['original'] or r['original'] not in t1:
            continue
        seen.add(k); t1 = t1.replace(k[0], k[1], 1); ap1.append(r)
    variants['cleanup_dedup'] = (t1, ap1)
    t2, ap2 = t, list(applied)
    for r in cleanups:                                   # (2) every row, first occurrence
        if r['original'] and r['original'] in t2:
            t2 = t2.replace(r['original'], r['replacement'], 1); ap2.append(r)
    variants['cleanup_all_rows'] = (t2, ap2)
    t3, ap3 = t, list(applied)
    for k in dict.fromkeys((r['original'], r['replacement']) for r in cleanups if r['original']):
        t3 = t3.replace(k[0], k[1])                      # (3) every occurrence
    variants['cleanup_replace_all'] = (t3, ap3 + [r for r in cleanups if r['original']])
    variants['cleanup_none'] = (t, list(applied))        # (4) cleanups not realised in output
    return variants


def nbl(t):
    return sum(1 for l in t.splitlines() if l.strip())


def local_saving(rows, cnt):
    return sum(cnt(r['original']) - cnt(r['replacement']) for r in rows)


def run_corpus(name, shard, inputs, extra):
    rows = [json.loads(l) for l in open(RO / 'shards' / shard / 'training_pairs.jsonl')]
    by = collections.defaultdict(list)
    for r in rows:
        by[r['file']].append(r)
    st = collections.Counter()
    shard_not_input = sorted(f for f in by if f not in inputs)
    per_file = {}
    tot = dict(files=len(inputs), shortened=0, edits=0, edits_shard=len(rows),
               A_orig=0, B_orig=0, A_saved=0, B_saved=0, A_local=0, B_local=0,
               A_local_applied=0, B_local_applied=0, A_recfield_saved=0,
               recfield_match_orig=0, recfield_match_short=0, recfield_files=0)
    for key, p in inputs.items():
        src = p.read_text()
        a0, b0 = cA(src), cB(src)
        tot['A_orig'] += a0; tot['B_orig'] += b0
        tot['bytes_orig'] = tot.get('bytes_orig', 0) + len(src.encode())
        tot['lines_orig'] = tot.get('lines_orig', 0) + nbl(src)
        rec = {'A_orig': a0, 'B_orig': b0, 'A_short': a0, 'B_short': b0, 'n_edits': 0}
        if key in by:
            rs = by[key]
            fo = collections.Counter(r['tokens_original'] for r in rs).most_common(1)[0][0]
            fs = collections.Counter(r['tokens_shortened'] for r in rs).most_common(1)[0][0]
            variants = reconstruct(src, rs, st)
            arch = p.with_name(p.stem + '_shortened.lean')
            if arch.exists():                            # archived optimizer output, if shipped
                variants['archived_shortened'] = (arch.read_text(), None)
            chosen = next((v for v in variants if cA(variants[v][0]) == fs), None)
            resolved = chosen is not None
            if chosen is None:
                chosen = next(iter(variants))            # spans_only / cleanup_dedup
                st['UNRESOLVED_files'] += 1
            st['variant_' + chosen] += 1
            short, applied = variants[chosen]
            if applied is None:                          # archived text: attribute all rows
                applied = rs
            a1, b1 = cA(short), cB(short)
            tot['bytes_saved'] = tot.get('bytes_saved', 0) + len(src.encode()) - len(short.encode())
            tot['lines_saved'] = tot.get('lines_saved', 0) + nbl(src) - nbl(short)
            tot['shortened'] += 1
            tot['edits'] += len(rs)
            tot['A_saved'] += a0 - a1; tot['B_saved'] += b0 - b1
            tot['A_local'] += local_saving(rs, cA); tot['B_local'] += local_saving(rs, cB)
            tot['A_local_applied'] += local_saving(applied, cA); tot['B_local_applied'] += local_saving(applied, cB)
            tot['recfield_files'] += 1
            tot['A_recfield_saved'] += fo - fs
            tot['A_primary_saved'] = tot.get('A_primary_saved', 0) + (a0 - (a1 if resolved else fs))
            if not resolved:
                tot['unresolved_A_recon_saved'] = tot.get('unresolved_A_recon_saved', 0) + a0 - a1
                tot['unresolved_A_recfield_saved'] = tot.get('unresolved_A_recfield_saved', 0) + a0 - fs
                tot['unresolved_B_recon_saved'] = tot.get('unresolved_B_recon_saved', 0) + b0 - b1
                tot['unresolved_B_orig'] = tot.get('unresolved_B_orig', 0) + b0
            tot['recfield_match_orig'] += int(fo == a0)
            tot['recfield_match_short'] += int(fs == a1)
            rec.update(A_short=a1, B_short=b1, n_edits=len(rs), rec_tokens_original=fo,
                       rec_tokens_shortened=fs, variant=chosen, resolved=resolved)
            if arch.exists():
                at = variants['archived_shortened'][0]
                rec['archived_bytes_equal'] = (at == short)
                st['archived_compared'] += 1
                st['archived_byte_equal_to_used'] += int(at == short)
                st['archived_A_equal_recfield'] += int(cA(at) == fs)
        per_file[key] = rec
    # shard rows on files that are NOT corpus inputs (e.g. *_linter.lean linter-baseline artifacts)
    na = dict(files=len(shard_not_input), edits=sum(len(by[f]) for f in shard_not_input),
              A_recfield_saved=sum(collections.Counter(r['tokens_original'] - r['tokens_shortened'] for r in by[f]).most_common(1)[0][0]
                                   for f in shard_not_input),
              A_local=sum(local_saving(by[f], cA) for f in shard_not_input),
              B_local=sum(local_saving(by[f], cB) for f in shard_not_input),
              examples=shard_not_input[:5])
    (HERE / 'file_lists' / f'{name}.txt').write_text('\n'.join(inputs) + '\n')
    return dict(totals=tot, recon_stats=dict(st), shard_rows_on_non_inputs=na), per_file


def hybrid_lanes(name, inputs, per_file):
    """Whole-file hybrid results from $HYBRID_DATA/files/<corpus>/<lane>/ on the SAME input set."""
    d = BT / 'files' / name
    if not d.exists() or name.endswith('_pool'):
        return {}
    out = {}
    for lane_dir in sorted(p for p in d.iterdir() if p.is_dir()):
        lane = lane_dir.name
        A = B = n = miss = 0
        for key, p in inputs.items():
            fn = lane_dir / (p.parent.name + '.lean' if name == 'putnam2025' else p.name)
            if not fn.exists():
                miss += 1
                t = None
            else:
                t = fn.read_text(); n += 1
            a = cA(t) if t is not None else per_file[key]['A_orig']
            b = cB(t) if t is not None else per_file[key]['B_orig']
            A += a; B += b
        out[lane] = dict(files_found=n, files_missing=miss, A_total=A, B_total=B)
    return out


def main():
    res, allpf = {}, {}
    for name, shard, inputs, extra in corpus_specs():
        print('==', name, len(inputs), flush=True)
        r, pf = run_corpus(name, shard, inputs, extra)
        r['hybrid'] = hybrid_lanes(name, inputs, pf)
        if name == 'putnam_verified':   # also the 24-file view used by the hybrid experiment
            all24 = extra['all24']
            r['all24_A_orig'] = sum(cA(p.read_text()) for p in all24.values())
            r['all24_B_orig'] = sum(cB(p.read_text()) for p in all24.values())
            r['excluded'] = sorted(set(all24) - set(inputs))
        if name == 'minif2f':
            lin = sorted((EV / 'goedel_eval/minif2f_verified').glob('*_linter.lean'))
            r['linter_artifacts'] = [p.name for p in lin]
            r['linter_artifacts_A'] = sum(cA(p.read_text()) for p in lin)
            r['linter_artifacts_B'] = sum(cB(p.read_text()) for p in lin)
        res[name] = r; allpf[name] = pf
        print(json.dumps(r['totals']), json.dumps(r['recon_stats']), flush=True)
    json.dump(res, open(HERE / 'results' / 'metrics.json', 'w'), indent=1)
    json.dump(allpf, open(HERE / 'results' / 'per_file.json', 'w'))


if __name__ == '__main__':
    main()
