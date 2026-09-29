#!/usr/bin/env python3
"""Parse raw complete-menu LeanPolish logs ([MENU_POOL] lines) into a site-level
pool file (jsonl.gz), one record per site, and print pool statistics.

  python3 extract_pools.py --logdir $DATA_DIR/logs/goedel --corpus goedel_train \
      --out $DATA_DIR/pools/goedel_train.jsonl.gz

Input: raw Lean stdout logs written by run_pools.py. Output: gzipped site-level pool file.
"""
import argparse
import glob
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poolcommon import parse_logs  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logdir", required=True, nargs="+")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    logs = sorted(p for d in args.logdir for p in glob.glob(f"{d}/**/*.log", recursive=True))
    sites = parse_logs(logs, args.corpus)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt") as f:
        for s in sites:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    files = {s["file"] for s in sites}
    print(json.dumps({"logs": len(logs), "sites": len(sites), "files_with_sites": len(files),
                      "sites_with_goal": sum(1 for s in sites if s.get("goal_state"))}))


if __name__ == "__main__":
    main()
