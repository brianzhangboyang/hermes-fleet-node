#!/usr/bin/env python3
"""worker_engine.py — worker matrix 单片执行引擎。
用法: worker_engine.py <manifest_path> <shard_id> <timeout_s>
按 kind 执行, 输出 result_<sid>.json (结构化, 含 task_id/shard_id/status/result/error/时间戳)。
安全: shell=白名单命令; 本引擎无 secrets; python kind=策略限制(离线计算用途),
      技术上非沙箱——不投喂含敏感数据/网络依赖的任务, 由提交方(本地validator)把关。
"""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

SHELL_WHITELIST = {
    "echo", "date", "hostname", "uname", "nproc", "free", "df", "top",
    "cat", "ls", "wc", "head", "tail", "grep", "awk", "sed", "sort", "uniq",
    "curl", "wget", "python3", "pip", "node", "npm", "git", "sleep", "env",
    "whoami", "id", "uptime", "vmstat", "iostat", "ping", "dig", "nslookup",
    "tr", "tee", "mkdir", "cp", "touch", "du", "stat", "file", "cut", "base64",
}
SHELL_CONTROL = {"for", "while", "until", "if", "then", "else", "elif", "fi",
                "do", "done", "in", "case", "esac", "export", "local", "{"}


def _lex(line: str):
    """shlex词法: 产出 (token, was_quoted) 序列。词法天然引号感知。"""
    import shlex
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        toks = list(lex)
    except ValueError:
        return None
    # was_quoted: 重建不可靠, 用原始行近似——带引号的token在shlex后丢失标记,
    # 简化处理: 含空格/特殊字符的token必来自引号
    out = []
    for t in toks:
        quoted = (" " in t or ";" in t or "&" in t or "|" in t or "$" in t
                  or "{" in t or "}" in t or "(" in t or ")" in t)
        out.append((t, quoted))
    return out


SHELL_BUILTIN_OK = {"true", "false", "test", "[", "printf", "cd", "set", "shift", ":"}
SPLIT_OPS = {";", "&&", "||", "|", "&"}


def shell_line_ok(line: str):
    """词法级白名单: 每个分号/管道/&&段的首token(跳赋值与控制词)必须在白名单。
    heredoc 拒绝; $()/反引号命令替换拒绝(词法会带$(开头,视为违规头)。"""
    if "<<" in line:
        return False, "heredoc-unsupported(用单行命令)"
    toks = _lex(line)
    if toks is None:
        return False, "unbalanced-quotes"
    seg_first = True
    loop_head = False
    for t, quoted in toks:
        if loop_head:
            if t == "do":
                loop_head = False
            continue
        if t in SPLIT_OPS:
            seg_first = True if t != "&" else seg_first
            continue
        if t == "for":
            loop_head = True
            seg_first = False
            continue
        if not seg_first:
            continue
        if t in SHELL_CONTROL or t in SHELL_BUILTIN_OK:
            continue
        if _looks_assignment(t):
            continue
        if t.startswith("$(") or t.startswith("`"):
            return False, "command-substitution-unsupported"
        if quoted:
            seg_first = False  # 引号token=数据, 不该是命令头
            continue
        if t not in SHELL_WHITELIST:
            return False, t
        seg_first = False
    return True, None


def _looks_assignment(tok: str):
    import re
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok))


MAX_OUT = 4000  # 单片结果截断, 保护 artifact 存储


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def trunc(s: str) -> str:
    s = s or ""
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n...[truncated {len(s)} chars]"


def run_cmd(argv, timeout):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def exec_shell(ins, tmo):
    lines = []
    any_ok, any_fail = False, False
    for cmd in filter(None, (l.strip() for l in ins.splitlines())):
        allowed, bad = shell_line_ok(cmd)
        if not allowed:
            lines.append(f"$ {cmd}\n  REJECTED: '{bad}' 不在白名单")
            any_fail = True
            continue
        try:
            r = subprocess.run(["bash", "-c", cmd], capture_output=True,
                               text=True, timeout=tmo)
            lines.append(f"$ {cmd}\n[exit={r.returncode}]\n{trunc(r.stdout)}\n{trunc(r.stderr)}")
            any_ok, any_fail = (any_ok or r.returncode == 0), (any_fail or r.returncode != 0)
        except subprocess.TimeoutExpired:
            lines.append(f"$ {cmd}\n  TIMEOUT after {tmo}s")
            any_fail = True
            break
        tmo = max(10, int(tmo * 0.6))
    return {"output": trunc("\n".join(lines)), "_partial_fail": any_fail and not any_ok}


def exec_http_probe(ins, tmo):
    results = []
    for url in filter(None, (l.strip() for l in ins.splitlines())):
        if not url.startswith(("http://", "https://")):
            results.append({"url": url, "error": "not-http"})
            continue
        try:
            r = run_cmd(["curl", "-s", "-o", "/dev/null", "-m", "10",
                         "-A", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36",
                         "-w", "%{http_code} %{time_total}s", url], 15)
            results.append({"url": url, "probe": r.stdout.strip()})
        except subprocess.TimeoutExpired:
            results.append({"url": url, "error": "timeout"})
        except Exception as e:
            results.append({"url": url, "error": str(e)[:200]})
    all_bad = bool(results) and all("probe" not in x for x in results)
    return {"probes": results, "_partial_fail": all_bad}


def exec_python(ins, tmo):
    r = run_cmd(["python3", "-I", "-c", ins], tmo)
    return {"exit": r.returncode, "output": trunc(r.stdout), "stderr": trunc(r.stderr),
            "_partial_fail": r.returncode != 0}


KIND_FN = {"shell": exec_shell, "http_probe": exec_http_probe, "python": exec_python}


def main():
    path, sid = sys.argv[1], int(sys.argv[2])
    tmo = int(float(sys.argv[3])) if len(sys.argv) > 3 else 300
    started = now_iso()
    t0 = time.monotonic()
    status, payload, error = "success", None, None
    tid = f"shard-{sid}"
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        tid = m["task_id"]
        shard = next(s for s in m["shards"] if s["shard_id"] == sid)
        fn = KIND_FN.get(shard["kind"])
        if fn is None:
            raise ValueError(f"未知 kind {shard['kind']}")
        payload = fn(shard["instructions"], shard.get("timeout_seconds", tmo))
        if isinstance(payload, dict) and payload.get("_partial_fail"):
            status, error = "failed", f"{shard['kind']} 内部全部子项失败(见result明细)"
    except subprocess.TimeoutExpired:
        status, error = "timeout", f"shard exceeded {tmo}s"
    except Exception as e:
        status, error = "failed", str(e)[:500]
    out = {
        "task_id": tid, "shard_id": sid, "status": status,
        "result": payload, "error": error,
        "started_at": started, "finished_at": now_iso(),
        "duration_seconds": round(time.monotonic() - t0, 1),
        "runner": subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip(),
    }
    with open(f"result_{sid}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"WORKER_DONE shard={sid} status={status}", file=sys.stderr)
    # 永远 exit 0: 状态在 result 文件里, 让 aggregate 统一裁决(失败不中断矩阵)


if __name__ == "__main__":
    main()
