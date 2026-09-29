#!/usr/bin/env python3
"""Render markdown tables from metrics.json. usage: make_tables.py metrics.json examples.jsonl > tables.md"""
import json, sys
m = json.load(open(sys.argv[1]))
ex = [json.loads(l) for l in open(sys.argv[2])] if len(sys.argv) > 2 else []
T = m['teacher']
LANES = ['g4_raw', 'g4_filt', 'g16_raw', 'g16_filt']


def f(n, d):
    return f"{n:,} ({100 * n / d:.2f}%)" if d else '-'


for ed, v in m['editors'].items():
    pf = v['per_file']
    for ctr, cname in (('A', 'counter A = countLeanTokens port (primary)'), ('B', 'counter B = count_appL')):
        print(f"\n#### Editor `{ed}`, {cname}\n")
        print("| File | Original | LeanPolish alone saved | Hybrid saved, raw G+4 | Hybrid saved, raw G+16 | Hybrid saved, filter G+4 | Hybrid saved, filter G+16 |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        tot = {'o': 0, 't': 0, **{l: 0 for l in LANES}}
        for key in sorted(pf):
            o = T[key]['orig'][ctr]; t = T[key]['teacher_saved'][ctr]
            tot['o'] += o; tot['t'] += t
            cells = []
            for l in ('g4_raw', 'g16_raw', 'g4_filt', 'g16_filt'):
                h = pf[key][l]['hybrid_saved'][ctr]; tot[l] += h
                cells.append(f"{f(h, o)} [+{pf[key][l]['neural_increment'][ctr]:,}]")
            tflag = '' if T[key]['teacher_output'] else ' (no teacher output)'
            print(f"| {key} | {o:,} | {f(t, o)}{tflag} | " + ' | '.join(cells) + ' |')
        o = tot['o']
        print(f"| **Total** | **{o:,}** | **{f(tot['t'], o)}** | " + ' | '.join(
            f"**{f(tot[l], o)}** [+{tot[l] - tot['t']:,}]" for l in ('g4_raw', 'g16_raw', 'g4_filt', 'g16_filt')) + ' |')
    print(f"\nPipeline counts (`{ed}`):\n")
    print("| File | sites | sites w/ shorter cand | unique shorter cands | screen pass | verify pass | kept joint raw G+16 | of which filter-ok | kept joint filter G+16 |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for key in sorted(pf):
        p = pf[key]['pipeline']
        print(f"| {key} | {p.get('sites', 0)} | {p.get('sites_with_shorter_cand', 0)} | {p.get('unique_shorter_cands', 0)} | "
              f"{p.get('screen_pass', 0)} | {p.get('verify_pass', 0)} | {pf[key]['g16_raw']['n_kept_joint']} | "
              f"{pf[key]['g16_raw']['n_kept_quality_ok']} | {pf[key]['g16_filt']['n_kept_joint']} |")
    print("\nAll final files verified (fresh `lake env lean`, no error, no sorry): " +
          str(all(pf[k][l]['final_verified'] for k in pf for l in LANES)))

if ex:
    print("\n#### Examples of jointly-kept neural edits (DeepSeek, raw G+16; sorted by appL savings)\n")
    shown = 0
    for flt in (True, False):
        print(f"\n{'Filter-compliant' if flt else 'Rejected by the isQualityUpgrade port'}:\n")
        k = 0
        for e in ex:
            if e['editor'] != 'deepseek' or e['quality_ok'] != flt:
                continue
            g = e['goal'].strip()
            g = g if len(g) < 400 else g[:400] + ' …'
            print(f"- `{e['file']}` (saves A {e['savings_A']}, appL {e['savings']}; budget {e['budget']})\n"
                  f"  - goal: `{' '.join(g.split())}`\n  - original: `{' '.join(e['original'].split())}`\n"
                  f"  - neural edit: `{' '.join(e['replacement'].split()) or '<DELETE>'}`")
            k += 1
            if k >= 6:
                break
