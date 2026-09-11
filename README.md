# hermes-fleet-node

Hermes 舰队节点仓库 + **github_worker_pool**（OP-005）：把 GitHub Actions 免费
ubuntu runner 建设成 Hermes 可按需调用的弹性临时并行 Worker Pool。

## github_worker_pool 能力（已验证）

一句话：把可拆分的独立子任务打包成 manifest，一条命令扔给 N 个免费 GitHub
runner 并行跑，结果结构化回收 + 聚合判定 + 单写回仓库。

### 用法（Hermes 日常入口）

```bash
# 1) 写任务清单(参考 tasks/manifests/ 下任意示例, schema=tasks/task-schema.json)
# 2) 提交(本地校验→push manifest→触发 workflow, 打印 RUN_ID):
"C:/Users/17376/.local/ghcli/bin/gh.exe" --version >/dev/null  # gh依赖
python D:/Boyang_AI_OS/infra/hermes-fleet-node/scripts/submit_task.py \
       <manifest.json> --max-parallel 8
# 3) 收结果(等完成→读 results/pool-<task_id>.json→打印verdict+逐片明细):
python D:/Boyang_AI_OS/infra/hermes-fleet-node/scripts/collect_results.py <RUN_ID>
```

- shard `kind`：`shell`（词法级白名单守卫，拒 heredoc/命令替换）
  / `http_probe`（URL 批量 HEAD 探测）/ `python`（离线计算；无 secrets）
- verdict：`SUCCESS / PARTIAL_SUCCESS / FAILED / UNKNOWN`，逐片 status 可查
- 上限：shards ≤16（实测稳定；官方 Free 档并发 20）
- 红线：不做常驻服务/tunnel 公网暴露/绕限制（GitHub ToS + 平台规则）

### 文件

```
.github/workflows/worker-pool.yml      正式架构(plan→matrix workers→aggregate)
.github/workflows/worker-pool-modeA.yml E5对照实验(多路直推冲突, 已否决留档)
.github/workflows/forge.yml            早期单runner锻造工(保留)
tasks/task-schema.json                 manifest 格式
tasks/manifests/                        任务实例(E2/E3/E4/E6 全归档)
scripts/submit_task.py                  提交入口(本地预检+触发)
scripts/collect_results.py              结果取回
scripts/plan_validator.py               远端 plan 校验
scripts/worker_engine.py                远端单片执行引擎
scripts/aggregator.py                   远端聚合裁决
```

### 验证记录（全部真实 run，2026-09-11）

| 实验 | run | 结果 |
|---|---|---|
| E1 基线 3 片 | 34617083040 | SUCCESS 3/3（首轮全missing=artifact路径bug,已修） |
| E2 并发 8 片 | 34617937318 | SUCCESS 8/8；8 个 job 同秒起跑，runner id 全不同（独立VM实锤） |
| E3 失败注入 | 34618263750 | PARTIAL_SUCCESS：1 failed+1 timeout(15s精确切断) 不拖垮其余2片 |
| E4 规模 16 片 | 34619525525 | SUCCESS 16/16，启动窗口 13s（首跑 aggregate push 被并发撞→写回加rebase-retry×5后绿） |
| E5 模式A对照 | 34618599330 | 4 pusher 中 3 个 non-fast-forward，最终仅 2/4 落地 → 模式A否决，模式B(Artifact+Aggregator)定正 |
| E6 真实任务 | 34619513171 | SUCCESS 5/5：B2B 目录侦察(9站可达性+robots+静态性)，含 for 循环/管道复杂度 |

TESTED_STABLE_PARALLELISM = **16**（E4 实测 16/16 零排队；官方 Free 并发上限 20，
docs.github.com/actions/reference/limits VERIFIED）

### 本机 push 通道备注

本机 git 直连 github 443 时断（代理不稳）。脚本已内置 rebase-retry；若本地
`git push` 失败，可改走 `gh api --method PUT /repos/.../contents/<file>`（E2E 全程
用过，稳定）。gh 便携版在 `C:\Users\17376\.local\ghcli\bin\gh.exe`，device flow
已登录（repo+workflow scope）。
