#!/usr/bin/env python3
"""collect_results.py — 取回 worker-pool run 的最终汇总 (v2: 全程 gh api, 不依赖 git pull)。
v1 的 `git pull --ff-only` 环节在本机 443 抖动时失效(R08 教训), v2 改用
gh api contents 读回 results/pool-<task>.{json,md}; task_id 推断顺序:
  1) --task 显式指定
  2) run 所在 workflow 名 = 排班 task_id (weekly-fob-dedup / weekly-site-matrix / biweekly-mail-check)
  3) 回退: 扫 results/ 最近 commits, 找 run 创建时间之后 fleet-bot 写的 "pool result: <tid> [skip ci]"
用法:
  python collect_results.py <run_id>                    # 等完成 + 读回 + 存盘 + 打印
  python collect_results.py <run_id> --no-wait
  python collect_results.py <run_id> --task weekly-fob-dedup --out D:/path/dir
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time

GH = os.environ.get("GH_BIN", r"C:\Users\17376\.local\ghcli\bin\gh.exe")
REPO = "brianzhangboyang/hermes-fleet-node"
SCHEDULE_TASKS = {"weekly-fob-dedup", "weekly-site-matrix", "biweekly-mail-check"}


def api(path, *extra):
    r = subprocess.run([GH, "api", path] + list(extra),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"gh api {path} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def api_json(path, *extra):
    return json.loads(api(path, *extra))


def wait_run(rid, poll=20):
    print(f"[wait] run {rid} ...", flush=True)
    while True:
        d = json.loads(api(f"repos/{REPO}/actions/runs/{rid}", "--jq",
                     '{status:.status,conclusion:.conclusion,name:.name,created_at:.created_at}'))
        if d["status"] == "completed":
            print(f"[wait] completed: conclusion={d['conclusion']} wf={d['name']!r}")
            return d
        time.sleep(poll)


def resolve_task(run, explicit):
    if explicit:
        return explicit
    if run["name"] in SCHEDULE_TASKS:
        return run["name"]
    # 回退: results/ 提交信息里找 run 创建后的 "pool result: <tid> [skip ci]"
    commits = api_json(f"repos/{REPO}/commits", "-f", "path=results", "-f", "per_page=15")
    for c in commits:
        msg = c["commit"]["message"]
        if msg.startswith("pool result: ") and c["commit"]["committer"]["date"] >= run["created_at"]:
            return msg.split(" ", 2)[2].replace(" [skip ci]", "").strip()
    raise SystemExit("TASK_UNKNOWN: 无法从 run 推断 task_id, 请用 --task 指定")


def fetch_content(path):
    rc = subprocess.run([GH, "api", f"repos/{REPO}/contents/{path}",
                         "--jq", ".content"],
                        capture_output=True, text=True, encoding="utf-8", timeout=120)
    if rc.returncode != 0:
        raise RuntimeError(f"gh api contents {path}: {rc.stderr.strip()[:200]}")
    return base64.b64decode(rc.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--task", default=None)
    ap.add_argument("--out", default=None, help="本地保存目录(默认 ./collected)")
    ap.add_argument("--pull", default="false", help="兼容v1参数, v2忽略(不再git pull)")
    a = ap.parse_args()

    run = wait_run(a.run_id) if not a.no_wait else \
        json.loads(api(f"repos/{REPO}/actions/runs/{a.run_id}", "--jq",
                 '{status:.status,conclusion:.conclusion,name:.name,created_at:.created_at}'))
    tid = resolve_task(run, a.task)
    print(f"[task] {tid}")

    outdir = a.out or os.path.join(os.getcwd(), "collected")
    os.makedirs(outdir, exist_ok=True)
    saved = []
    for suffix in (".json", ".md"):
        p = f"results/pool-{tid}{suffix}"
        try:
            data = fetch_content(p)
        except RuntimeError as e:
            print(f"[warn] {p} 读回失败: {e}")
            continue
        dest = os.path.join(outdir, f"{tid}__run{a.run_id}{suffix}")
        open(dest, "wb").write(data)
        saved.append(dest)
    d = json.loads(open(saved[0], encoding="utf-8").read()) if saved and saved[0].endswith(".json") else None
    if d is None:
        print("NO_RESULT: results/ 下未见本 task 汇总 (aggregate 写回可能未完成)")
        sys.exit(3)

    print("\n===== FINAL SUMMARY =====")
    print(f"run       : {a.run_id}  workflow={run['name']}  run_conclusion={run['conclusion']}")
    print(f"saved     : {saved}")
    print(f"task_id   : {d['task_id']}")
    print(f"verdict   : {d['verdict']}")
    print(f"ok/total  : {d['shards_ok']}/{d['shards_total']}")
    print(f"failed    : {d['shards_failed']}  missing: {d['shards_missing']}")
    for s in d["shards"]:
        err = (" err=" + str(s.get("error"))[:80]) if s.get("error") else ""
        print(f"  - shard {s['shard_id']}: {s['status']} ({s.get('duration_seconds')}s){err}")


if __name__ == "__main__":
    main()
