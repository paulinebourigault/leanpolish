#!/usr/bin/env python3
"""Split a sites jsonl into K shards by source file (stable md5 of file path). shard.py IN K OUTPREFIX"""
import sys, json, hashlib
inp, K, pre = sys.argv[1], int(sys.argv[2]), sys.argv[3]
fo = [open(f'{pre}.{i}.jsonl', 'w') for i in range(K)]
for l in open(inp):
    f = json.loads(l)['file']
    fo[int(hashlib.md5(f.encode()).hexdigest(), 16) % K].write(l)
