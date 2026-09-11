# OP-005 最终报告 · github_worker_pool

日期：2026-09-11 · 执行人：Hermes（实验负责人制）
结论：**OP-005 SUCCESS** — 9 条成功标准全部满足（逐条见下）。

## 能力定义

`github_worker_pool` = Hermes 的按需弹性临时并行 Worker Pool，免费 GitHub
Actions ubuntu runner（4核/15G/87G per worker），单命令提交、N 路并行、
结构化回收、聚合裁决、单写回。

调用链：
```
manifest.json → submit_task.py(本地校验/push/触发) → worker-pool.yml
  plan(远端二次校验+展开matrix) → N×worker(独立VM, kind=shell/http_probe/python)
  → Artifact 回收 → aggregator(SUCCESS/PARTIAL_SUCCESS/FAILED/UNKNOWN)
  → 单写回 results/pool-<task_id>.json(+rebase-retry) → collect_results.py 取回
```

## 实验矩阵（全部真实 run，证据在 git 历史 + results/）

| ID | 目的 | run | 结论 |
|---|---|---|---|
| E1 | 3片基线 | 34616151977→34617083040 | 首轮暴露 artifact 路径 bug（result.json 写死→全 missing）；修复后 SUCCESS 3/3 |
| E2 | 8路并发+独立性 | 34617937318 | 8/8；8 job 同秒起跑，runner id 1000000023-30 全不同 = 独立 VM 实锤；单片失败隔离由 fail-fast:false 保障 |
| E3 | 失败注入 | 34618263750 | PARTIAL_SUCCESS 2/4：主动 exit(3)→failed、sleep999→timeout@15s 精确切断、其余 2 片正常回收 |
| E4 | 16路规模 | 34618578471→34619525525 | 首跑 worker 16/16 全成功但 aggregate 写回被 modeA 并发 push 撞掉→写回加 rebase-retry×5；重跑 SUCCESS 16/16，启动窗口 13s 零排队 |
| E5 | 模式A对照 | 34618599330 | 4 pusher 直推：3 个 non-fast-forward/cannot-lock-ref，最终仅 2/4 文件落地 → **模式A否决（丢数据）**，模式B(Artifact+Aggregator单写回)定正 |
| E6 | 真实业务任务 | 34619513171 | B2B 目录侦察 5 片 9 站点：europages 200(alibaba 200/thomasnet 403/kompass 403/tradeindia 200/exportersindia 可达/made-in-china 200/goldsupplier 200/tradekey 200；alibaba 搜索页返 90731 bytes HTML 静态直出，organic 条目计数待复核）——EVOLUTION-BENCH-001 选型数据到手

**TESTED_STABLE_PARALLELISM = 16**

## 成功标准核对

1. 多 Worker 执行不同 shard — VERIFIED（E2/E4/E6）
2. 实测稳定并行规模 — VERIFIED（E4: 16/16 零排队）
3. 任务不写死 — VERIFIED（manifest_path 输入，E1-E6 六个任务零改码）
4. 结构化结果 — VERIFIED（result_<sid>.json 含 task_id/shard_id/status/result/error/起止/runner）
5. 无写回竞争 — VERIFIED（模式B单写回 + E5 对照证据）
6. PARTIAL_SUCCESS — VERIFIED（E3 实拍 1失败+1超时）
7. 真实端到端 — VERIFIED（E6 B2B 侦察，非 echo）
8. 能力固化 — VERIFIED（submit/collect 两脚本 + task-schema + skill 更新，无需重写 workflow）
9. 分级标注 — 本文档 VERIFIED=有 run 号；DOCUMENTED=官方文档；INFERRED=推断；UNKNOWN 未混用

## 官方边界（DOCUMENTED，docs.github.com/actions/reference/limits，2026-09-11 实抓）

- matrix ≤256 jobs/run；标准 runner 并发：Free=20 / Pro=40 / Team=60
- job ≤6h，run ≤35 天；公共仓库标准 runner 免费（不占 2000 分钟池）
- artifact 存储 Free 500MB/月（本池单片结果 ≤4KB 截断，无压力）
- 触发事件 1500/10s；重跑 ≤50 次

## 明确不做的（BLOCKED-BY-POLICY，按任务书记录不绕过）

- runner 常驻化（6h 硬顶 + ToS 禁 standalone service）→ 常驻走 VPS self-hosted runner（另案）
- cloudflared 公网暴露 = GitHub ToS 红线，否决
- worker 内跑付费模型 = 密钥进 public repo 风险，本池只跑无密钥任务；需要模型的子任务走 VPS 节点或 secrets 治理后再开

## 工程教训（已固化进代码）

- artifact path 写死 result.json + if-no-files-found:warn = 静默全丢（E1 首败根因）→ glob + error
- aggregate push 与任何并发 writer（包括实验 workflow）撞 ref → rebase-retry×5 必须内置
- shell 白名单必须词法级（引号感知 + 拒 heredoc/命令替换 + for 循环变量不误杀）：15 组本地用例回归
- 本机 git 443 不稳时，gh contents API 是可靠备用写通道
