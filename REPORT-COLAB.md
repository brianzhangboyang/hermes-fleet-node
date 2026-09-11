# Colab 收编报告（2026-09-11 夜，无人值守）

结论：**Colab 已收编为 Hermes 的按需 GPU 临时节点**。全链路 CDP 浏览器自动化
实测通过，金标准 = VM 内 nvidia-smi 返回真实硬件。

## 实测战果

```json
{"python": "3.13.15", "machine": "x86_64", "cpu": 2,
 "gpu": [{"name": "Tesla T4", "driver": "580.82.07", "mem_mb": 15360}],
 "ram_gb": "12", "disk_free": "66G", "net": 200}
```
VERIFIED（run 现场抓取，非文档转述）：免费档 **Tesla T4 16G** 到手。

## 打通的通道（Windows 本机，无 CLI 依赖）

官方 google-colab-cli 仅 Linux/macOS → Windows 控制机走 CDP 直驱：

1. 本地生成 ipynb（metadata 带 `"accelerator":"GPU"` + `"colab":{"acceleratorType":"GPU"}`
   + 自检 cell 打印 `COLAB_GPU_RESULT=` marker）
2. gh contents API PUT 推到 GitHub 仓库 notebooks/ → 取 commit SHA
3. 打开不可变 URL：`colab.research.google.com/github/<o>/<r>/blob/<SHA>/x.ipynb`
   （main 分支 URL 有缓存，必须 SHA——ChatGPT 咨询结论，实测成立）
4. JS `.click()` 穿透 shadow 点"连接到新的运行时" → 轮询"已连接到"出现（约20s）
5. **安全横幅"仍然运行"按钮：JS click 无效，必须穿透 shadow 找内部 #button 再 click**（本次通败关键，v1 成功/v2 连败的差异所在）
6. 真实 CDP 坐标点击 play_arrow（299,84）= 运行全部（对 MD-TEXT-BUTTON，合成 click 无效、域级坐标点击有效）
7. 轮询主文档 innerText 抓 `^COLAB_GPU_RESULT=[...]` 行（marker 带行首锚定排除源码干扰）

## 失败模式档案（每条都烧了轮次）

- md-text-button 用 element.click()：有时透有时不透 → 一律 shadowRoot.querySelector('#button')
- 横幅"仍然运行"的 span 级 click/dispatchEvent/坐标点击全无效 → shadow 内层 button 才有效
- 命令面板 Ctrl+Shift+P：CDP modifiers 位掩码要用 Ctrl=2/Shift=8（曾错用7=Alt+Ctrl+Meta 没开成）
- GitHub blob/main URL 改 ?v= 参数无效 → 用 commit SHA
- 输出若渲染在跨源 output iframe 主文档抓不到；本 notebook 的 stdout 实测是直接进主文档 innerText 的（以 marker 抓到的行首锚定为准）

## 定位与红线（遵守 Colab 免费档 FAQ + ChatGPT 咨询结论）

- 定位 = **按需 GPU 批处理临时工**：单账号、低频、跑完即弃、绝不常驻
- 不做：多账号轮换 / worker farm / 24x7 keepalive daemon / 把免费算力转售或租给第三方
- VM 内不留任何长期凭证；结果走 print→DOM 抓取（第四种方案，最安全）
- 与 github_worker_pool 分工：GitHub = 免费 CPU 弹性并行(≤16路)；Colab = 免费 T4 GPU 单点
  重活；VPS 舰队 = 常驻服务。任务路由按"要不要 GPU/要不要常驻/要不要并行"三问分流。

## 复用方式

金标准探测 notebook 模板已固化：
`D:/Boyang_AI_OS/infra/hermes-fleet-node/notebooks/hermes-colab-selftest.ipynb`
操作细节与选择器策略见 skill `colab-gpu-worker`。
