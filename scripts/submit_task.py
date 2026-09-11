#!/usr/bin/env python3
"""submit_task.py — github_worker_pool 唯一提交入口 (本机运行)。
用法:
  python submit_task.py tasks/manifests/demo.json            # 校验+push+触发
  python submit_task.py task.json --dry-run                  # 只校验
  python submit_task.py --status <run_id>                    # 查询状态
流程: 本地schema校验(不过则拒绝提交,零runner消耗) -> git push manifest
      -> gh workflow run worker-pool.yml -> 打印 run_id
结果取回: 见 collect_results.py
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GH = os.environ.get("GH_BIN", r"C:\Users\17376\.local\ghcli\bin\gh.exe")
REPO_DIR = os.path.dirname(HERE)  # infra/hermes-fleet-node
SCHEMA_PATH = os.path.join(HERE, "..", "tasks", "task-schema.json")
SHELL_WHITELIST = {
    "echo", "date", "hostname", "uname", "nproc", "free", "df", "top",
    "cat", "ls", "wc", "head", "tail", "grep", "awk", "sed", "sort", "uniq",
    "curl", "wget", "python3", "pip", "node", "npm", "git", "sleep", "env",
    "whoami", "id", "uptime", "vmstat", "iostat", "ping", "dig", "nslookup",
}
TID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{3,63}$")


def validate(path):
    """本地预检(镜像 plan_validator 规则 + shell 白名单深度检查)。返回 (ok, msg)。"""
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:
        return False, f"JSON 解析失败: {e}"
    tid = m.get("task_id")
    if not (isinstance(tid, str) and TID_RE.match(tid)):
        return False, "task_id 不合规"
    if not (isinstance(m.get("objective"), str) and 0 < len(m["objective"]) <= 2000):
        return False, "objective 缺失/超长"
    shards = m.get("shards")
    if not (isinstance(shards, list) and 1 <= len(shards) <= 16):
        return False, "shards 数量须 1..16"
    seen = set()
    for s in shards:
        sid = s.get("shard_id")
        if not isinstance(sid, int) or sid in seen:
            return False, f"shard_id 非法/重复: {sid}"
        seen.add(sid)
        if s.get("kind") not in ("shell", "http_probe", "python"):
            return False, f"shard {sid}: kind 非法"
        ins = s.get("instructions")
        if not (isinstance(ins, str) and 0 < len(ins) <= 8000):
            return False, f"shard {sid}: instructions 缺失/超长"
        if s.get("kind") == "shell":
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from worker_engine import shell_line_ok
            for cmd in filter(None, (l.strip() for l in ins.splitlines())):
                allowed, bad = shell_line_ok(cmd)
                if not allowed:
                    return False, f"shard {sid}: '{bad}' 不在白名单 (cmd: {cmd[:60]})"
        t = s.get("timeout_seconds", 300)
        if not (isinstance(t, int) and 10 <= t <= 1500):
            return False, f"shard {sid}: timeout_seconds 须 10..1500"
    return True, f"OK task={tid} shards={len(shards)}"


def sh(argv, cwd=REPO_DIR):
    r = subprocess.run(argv, capture_output=True, text=True, cwd=cwd, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"{argv[0]} 失败: {(r.stderr or r.stdout)[:400]}")
    return (r.stdout or "").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-parallel", default="4")
    ap.add_argument("--fail-fast", default="false")
    ap.add_argument("--status", help="查询 run 状态并退出")
    a = ap.parse_args()

    if a.status:
        out = sh([GH, "run", "list", "--workflow=worker-pool.yml",
                  "--limit", "5", "--json", "databaseId,status,conclusion,displayTitle"])
        print(out)
        return

    if not a.manifest:
        ap.error("需要 manifest 路径或 --status")
    ok, msg = validate(a.manifest)
    print(f"[validate] {msg}")
    if not ok:
        sys.exit(2)
    if a.dry_run:
        return

    # push manifest 到 tasks/manifests/
    dest = os.path.join(REPO_DIR, "tasks", "manifests", os.path.basename(a.manifest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.abspath(a.manifest) != os.path.abspath(dest):
        import shutil
        shutil.copyfile(a.manifest, dest)
    rel = "tasks/manifests/" + os.path.basename(a.manifest)
    sh(["git", "add", rel])
    if sh(["git", "status", "--porcelain", rel]):
        sh(["git", "commit", "-m", f"pool task submit: {rel} [skip ci]"])
        sh(["git", "push"])
    else:
        print("[git] manifest 无变化, 跳过 commit")

    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%H%M%S")
    out = sh([GH, "workflow", "run", "worker-pool.yml",
              "-f", f"manifest_path={rel}",
              "-f", f"max_parallel={a.max_parallel}",
              "-f", f"fail_fast={a.fail_fast}"])
    print(f"[trigger] {out or 'ok'}")
    import time
    time.sleep(6)
    rid = sh([GH, "run", "list", "--workflow=worker-pool.yml",
              "--limit", "1", "--json", "databaseId", "--jq", ".[0].databaseId"])
    print(f"RUN_ID={rid}")
    print(f"取结果: python scripts/collect_results.py {rid}")


if __name__ == "__main__":
    main()
