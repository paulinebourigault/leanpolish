#!/usr/bin/env python3
"""Screen verdicts -> rows for verify_full.py (fresh `lake env lean` on the spliced file).
Candidates that pass the REPL screen are sent to full verification, plus candidates the
screen could not decide for infrastructure reasons (chunking/boot problems). Screen
failures and screen timeouts are final rejections (a candidate that fails its own
declaration-level replay cannot pass the whole file).
usage: make_verify_rows.py sites.jsonl screen.jsonl out.jsonl [--goals-differ]
"""
import json, sys
from collections import Counter
sites = {json.loads(l)['site_id']: json.loads(l) for l in open(sys.argv[1])}
SEND = {'pass', 'no_chunk', 'chunk_baseline_fail', 'file_boot_fail', 'error'}
if len(sys.argv) > 4 and sys.argv[4] == '--goals-differ':  # 2nd lane: goals differ, may still close later
    SEND = {'fail_goals_differ'}
cnt, seen, n = Counter(), set(), 0
with open(sys.argv[3], 'w') as fo:
    for l in open(sys.argv[2]):
        r = json.loads(l)
        v = r['screen'] if not r['screen'].startswith('error') else 'error'
        cnt[v] += 1
        k = (r['site_id'], r['replacement'])
        if v not in SEND or k in seen:
            continue
        seen.add(k)
        s = sites[r['site_id']]
        fo.write(json.dumps({'site_id': s['site_id'], 'file': s['file'], 'start_byte': s['start_byte'],
                             'end_byte': s['end_byte'], 'original': s['original'],
                             'replacement': r['replacement'], 'screen': v}, ensure_ascii=False) + '\n')
        n += 1
print('screen verdicts', dict(cnt), '-> verify rows', n)
