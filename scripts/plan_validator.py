#!/usr/bin/env python3
"""plan_validator.py — worker-pool plan job: 校验 manifest 并展开 matrix。
输出到 GITHUB_OUTPUT: task_id / matrix(JSON单行) / n_shards
校验失败 exit 1 (plan 挂 → 整个 run 不烧 worker)。
"""
import json
import re
import sys

KINDS = {"shell", "http_probe", "python"}
TID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{3,63}$")


def fail(msg: str):
    print(f"VALIDATE_FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except Exception as e:
        fail(f"manifest 读取/JSON解析失败: {e}")

    tid = m.get("task_id")
    if not (isinstance(tid, str) and TID_RE.match(tid)):
        fail("task_id 缺失或不合规(^[a-z0-9][a-z0-9_-]{3,63}$)")
    obj = m.get("objective")
    if not (isinstance(obj, str) and 0 < len(obj) <= 2000):
        fail("objective 缺失或超长(<=2000)")
    shards = m.get("shards")
    if not (isinstance(shards, list) and 1 <= len(shards) <= 16):
        fail("shards 数量必须 1..16 (Free档并发20封顶后的保守值)")

    seen = set()
    out = []
    for s in shards:
        sid = s.get("shard_id")
        if not (isinstance(sid, int) and sid >= 1) or sid in seen:
            fail(f"shard_id 非法或重复: {sid}")
        seen.add(sid)
        kind = s.get("kind")
        if kind not in KINDS:
            fail(f"shard {sid}: kind={kind!r} 不在 {sorted(KINDS)}")
        ins = s.get("instructions")
        if not (isinstance(ins, str) and 0 < len(ins) <= 8000):
            fail(f"shard {sid}: instructions 缺失或超长(<=8000)")
        if len(str(s.get("expected_output", ""))) > 500:
            fail(f"shard {sid}: expected_output 超长(<=500)")
        t = s.get("timeout_seconds", 300)
        if not (isinstance(t, int) and 10 <= t <= 1500):
            fail(f"shard {sid}: timeout_seconds 必须 10..1500")
        out.append({
            "shard_id": sid, "kind": kind,
            "timeout_seconds": t,
            # instructions 不进 matrix(避免经 GITHUB_OUTPUT 双重转义), worker 自己按 sid 从 manifest 取
        })

    out.sort(key=lambda x: x["shard_id"])
    print(f"task_id={tid}")
    print(f"n_shards={len(out)}")
    print("matrix=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print(f"PLAN_OK task={tid} shards={len(out)}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
