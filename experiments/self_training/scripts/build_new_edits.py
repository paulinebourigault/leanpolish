#!/usr/bin/env python3
"""Verified round-1 candidates on training sites -> new_edits.jsonl (release schema) + round-2 SFT data.
Implements the pre-registered rules (see README):
  new edit   = != original, strictly shorter (count_appL), exact verdict 'pass'
  trivial    = pure deletion (empty replacement)
  compliant  = quality_filter.is_quality_upgrade(original, replacement)
  dedup      = one row per site: max count_appL saving; ties greedy-first then lexicographic
  leakage    = drop rows whose goal hash is in data/heldout_goal_hashes.json
  NAIVE      = all new edits + REPLAY ; SEL = best non-deletion & compliant per site + same REPLAY
  REPLAY     = random.Random(42).sample(sft_train, len(NAIVE new edits))
Usage: build_new_edits.py --sites train_sites.jsonl --gens gens_r1_train.jsonl --verify verify_train.jsonl
         --screen screen_train.jsonl --sft-train sft_train.jsonl --hashes heldout_goal_hashes.json --outdir DIR"""
import argparse, hashlib, json, random, re, os, sys
from collections import Counter, defaultdict
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.environ.get('LEANPOLISH_ROOT', os.path.abspath(os.path.join(_HERE, '..', '..', '..')))
for _p in (_HERE, os.path.join(_ROOT, 'experiments', 'hybrid', 'scripts'), os.path.join(_ROOT, 'leanpolish')):
    sys.path.insert(0, _p)
from retokenize_appendixL import count_appL
from quality_filter import is_quality_upgrade, axis
WS = re.compile(r'\s+')
gh = lambda s: hashlib.sha256(WS.sub(' ', s).strip().encode()).hexdigest()
ap = argparse.ArgumentParser()
for k in ('sites', 'gens', 'verify', 'screen', 'sft_train', 'hashes', 'outdir', 'files_root'):
    ap.add_argument('--' + k.replace('_', '-'), required=k != 'files_root')
a = ap.parse_args()
sites = {json.loads(l)['site_id']: json.loads(l) for l in open(a.sites)}
gens = {json.loads(l)['site_id']: json.loads(l) for l in open(a.gens)}
H = set(json.load(open(a.hashes)))
ver = {}
for l in open(a.verify):
    v = json.loads(l); ver[(v['site_id'], v['replacement'])] = v['verdict']
scr = Counter(json.loads(l)['screen'] for l in open(a.screen))
st = Counter(); st['sites'] = len(sites); st['sites_with_gen'] = len(gens)
per_site = defaultdict(list); allv = []
for sid, g in gens.items():
    s = sites[sid]; o = s['original']
    decs = [('greedy', g['greedy'])] + [(f'sample{i}', c) for i, c in enumerate(g.get('samples', []))]
    uniq = {}
    for d, c in decs:
        st['cands_total'] += 1
        if c == o or c.strip() == o.strip(): st['cands_same_as_original'] += 1; continue
        if count_appL(c) >= count_appL(o): st['cands_not_shorter'] += 1; continue
        st['cands_shorter'] += 1
        uniq.setdefault(c, d)
    for c, d in uniq.items():
        st['unique_shorter'] += 1
        v = ver.get((sid, c), 'screen_reject')
        st['verdict_' + v] += 1
        if v != 'pass': continue
        rec = {'site_id': sid, 'replacement': c, 'decoding': d, 'saving_appL': count_appL(o) - count_appL(c),
               'deletion': c.strip() == '', 'compliant': is_quality_upgrade(o, c)}
        per_site[sid].append(rec); allv.append(rec)
st['verified_unique_candidates'] = len(allv)
st['sites_with_verified'] = len(per_site)
os.makedirs(a.outdir, exist_ok=True)
json.dump(allv, open(f'{a.outdir}/all_verified_candidates.json', 'w'), ensure_ascii=False)
def mkrow(s, b, rs):
    src = open(f"{a.files_root}/{s['file']}", 'rb').read() if a.files_root else None
    return {
        'attempt_id': f"{s['orig_file']}:{s['start_byte']}:{s['end_byte']}", 'corpus': 'goedel',
        'file': s['orig_file'], 'start_byte': s['start_byte'], 'end_byte': s['end_byte'],
        'line': (src[:s['start_byte']].count(b'\n') + 1) if src else None,
        'original': s['original'], 'replacement': b['replacement'],
        'type': 'dead_code_removal' if b['deletion'] else 'tactic_replacement',
        'kind': 'neural_deletion' if b['deletion'] else 'neural_tactic_replacement',
        'outcome': 'accepted', 'goal_state': s['goal'], 'goal_pretty': s['goal'].split('⊢')[-1].strip(),
        'context': s['prompt'].split('[LOCAL CONTEXT]\n', 1)[1].split('\n\n[ORIGINAL FRAGMENT]')[0],
        'content_sha256': s['content_sha256'],
        'edit_width': len(s['original']) - len(b['replacement']),
        'tokens_appL_original_fragment': count_appL(s['original']), 'saving_appL': b['saving_appL'],
        'axis_orig': axis(s['original']), 'axis_repl': axis(b['replacement']) if b['replacement'] else None,
        'provenance': 'neural_round1', 'decoding': b['decoding'], 'n_verified_candidates_at_site': len(rs),
        'trivial_deletion': b['deletion'], 'specificity_filter_compliant': b['compliant'],
        'verification': 'repl_screen+fresh_lake_env_lean_lean4.21_mathlib_v4.21.0',
        'schema_version': 2, '_prompt': s['prompt']}
# NAIVE: per site the verified candidate with max saving (ties greedy-first, lexicographic).
# SEL (clarified before any result was seen): per site the max-saving candidate AMONG non-deletion,
# filter-compliant verified candidates (so a site where a deletion also verified still contributes its
# compliant tactic edit).
rows, sel_rows = [], []
key = lambda r: (-r['saving_appL'], r['decoding'] != 'greedy', r['replacement'])
for sid, rs in per_site.items():
    s = sites[sid]
    if gh(s['goal']) in H: st['drop_goal_overlap_heldout'] += 1; continue
    rs.sort(key=key)
    rows.append(mkrow(s, rs[0], rs))
    ok = [r for r in rs if not r['deletion'] and r['compliant']]
    if ok: sel_rows.append(mkrow(s, ok[0], rs))
st['sites_with_verified_nondel_compliant'] = len(sel_rows)
st['sites_where_naive_pick_is_deletion_but_sel_has_edit'] = sum(1 for r in rows if r['trivial_deletion'] and any(x['attempt_id'] == r['attempt_id'] for x in sel_rows))
st['new_edits'] = len(rows)
st['new_edits_deletion'] = sum(r['trivial_deletion'] for r in rows)
st['new_edits_nondeletion'] = len(rows) - st['new_edits_deletion']
st['new_edits_compliant'] = sum(r['specificity_filter_compliant'] for r in rows)
st['new_edits_nondeletion_compliant'] = sum((not r['trivial_deletion']) and r['specificity_filter_compliant'] for r in rows)
st['saving_appL_total'] = sum(r['saving_appL'] for r in rows)
st['saving_appL_deletion'] = sum(r['saving_appL'] for r in rows if r['trivial_deletion'])
st['saving_appL_nondel_compliant'] = sum(r['saving_appL'] for r in rows if not r['trivial_deletion'] and r['specificity_filter_compliant'])
st['files_with_new_edits'] = len({r['file'] for r in rows})
st['screen_verdicts'] = dict(scr)
rel = {}
for r in rows: rel[(r['attempt_id'], r['replacement'])] = dict(r, used_in_naive=True, used_in_sel=False)
for r in sel_rows:
    k = (r['attempt_id'], r['replacement'])
    if k in rel: rel[k]['used_in_sel'] = True
    else: rel[k] = dict(r, used_in_naive=False, used_in_sel=True)
with open(f'{a.outdir}/new_edits.jsonl', 'w') as f:
    for r in rel.values(): f.write(json.dumps({k: v for k, v in r.items() if k != '_prompt'}, ensure_ascii=False) + '\n')
st['new_edits_release_rows'] = len(rel)
sft = lambda r: {'prompt': r['_prompt'], 'target': r['replacement'] if r['replacement'] else '<DELETE>',
                 'file': r['file'], 'attempt_id': r['attempt_id'], 'shard': 'goedel_neural_round1', 'type': r['type']}
base = [json.loads(l) for l in open(a.sft_train)]
replay = random.Random(42).sample(base, min(len(rows), len(base)))
naive = [sft(r) for r in rows]; sel = [sft(r) for r in sel_rows]
for name, new in (('naive', naive), ('sel', sel)):
    data = new + replay
    random.Random(42).shuffle(data)
    with open(f'{a.outdir}/r2_{name}_train.jsonl', 'w') as f:
        for d in data: f.write(json.dumps(d, ensure_ascii=False) + '\n')
    st[f'r2_{name}_rows'] = len(data); st[f'r2_{name}_new'] = len(new)
st['replay_rows'] = len(replay)
json.dump(st, open(f'{a.outdir}/new_edits_stats.json', 'w'), indent=1)
print(json.dumps(st, indent=1))
