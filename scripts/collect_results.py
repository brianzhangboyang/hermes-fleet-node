#!/usr/bin/env python3
"""collect_results.py — 取回 worker-pool run 的最终汇总。
用法:
  python collect_results.py <run_id>            # 等完成 + git pull + 打印 merged
  python collect_results.py <run_id> --no-wait
入口逻辑: gh run view 拿 conclusion -> git pull -> 读 results/pool-<task>.json
"""
import argparse
import json
import os
import subprocess
import sys
import time

GH = os.environ.get("GH_BIN", r"C:\Users\17376\.local\ghcli\bin\gh.exe")
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(argv, cwd=REPO_DIR):
    r = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=1800)
    return r


def wait_run(rid):
    print(f"[wait] run {rid} ...", flush=True)
    r = sh([GH, "run", "watch", str(rid)])  # 无 --exit-status: 失败也要拿产物
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--pull", default="true")
    a = ap.parse_args()

    if not a.no_wait:
        wait_run(a.run_id)

    if a.pull != "false":
        sh(["git", "pull", "--ff-only"])

    # 找本 run 对应的 merged summary artifact (或直接读仓库 results/)
    v = sh([GH, "run", "view", str(a.run_id),
            "--json", "conclusion,status,jobs", "--jq",
            '{status,conclusion,jobs:[.jobs[]|{name,conclusion}}]'])
    print("[run view]", v.stdout.strip()[:600])

    res_dir = os.path.join(REPO_DIR, "results")
    files = sorted(os.listdir(res_dir)) if os.path.isdir(res_dir) else []
    print("[results dir]", files[-8:])
    # 取本 run 产出的最新 pool-*.json
    cands = [f for f in files if f.startswith("pool-") and f.endswith(".json")]
    if not cands:
        print("NO_RESULT_YET 仓库尚无 pool-*.json (run 可能未完成或 aggregate 未 push)")
        sys.exit(3)
    latest = os.path.join(res_dir, cands[-1])
    with open(latest, encoding="utf-8") as f:
        d = json.load(f)
    print("\n===== FINAL SUMMARY =====")
    print(f"file      : {latest}")
    print(f"task_id   : {d['task_id']}")
    print(f"verdict   : {d['verdict']}")
    print(f"ok/total  : {d['shards_ok']}/{d['shards_total']}")
    print(f"failed    : {d['shards_failed']}  missing: {d['shards_missing']}")
    for s in d["shards"]:
        st = s["status"]
        err = (" err=" + str(s.get("error"))[:80]) if s.get("error") else ""
        print(f"  - shard {s['shard_id']}: {st} ({s.get('duration_seconds')}s){err}")
    print("\n----- shard outputs (head 300c each) -----")
    for s in d["shards"]:
        if s.get("result"):
            print(f"[shard {s['shard_id']}] {json.dumps(s['result'], ensure_ascii=False)[:300]}")


if __name__ == "__main__":
    main()
