#!/usr/bin/env python3
"""metrics.json -> markdown tables (whole-file reduction matrix + C2 cost/candidate table)."""
import json, re, sys

LABELS = [
    (r'^original$', 'Original'),
    (r'^leanpolish$', 'LeanPolish alone (paper run, = hybrid F1)'),
    (r'^lp_rerun$', 'LeanPolish alone, clean rerun'),
    (r'^MAIN_hybrid_greedy$', 'Hybrid, SFT editor, greedy (main hybrid)'),
    (r'^MAIN_hybrid_all$', 'Hybrid, SFT editor, greedy+4 samples (main hybrid)'),
    (r'^MAIN_hybrid_all_qf$', 'Hybrid, SFT editor, +quality filter (main hybrid)'),
    (r'^c1ds_\w+?_greedy$', 'C1 frozen hybrid, DeepSeek few-shot, greedy'),
    (r'^c1ds_\w+?_all$', 'C1 frozen hybrid, DeepSeek few-shot, greedy+4'),
    (r'^c1ds_\w+?_all_qf$', 'C1 frozen hybrid, DeepSeek few-shot, +quality filter'),
    (r'^c1q7_\w+?_greedy$', 'C1 frozen hybrid, Qwen-7B few-shot, greedy'),
    (r'^c1q7_\w+?_all$', 'C1 frozen hybrid, Qwen-7B few-shot, greedy+4'),
    (r'^c1q7_\w+?_all_qf$', 'C1 frozen hybrid, Qwen-7B few-shot, +quality filter'),
    (r'^c2ds(_(pv|ax|mf))?_k4_orig$', 'C2 LLM-only, DeepSeek-Prover-V2-7B, k=4'),
    (r'^c2ds(_(pv|ax|mf))?_k16_orig$', 'C2 LLM-only, DeepSeek-Prover-V2-7B, k=16'),
    (r'^c2ds(_(pv|ax|mf))?_k4_base$', 'C2 PRE-PASS (LeanPolish -> DeepSeek), k=4'),
    (r'^c2ds(_(pv|ax|mf))?_k16_base$', 'C2 PRE-PASS (LeanPolish -> DeepSeek), k=16'),
    (r'^c2ds(_(pv|ax|mf))?_k4_post$', 'C2 POST-PASS (DeepSeek -> LeanPolish), k=4'),
    (r'^c2ds(_(pv|ax|mf))?_k16_post$', 'C2 POST-PASS (DeepSeek -> LeanPolish), k=16'),
    (r'^c2q32(_(pv|ax|mf))?_k4_orig$', 'C2 LLM-only, Qwen2.5-Coder-32B, k=4'),
    (r'^c2q32(_(pv|ax|mf))?_k16_orig$', 'C2 LLM-only, Qwen2.5-Coder-32B, k=16'),
    (r'^c2q32(_(pv|ax|mf))?_k4_base$', 'C2 PRE-PASS (LeanPolish -> Qwen-32B), k=4'),
    (r'^c2q32(_(pv|ax|mf))?_k16_base$', 'C2 PRE-PASS (LeanPolish -> Qwen-32B), k=16'),
    (r'^c2q32(_(pv|ax|mf))?_k4_post$', 'C2 POST-PASS (Qwen-32B -> LeanPolish), k=4'),
    (r'^c2q32(_(pv|ax|mf))?_k16_post$', 'C2 POST-PASS (Qwen-32B -> LeanPolish), k=16'),
    (r'^c2dsfr_(pv|ax|mf)_k4_lp_rerun$', 'C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=4'),
    (r'^c2dsfr_(pv|ax|mf)_k16_lp_rerun$', 'C2 PRE-PASS on FRESH LeanPolish (-> DeepSeek), k=16'),
    (r'^c2q32fr_(pv|ax|mf)_k4_lp_rerun$', 'C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=4'),
    (r'^c2q32fr_(pv|ax|mf)_k16_lp_rerun$', 'C2 PRE-PASS on FRESH LeanPolish (-> Qwen-32B), k=16'),
    (r'^c3_r1lp$', 'C3 round 1: LeanPolish on hybrid output'),
    (r'^c3_r1$', 'C3 round 1: + SFT editor'),
    (r'^c3_r2lp$', 'C3 round 2: LeanPolish'),
    (r'^c3_r2$', 'C3 round 2: + SFT editor'),
    (r'^c3_r3lp$', 'C3 round 3: LeanPolish'),
    (r'^c3_r3$', 'C3 round 3: + SFT editor'),
]
CORP = [('putnam_verified', 'PB-verified'), ('putnam_verified19', 'PB-verified, paper 19'), ('putnam2025', 'Putnam 2025 AxiomProver'), ('minif2f100', 'miniF2F-100')]


def label(k):
    for pat, lab in LABELS:
        if re.match(pat, k): return lab
    return None


def main():
    m = json.load(open(sys.argv[1]))
    W = m['whole_file']
    out = []
    DESC = {'lean': 'countLeanTokens (Lean-aware, comment-skipping; PRIMARY)', 'raw': 'appL (counts comments)',
            'stripped': 'appL on comment-stripped text'}
    for mode in ('lean', 'raw', 'stripped'):
        out.append(f"\n### Whole-file token reduction, % of ALL original tokens -- {DESC[mode]}\n")
        hdr = '| Condition | ' + ' | '.join(f"{n} ({W[c]['n_files']} files)" for c, n in CORP if c in W) + ' |'
        out += [hdr, '|---|' + '---:|' * sum(c in W for c, _ in CORP)]
        rows = {}
        for c, _ in CORP:
            if c not in W: continue
            for k, v in W[c][mode].items():
                if not isinstance(v, dict): continue
                lab = label(k)
                n4 = (c == 'putnam2025' and re.match(r'^c2(ds|q32)', k)) or (c == 'minif2f100' and k.startswith('c2q32'))
                if n4 and '_k16_' in k: continue   # generated with n=4 only
                if lab: rows.setdefault(lab, {})[c] = v
        order = [lab for _, lab in LABELS]
        for lab in order:
            if lab not in rows: continue
            cells = []
            for c, _ in CORP:
                if c not in W: continue
                v = rows[lab].get(c)
                cells.append('—' if v is None else f"{v['reduction_pct']:.2f} ({v['saved']:,}; {v['files_changed']}f)")
            out.append(f'| {lab} | ' + ' | '.join(cells) + ' |')
        tot = {c: W[c][mode]['original']['tokens'] for c, _ in CORP if c in W}
        out.append('\nOriginal tokens (this counter): ' + ', '.join(f'{c} {t:,}' for c, t in tot.items()))
    out.append('\n### C2 cost and candidate statistics (per model / corpus / input / k)\n')
    out.append('Lean calls = REPL declaration re-elaborations (screen) + REPL file boots + fresh `lake env lean` compiles (compose). '
               'GPU-s = generation run GPU seconds (incl. model load) apportioned by generated tokens. '
               '"compile rate" = screen-pass / distinct strictly-shorter rewrites (exhaustive screens only; Axiom uses exact early stopping, marked *). '
               'Saved = whole-file countLeanTokens saved vs the ORIGINAL files (pre-pass rows include LeanPolish\'s savings).\n')
    out.append('| model | corpus | input | k | units | samples | parse ok | stmt changed / no code / other | shorter rewrites | compile rate | units w/ pass | edits applied | gen tokens | GPU-s | Lean calls | saved | saved / 1k Lean calls |')
    out.append('|---|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|')
    for key, st in sorted(m.get('c2_candidates', {}).items()):
        M, C, V, K = key.split('|')
        if K == 'k16' and (C == 'putnam2025' or (C == 'minif2f100' and M.startswith('c2q32'))): continue   # n=4 only
        ok = st.get('parse_ok', 0) + st.get('parse_ok_truncated', 0)
        bad = f"{st.get('parse_statement_changed', 0)} / {st.get('parse_no_code', 0) + st.get('parse_decl_not_found', 0)} / {st.get('parse_forbidden', 0)}"
        sh = st.get('distinct_shorter_cands', 0)
        rate = f"{100 * st.get('screen_pass', 0) / sh:.0f}%" if sh else '-'
        if not st.get('screen_exhaustive', True): rate += '*'
        wf = W.get(C, {}).get('lean', {}).get(f'{M}_{K}_{V}')
        saved = wf['saved'] if isinstance(wf, dict) else None
        calls = st.get('lean_calls', 0)
        per = f"{1000 * saved / calls:,.0f}" if saved is not None and calls else '-'
        inp = {'base': 'LeanPolish (archived)', 'orig': 'original', 'lp_rerun': 'LeanPolish (fresh)'}[V]
        out.append(f"| {M} | {C} | {inp} | {K} | {st.get('units', 0)} | {st.get('samples', 0)} | {ok} | {bad} | "
                   f"{sh} | {rate} | {st.get('units_with_passing_shorter', 0)} | {st.get('compose_edits_applied', 0)} | "
                   f"{st.get('gen_tokens', 0):,} | {st.get('gpu_s_share', '-')} | {calls} | {saved if saved is not None else '-'} | {per} |")
    print('\n'.join(out))


if __name__ == '__main__':
    main()
