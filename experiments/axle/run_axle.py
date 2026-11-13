#!/usr/bin/env python3
"""Run AXLE's `simplify_theorems` (public service, environment lean-4.21.0, default simplifications)
on a folder of Lean files and save the full response per file.

The Goedel-Prover-V2 files switch Lean's linters off in their header (`set_option linter.* false`).
AXLE relies on the linters and then makes no edit, so these lines are removed from the text sent to
AXLE; `rebuild_verify.py` restores the original header before anything is counted.

Usage: run_axle.py <variant> <corpus>:<input dir> [<corpus>:<input dir> ...]
  writes <REPLICATION_DATA>/axle/raw/<variant>/<corpus>/<name>.json
  variant = `original` (inputs/) or `lp_fixed_point` (lp_fixed_point/)
Requires the `axle` client package and network access.
"""
import asyncio, json, os, re, sys, time
from pathlib import Path
from axle import AxleClient

OUT = Path(os.environ['REPLICATION_DATA']) / 'axle' / 'raw'


async def one(client, sem, variant, corpus, f):
    o = OUT / variant / corpus / (f.stem + '.json')
    if o.exists():
        return
    o.parent.mkdir(parents=True, exist_ok=True)
    src = re.sub(r'^set_option linter\.[^\n]*\n', '', f.read_text(), flags=re.M)
    async with sem:
        t = time.time()
        try:
            r = await client.simplify_theorems(content=src, environment='lean-4.21.0', ignore_imports=True, timeout_seconds=3000)
            d = r.model_dump(mode='json') if hasattr(r, 'model_dump') else dict(r.__dict__)
            d['ok'] = True
        except Exception as e:
            d = {'ok': False, 'error': repr(e)[:2000]}
        d['client_wall_s'] = time.time() - t
        d['input'] = f'{corpus}/{f.name}'
    o.write_text(json.dumps(d, default=str))
    print(corpus, f.name, d.get('ok'), round(d['client_wall_s'], 1), d.get('simplification_stats'), flush=True)


async def main():
    variant, jobs = sys.argv[1], []
    for spec in sys.argv[2:]:
        corpus, d = spec.split(':', 1)
        jobs += [(corpus, f) for f in sorted(Path(d).rglob('*.lean'))]
    sem = asyncio.Semaphore(8)
    async with AxleClient() as client:
        await asyncio.gather(*[one(client, sem, variant, corpus, f) for corpus, f in jobs])


asyncio.run(main())
