#!/usr/bin/env python3
"""Extract candidate tactic sites with the Lean REPL (allTactics) and build SFT-format prompts.

Usage: python extract_sites.py --files-root FILES --corpus putnam2025 --variant base \
          --project $LEAN_PROJECT --repl $REPL_BIN --jobs 16 --out sites_putnam2025_base.jsonl

Site criteria: single tactic invocation (no nested `by`, no bullets/case
alternatives/calc blocks; multi-line allowed only for combinator/bracket continuation),
non-empty goals before, span length <= 600 bytes. Identical spans deduplicated.
Prompt = exactly build_sft_data.PROMPT_TEMPLATE; goal = first goal of the REPL goal list
(Meta.ppGoal format, as LeanPolish's goal_state); context = file bytes
[start-300, end+300] (as LeanPolish.lean line ~3616), tail-truncated to 1200 chars.
"""
import argparse, json, os, re, subprocess, hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROMPT_TEMPLATE = (
    "You are editing a Lean 4 proof. Return only a shorter replacement that\n"
    "preserves the goal. Return <DELETE> if the fragment should be removed.\n"
    "\n"
    "[GOAL]\n{goal}\n"
    "\n"
    "[LOCAL CONTEXT]\n{context}\n"
    "\n"
    "[ORIGINAL FRAGMENT]\n{original}\n"
    "\n"
    "[REPLACEMENT]\n"
)
MAX_GOAL, MAX_CTX = 2000, 1200
BY_RE = re.compile(r'(?<![A-Za-z0-9_.\'])by(?![A-Za-z0-9_\'])')
BAD_RE = re.compile(r'(^|\n)\s*(·|\.|case |next |\| )|=>\s*(\n|$)|(^|\s)calc(\s|$)|\bconv(_lhs|_rhs)?\b')


def build_prompt(goal, ctx, original):
    if not goal:
        goal = '(no local goal)'
    if len(goal) > MAX_GOAL:
        goal = goal[:MAX_GOAL] + ' …'
    if len(ctx) > MAX_CTX:
        ctx = '… ' + ctx[-MAX_CTX:]
    return PROMPT_TEMPLATE.format(goal=goal, context=ctx, original=original)


def run_repl(path_rel, project, repl, timeout=3600):
    cmd = json.dumps({"path": path_rel, "allTactics": True})
    p = subprocess.Popen(['lake', 'env', repl], cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, _ = p.communicate(cmd + '\n\n', timeout=timeout)
    except subprocess.TimeoutExpired:
        try: os.killpg(p.pid, 9)  # also kill the repl child
        except Exception: pass
        raise
    return json.loads(out)


def byte_offsets(text):
    lines = text.split('\n')
    starts, acc = [], 0
    for ln in lines:
        starts.append(acc); acc += len(ln.encode()) + 1
    def conv(pos):
        ln = lines[pos['line'] - 1]
        return starts[pos['line'] - 1] + len(ln[:pos['column']].encode())
    return conv


def first_goal(goals):
    if not goals:
        return ''
    return goals.split('\n\n')[0]


def sites_for(file_path: Path, corpus, variant, args):
    rel = os.path.relpath(file_path, args.project)
    rawdir = Path(args.raw_dir); rawdir.mkdir(parents=True, exist_ok=True)
    rawf = rawdir / f'{corpus}__{variant}__{file_path.stem}.json'
    if rawf.exists():
        res = json.loads(rawf.read_text())
    else:
        res = run_repl(rel, args.project, args.repl)
        rawf.write_text(json.dumps(res))
    text = file_path.read_text()
    src = text.encode()
    conv = byte_offsets(text)
    errs = [m for m in res.get('messages', []) if m.get('severity') == 'error']
    out, seen, stats = [], set(), {'tactics': 0, 'kept': 0, 'nested_by': 0, 'structure': 0,
                                    'no_goal': 0, 'too_long': 0, 'dup': 0}
    for t in res.get('tactics', []):
        stats['tactics'] += 1
        s, e = conv(t['pos']), conv(t['endPos'])
        if (s, e) in seen:
            stats['dup'] += 1; continue
        seen.add((s, e))
        orig = src[s:e].decode('utf-8', errors='replace')
        goal = first_goal(t.get('goals', ''))
        if not t.get('goals'):
            stats['no_goal'] += 1; continue
        if goal.startswith('| ') or '\n| ' in goal:  # conv-mode goal
            stats['structure'] += 1; continue
        if BY_RE.search(orig):
            stats['nested_by'] += 1; continue
        if BAD_RE.search(orig):
            stats['structure'] += 1; continue
        if e - s > 600 or e <= s:
            stats['too_long'] += 1; continue
        cs, ce = max(0, s - 300), min(len(src), e + 300)
        ctx = src[cs:ce].decode('utf-8', errors='ignore')
        site = {
            'corpus': corpus, 'variant': variant, 'file': f'{corpus}/{variant}/{file_path.name}',
            'start_byte': s, 'end_byte': e, 'original': orig, 'goal': goal,
            'n_goals_before': t['goals'].count('\n\n') + 1, 'proofState': t.get('proofState'),
            'repl_tactic': t.get('tactic'),
            'content_sha256': hashlib.sha256(src).hexdigest(),
            'site_id': f'{corpus}/{variant}/{file_path.stem}:{s}:{e}',
            'prompt': build_prompt(goal, ctx, orig),
        }
        out.append(site); stats['kept'] += 1
    return out, stats, len(errs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--files-root', required=True)
    ap.add_argument('--corpus', required=True)
    ap.add_argument('--variant', default='base')
    ap.add_argument('--project', default=os.environ.get('LEAN_PROJECT', os.path.join(os.environ.get('LEANPOLISH_ROOT', os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))), 'leanpolish')))
    ap.add_argument('--repl', default=os.environ.get('REPL_BIN', 'repl/.lake/build/bin/repl'))
    ap.add_argument('--raw-dir', default='repl_raw')
    ap.add_argument('--jobs', type=int, default=16)
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    files = sorted(Path(args.files_root, args.corpus, args.variant).glob('*.lean'))
    if args.only:
        files = [f for f in files if f.stem in set(args.only)]
    allsites, summary = [], {}
    def job(f):
        try:
            return f, sites_for(f, args.corpus, args.variant, args)
        except Exception as ex:
            return f, ([], {'error': repr(ex)[:300]}, -1)
    with ThreadPoolExecutor(args.jobs) as ex:
        for f, (sites, stats, nerr) in ex.map(job, files):
            stats['file_errors'] = nerr
            summary[f.stem] = stats
            allsites.extend(sites)
            print(f.stem, stats, flush=True)
    with open(args.out, 'w') as fo:
        for s in allsites:
            fo.write(json.dumps(s, ensure_ascii=False) + '\n')
    json.dump(summary, open(args.out + '.summary.json', 'w'), indent=1)
    print('TOTAL sites', len(allsites))

if __name__ == '__main__':
    main()
