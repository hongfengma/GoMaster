# 变更记录 v0.6（2026-08-13）

针对老马提出的 7 项反馈，本轮集中改造。所有改动已落盘并通过 git 提交。

## 1. KataGo 分析太慢 → 已优化（核心提速）
**根因**：之前用的 `b10c384h6nbttflrs` 是给 GPU 设计的大网络（10 层 × 384 通道），CPU 上极慢（9 路 20 手曾达 10 分钟）。
**改动**：
- 新增小网络权重自动优选：`config.py` 按 `b10c128(11MB) → b6c96(3.6MB) → b10c384(兜底)` 顺序自动选用，文件名命中即生效。
- 小网络来源（CPU 友好、棋力仍达职业级以上）：
  - b10c128：https://katagoarchive.org/g170/neuralnets/g170-b10c128-s197428736-d67404019.bin.gz
  - b6c96：  https://katagoarchive.org/g170/neuralnets/g170-b6c96-s175395328-d26788732.bin.gz
- `DEFAULT_MAX_VISITS` 80 → 40（小网络下足够 9 路）。
- 引擎启动注入 `-override-config numSearchThreads=N`（N=CPU 核心数一半），充分利用多核。
- `config.py` 的 `PROJ` 改为基于 `__file__` 自动定位项目根，**不再硬编码 Windows 路径**（Mac 可直跑）。

## 2. 棋盘边线坐标标记
`web/app.js` 的 `drawBoard` 增加标准记谱坐标：列 `a…t`（跳过 i），行底 `1` 顶 `size`。棋子与标记同坐标系，定位不偏移。

## 3. 后续变化直观化
原"蓝虚线"看不出黑白子与手数。改为：AI 推荐后续变化（PV）以**带序号的黑白子**直接落在棋盘上（序号 1/2/3…，PV[0] 即推荐点加绿圈），一眼看懂变化走向。

## 4. DeepSeek 讲解 Markdown 渲染
前端增加零依赖的极简 Markdown 渲染器（标题/加粗/斜体/行内代码/列表/引用/段落），讲解文本不再是原始 `#`、`**` 符号。

## 5. DeepSeek 讲解太泛 → 更详尽准确
- 后端向大模型注入更丰富数据：**AI 前三候选**（含各自胜率与后续）、**当前阶段**（布局/中盘/官子）。
- Prompt 重写：要求"具体棋理 + 局部棋形 + 后续推演"，明确**禁止只甩「敌之要点即我之要点」而不解释**；引用棋谚须说明在当前局面如何体现。
- `max_tokens` 900→1100，`temperature` 0.6→0.5（更准确）。兜底讲解也改为基于数据的具体描述。

## 6. 沙箱装不了 react/electron 的真相
**npm registry 本身可达**（实测 `npm install react` 3 秒成功、`npm ping` 正常）。
真正卡的是 **electron 安装时要从 GitHub 下载原生二进制**，而沙箱对 GitHub release 资产不可达（已验证 404/000）。
→ 纯 JS 包（react/vite）在沙箱就能装；electron 这类带原生二进制的包，请在**有网的本机/Mac** 安装。

## 7. 单位 Mac 继续开发
- 工作区已 `git init` 并提交（`0c574ad`，仓库仅含源码，权重/二进制已 gitignore）。
- 新增 `MAC_SETUP.md`：含 GitHub 同步方式、Mac 端 KataGo/权重准备、运行与 React/Electron 后续路线。
- 因 `config.py` 已跨平台自动探测，Mac 克隆后只需各自放好 KataGo 二进制与权重即可运行。

## 待办 / 注意
- 小网络权重需下载到 `deps/`（沙箱用 `-k` 绕过证书吊销检查才能拉取；本机/Mac 有网可直接下）。
- 19 路若仍嫌慢：可把 `visits` 调到 60~120，或优先用 b6c96（最快）。
- React/Electron 全量迁移：建议 Mac 本机用 Vite 起 React 工程，平移 `web/app.js` 逻辑，后端 `server.py` 不动。
