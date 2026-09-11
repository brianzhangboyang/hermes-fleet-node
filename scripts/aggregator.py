#!/usr/bin/env python3
"""aggregator.py — 收齐各 shard result_<sid>.json, 裁决 verdict, 产出 merged/。
用法: aggregator.py <task_id> <n_shards> <expect_matrix_json> <results_in_dir> <out_dir>
verdict: SUCCESS 全成功 / PARTIAL_SUCCESS 有成有败 / FAILED 无一成功 / UNKNOWN 结果缺失
"""
import glob
import json
import os
import sys
from datetime import datetime, timezone


def main():
    tid, n = sys.argv[1], int(sys.argv[2])
    expect = json.loads(sys.argv[3])
    src, outdir = sys.argv[4], sys.argv[5]
    os.makedirs(outdir, exist_ok=True)

    want = [s["shard_id"] for s in expect]
    shards, missing = [], []
    for sid in want:
        p = os.path.join(src, f"result_{sid}.json")
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    shards.append(json.load(f))
            except Exception as e:
                shards.append({"task_id": tid, "shard_id": sid, "status": "failed",
                               "result": None, "error": f"corrupt artifact: {e}"[:300],
                               "started_at": None, "finished_at": None, "duration_seconds": None})
        else:
            missing.append(sid)
            shards.append({"task_id": tid, "shard_id": sid, "status": "missing",
                           "result": None, "error": "no result.json (worker killed/cancelled?)",
                           "started_at": None, "finished_at": None, "duration_seconds": None})

    ok = [s for s in shards if s["status"] == "success"]
    if not shards or (len(missing) == len(shards)):
        verdict = "UNKNOWN"
    elif len(ok) == len(shards):
        verdict = "SUCCESS"
    elif ok:
        verdict = "PARTIAL_SUCCESS"
    else:
        verdict = "FAILED"

    summary = {
        "task_id": tid, "verdict": verdict,
        "shards_total": len(shards), "shards_ok": len(ok),
        "shards_failed": len([s for s in shards if s["status"] in ("failed", "timeout")]),
        "shards_missing": missing,
        "aggregated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shards": shards,
    }
    with open(os.path.join(outdir, f"pool-{tid}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    lines = [f"# pool report: {tid}", "",
             f"- verdict: **{verdict}** ({len(ok)}/{len(shards)} ok)",
             f"- aggregated: {summary['aggregated_at']}", ""]
    for s in shards:
        mark = {"success": "OK", "failed": "FAIL", "timeout": "TIMEOUT",
                "missing": "MISSING"}.get(s["status"], s["status"])
        err = f" err={s['error'][:120]}" if s.get("error") else ""
        lines.append(f"- shard {s['shard_id']}: {mark}{err}")
    with open(os.path.join(outdir, f"pool-{tid}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"AGGREGATE {tid}: {verdict} ({len(ok)}/{len(shards)})", file=sys.stderr)


if __name__ == "__main__":
    main()
