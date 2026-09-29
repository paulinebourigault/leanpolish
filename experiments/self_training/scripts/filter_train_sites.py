#!/usr/bin/env python3
"""Post-filter REPL-extracted training sites: drop spans overlapping accepted teacher edits
(byte-span overlap for span edits; any overlap with a teacher warning_cleanup line), and attach
the original Goedel file path. Usage: filter_train_sites.py raw.jsonl teacher_spans.json out.jsonl"""
import json, sys
from collections import Counter
raw, tsp, out = sys.argv[1:4]
T = json.load(open(tsp))
c = Counter(); fo = open(out, 'w')
for l in open(raw):
    s = json.loads(l)
    name = s['file'].split('/')[-1]
    gf = f'goedel_workbook/{name}'
    t = T[gf]
    a, b = s['start_byte'], s['end_byte']
    c['raw'] += 1
    if any(a < te and ts < b for ts, te in t['spans']):
        c['drop_overlap_teacher_span'] += 1; continue
    src = open(sys.argv[4] + '/' + s['file'], 'rb').read() if len(sys.argv) > 4 else None
    if src is not None:
        l0 = src[:a].count(b'\n') + 1; l1 = src[:b].count(b'\n') + 1
        if any(l0 <= w <= l1 for w in t['warning_lines']):
            c['drop_overlap_teacher_warning_line'] += 1; continue
    s['orig_file'] = gf
    fo.write(json.dumps(s, ensure_ascii=False) + '\n'); c['kept'] += 1
print(dict(c))
