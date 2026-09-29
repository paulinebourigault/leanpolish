#!/usr/bin/env python3
"""Build the paper's LaTeX tables (tables.tex) + a markdown numbers dump (tables.md) from
metrics.json, recompute_numbers_port.json, reference_row.json, fewshot_metrics_port.json,
frontier_port.json (all in results/). Run after compute_metrics.py / learning_table_port.py /
reference_row.py / fewshot_port.py / frontier_port.py."""
import json
from pathlib import Path
H = Path(__file__).resolve().parent / 'results'
M = json.load(open(H / 'metrics.json'))
LP = json.load(open(H / 'recompute_numbers_port.json'))
LA = json.load(open(H / 'recompute_numbers.json'))
REF = json.load(open(H / 'reference_row.json'))
FS = json.load(open(H / 'fewshot_metrics_port.json'))['results']
FR = json.load(open(H / 'frontier_port.json'))


from fractions import Fraction
from decimal import Decimal, ROUND_HALF_UP
def hu(num, den, d=1):  # round-half-up percentage on the exact fraction (as recompute_numbers.pct)
    q = Decimal(100 * num) / Decimal(den)
    return str(q.quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))
def c(n): return f'{n:,}'.replace(',', '{,}')
def p(a, b, d=2): return f'{100 * a / b:.{d}f}'


ROWS = [  # key, label
    ('mathlib', 'Mathlib v4.21.0 subset (human)'),
    ('goedel', 'Goedel-Workbook (Goedel-Prover-V2)'),
    ('putnam_bench', 'PutnamBench sample (Goedel-Prover-V2)'),
    ('minif2f', 'miniF2F verified (Goedel-Prover-V2)'),
    ('putnam_verified', 'PutnamBench verified (Goedel-Prover-V2)'),
    ('putnam2025', 'Putnam 2025 (AxiomProver)'),
]
APPROX = {'goedel', 'putnam_bench'}   # count_appL/bytes/lines numerators reconstructed with unresolved cleanup rows
md = []
tex = []

# ------------------------------------------------------------ Table 1 (tab:corpora)
tex.append(r"""% ---- Table 1 (tab:corpora) replacement: token columns under the Lean-aware counter (A) ----
\begin{tabular}{lrrrrrrr}
\toprule
Source (generator) & Input files & Files & Accepted & Failed siblings & Tok.\ red.\ (\%) & Density & tok/edit \\
\midrule""")
FAILED = {'mathlib': 26912, 'goedel': 28525, 'putnam_bench': 5930, 'minif2f': 3753, 'putnam_verified': 254, 'putnam2025': '147 / 75'}
ACC_REL = {'mathlib': '6{,}695', 'goedel': '20{,}822', 'putnam_bench': '4{,}354', 'minif2f': '1{,}184',
           'putnam_verified': '80', 'putnam2025': '142 / 125'}
FILES_REL = {'mathlib': 2233, 'goedel': 10052, 'putnam_bench': 352, 'minif2f': 308, 'putnam_verified': 16, 'putnam2025': 10}
md.append('| corpus | input files | shortened input files | edits on input files | A orig | A saved (whole-file) | A red % | A density | A tok/edit | B orig | B saved | B red % | B density | B tok/edit | A local-sum | B local-sum |')
md.append('|' + '---|' * 16)
for k, lab in ROWS:
    t = M[k]['totals']
    sA, sB = t['A_primary_saved'], t['B_saved']
    tex.append(f"{lab} & {c(t['files'])} & {c(FILES_REL[k])} & {ACC_REL[k]} & {FAILED[k] if isinstance(FAILED[k], str) else c(FAILED[k])} & "
               f"{p(sA, t['A_orig'])} & {1000 * t['edits'] / t['A_orig']:.2f} & {sA / t['edits']:.1f} \\\\")
    md.append(f"| {k} | {t['files']:,} | {t['shortened']:,} | {t['edits']:,} | {t['A_orig']:,} | {sA:,} | {p(sA, t['A_orig'], 3)} | "
              f"{1000 * t['edits'] / t['A_orig']:.3f} | {sA / t['edits']:.2f} | {t['B_orig']:,} | {sB:,}{'~' if k in APPROX else ''} | "
              f"{p(sB, t['B_orig'], 3)} | {1000 * t['edits'] / t['B_orig']:.3f} | {sB / t['edits']:.2f} | {t['A_local']:,} | {t['B_local']:,} |")
pool = M['putnam2025_pool']['totals']
md.append(f"| putnam2025_pool | {pool['files']} | {pool['shortened']} | {pool['edits']} | {pool['A_orig']:,} | {pool['A_saved']:,} | "
          f"{p(pool['A_saved'], pool['A_orig'], 3)} | {1000 * pool['edits'] / pool['A_orig']:.3f} | {pool['A_saved'] / pool['edits']:.2f} | "
          f"{pool['B_orig']:,} | {pool['B_saved']:,} | {p(pool['B_saved'], pool['B_orig'], 3)} | | | {pool['A_local']:,} | {pool['B_local']:,} |")
tex.append(r"""\midrule
Total (distinct files) & & 12{,}972 & 33{,}402 & 65{,}596 & & & \\
\bottomrule
\end{tabular}
% Input files = every input file of the corpus (list in experiments/metrics/file_lists/); files the optimizer
% did not shorten (incl. optimizer timeouts/errors) count 0. Density = accepted edits on input files per 1,000
% original tokens; tok/edit = whole-file tokens saved / accepted edits on input files. Putnam 2025: sequential config.
""")

# ------------------------------------------------------------ Linter table + appendix tables
tex.append(r"""% ---- tab:linter, LeanPolish column (A); linter column NOT recomputed (see experiments/metrics/README.md) ----
\begin{tabular}{lrrr}
\toprule
Input proofs (files shortened / total) & \LP{} & \texttt{unusedTactic} linter & ProofOptimizer (ref.) \\
\midrule""")
for k, lab, lint, po in (('minif2f', 'miniF2F, Goedel-Prover-V2', '0.002', '87.9'),
                         ('putnam_verified', 'PutnamBench, Goedel-Prover-V2', '0.000', '57.2'),
                         ('goedel', 'Goedel-Workbook', '0.010', '---'),
                         ('mathlib', 'Mathlib v4.21.0 subset', '0.000', '---'),
                         ('putnam2025', 'Putnam 2025, AxiomProver', '0.000', '---')):
    t = M[k]['totals']
    lab2 = f"{lab} ({t['shortened']}/{t['files']})" if k in ('minif2f', 'putnam_verified') else lab
    d = 1 if k in ('minif2f', 'putnam_verified') else 2
    tex.append(f"{lab2} & {p(t['A_primary_saved'], t['A_orig'], d)} & {lint} & {po} \\\\")
tex.append(r"""\bottomrule
\end{tabular}
""")
tex.append(r"""% ---- Appendix B/T/L table, LeanPolish columns (T = Lean-aware counter A; B,L exact denominators) ----
\begin{tabular}{lrrr}
\toprule
Corpus & B & T & L \\
\midrule""")
for k, lab in (('minif2f', 'miniF2F (Goedel-V2 verified)'), ('putnam_verified', 'PutnamBench (Goedel-V2 verified)'),
               ('mathlib', 'Mathlib v4.21.0'), ('goedel', 'Goedel-Workbook'),
               ('putnam_bench', 'PutnamBench (Goedel sample)'), ('putnam2025', 'Putnam 2025 / AxiomProver')):
    t = M[k]['totals']
    tex.append(f"{lab} & {p(t['bytes_saved'], t['bytes_orig'])} & {p(t['A_primary_saved'], t['A_orig'])} & "
               f"{p(t['lines_saved'], t['lines_orig'])} \\\\")
tex.append(r"""\bottomrule
\end{tabular}
% L = non-blank lines. Goedel/PutnamBench-sample B and L come from reconstructed texts (cleanup rows carry no span; see experiments/metrics/README.md).
""")
md.append('\n| corpus | bytes orig | bytes saved | B% | nonblank lines orig | lines saved | L% |\n|---|---|---|---|---|---|---|')
for k, _ in ROWS:
    t = M[k]['totals']
    md.append(f"| {k} | {t['bytes_orig']:,} | {t['bytes_saved']:,} | {p(t['bytes_saved'], t['bytes_orig'], 3)} | {t['lines_orig']:,} | {t['lines_saved']:,} | {p(t['lines_saved'], t['lines_orig'], 3)} |")

# ------------------------------------------------------------ Hybrid table (whole-file, same sets)
md.append('\n| corpus | lane | A total | A saved | A red % | B total | B saved | B red % |\n|---|---|---|---|---|---|---|---|')
HYB = {}
for k in ('putnam2025', 'putnam_verified', 'minif2f'):
    h = M[k]['hybrid']; A0, B0 = h['orig']['A_total'], h['orig']['B_total']
    for lane in ('base', 'hybrid_greedy', 'hybrid_all', 'hybrid_all_qf', 'hybrid_k16'):
        if lane in h:
            a, b = h[lane]['A_total'], h[lane]['B_total']
            HYB[(k, lane)] = (p(A0 - a, A0), p(B0 - b, B0))
            md.append(f"| {k} | {lane} | {a:,} | {A0 - a:,} | {p(A0 - a, A0, 3)} | {b:,} | {B0 - b:,} | {p(B0 - b, B0, 3)} |")
tex.append(r"""% ---- tab:hybrid, LeanPolish / hybrid (DeepSeek) lanes, counter A [counter B in brackets]; same input sets ----
\begin{tabular}{lrrrrr}
\toprule
Proofs & Files & \LP{} & Hybrid greedy & Hybrid best-of-5 & Hybrid best-of-5, filter \\
\midrule""")
for k, lab in (('putnam2025', 'Putnam 2025, AxiomProver'), ('putnam_verified', 'PutnamBench, Goedel-Prover-V2'),
               ('minif2f', 'miniF2F, Goedel-Prover-V2')):
    t = M[k]['totals']
    cells = [f"{HYB[(k, l)][0]} [{HYB[(k, l)][1]}]" for l in ('base', 'hybrid_greedy', 'hybrid_all', 'hybrid_all_qf')]
    tex.append(f"{lab} & {t['files']} & " + ' & '.join(cells) + r' \\')
tex.append(r"""\bottomrule
\end{tabular}
""")

# ------------------------------------------------------------ Table 2 (tab:sft) token columns
CORP = ['minif2f', 'putnam_verified', 'putnam2025_per_file']
fam = LP['families']
def tacrate(tag, cp):
    n, d, _ = fam[f'{cp}/tactic_replacement/{tag}']; return hu(n, d)
rows = []
r = ['Reference (pipeline)']
for cp in CORP:
    x = REF[f'{cp}/A_port']; r += [f"{x['paper_def_all_pct']:.1f}", f"{x['paper_def_tac_pct']:.1f}", c(x['tok'])]
rows.append(r)
r = ['Delete rule (no model)']
for cp in CORP:
    dc = LP['delete_control'][cp]; r += [hu(dc['delete_has_pass_verdict'], dc['sites']), '0.0', c(dc['savings_passverified'])]
rows.append(r)
for tag, lab in (('frozen', 'DeepSeek-Prover-V2-7B, frozen'), ('frozen_qwen', 'Qwen2.5-Coder-7B, frozen')):
    r = [lab]
    for cp in CORP:
        hd = LP['headline'][cp][tag]; r += [hu(hd['vs1'], LP['headline'][cp]['sites']), tacrate(tag, cp), c(hd['savings1'])]
    rows.append(r)
for m, lab in (('fewshot_deepseek', 'DeepSeek-Prover-V2-7B, 4-shot'), ('fewshot_qwen', 'Qwen2.5-Coder-7B, 4-shot')):
    r = [lab]
    for cp in CORP:
        a = FS[f'{m}/{cp}']; tt = FS[f'{m}/{cp}/family:tactic']
        r += [f"{100 * a['valid_shorter@1']:.1f}", f"{100 * tt['valid_shorter@1']:.1f}", c(a['savings_appL'])]  # 'savings_appL' key = port savings here
    rows.append(r)
for tag, lab in (('sft', 'DeepSeek-Prover-V2-7B, SFT'), ('sft_qwen', 'Qwen2.5-Coder-7B, SFT'), ('dpo', 'DeepSeek-Prover-V2-7B, DPO')):
    r = [lab]
    for cp in CORP:
        hd = LP['headline'][cp][tag]; r += [hu(hd['vs1'], LP['headline'][cp]['sites']), tacrate(tag, cp), c(hd['savings1'])]
    rows.append(r)
json.dump({'tab_sft_rows_port': rows}, open(H / 'tab_sft_port.json', 'w'), indent=1)
tex.append('% ---- tab:sft rows under counter A (rates: see experiments/metrics/README.md; 4-shot rates/savings from fewshot_results_port.md) ----')
for r in rows:
    tex.append(f"{r[0]} & " + ' && '.join(' & '.join(r[1 + 3 * i: 4 + 3 * i]) for i in range(3)) + r' \\')

(H / 'tables.tex').write_text('\n'.join(tex) + '\n')
(H / 'tables.md').write_text('\n'.join(md) + '\n')
print('\n'.join(tex)); print('\n'.join(md))
