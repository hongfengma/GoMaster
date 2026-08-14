# 围棋教练 AI 复盘与解说系统 —— 解决方案与可行架构

> 状态：**v0.7.1 · 正式前端（React+TS+Zustand）已构建验证；Electron 桌面 exe 已在本机（沙箱）打包成功（2026-08-13）**
> 当前阶段：端到端可用 —— 后端（KataGo+DeepSeek 复盘）+ 前端（正式 React UI / 零依赖 MVP 兜底）已联通，浏览器或桌面窗口即可逐手复盘
> 本次改动详见 `CHANGELOG_v0.6.md`；Mac 迁移见 `MAC_SETUP.md`；正式前端与打包见 `frontend/README.md`

---

## 0. 已确认技术决策与资源（老马 2026-08-12 确认）

| 项 | 决策 |
|----|------|
| 平台 | Windows + macOS 跨平台 → 最终用 Electron 打包 |
| 前端 | 目标 React（Electron + React + Zustand），棋盘 Canvas+SVG |
| 后端 | Python + FastAPI 本地服务 |
| AI 引擎 | KataGo（Analysis Engine 接口，CPU 模式无独显）+ DeepSeek 讲解 |
| 商业模式 | 暂时自用，授权模块后置 |
| **核心场景** | **复盘指导优先**：导入 SGF → 逐手复盘 → 对比实际落子 vs 推荐选点 → 大模型讲解差距 |

**前端实现现状（v0.5→v0.7 演进）：** 阶段 1 用零依赖原生方案（`web/`）先跑通验证价值；v0.7 已落地**正式前端** `frontend/`（Vite + React 19 + TypeScript + Zustand），棋盘 Canvas 渲染、逐手导航、坐标/变分序号、Markdown 讲解等功能平移自 MVP 并组件化。后端 `server.py` + `src/` 的 API 契约**完全不变**；`server.py` 现优先托管 `frontend/dist`，缺失时回退 `web/`。Electron 桌面外壳（`electron/main.cjs`）已就绪，因需从 GitHub 下载二进制，安装/打包在老马本机进行。
- 前端：`frontend/`（React + TS + Zustand，Canvas 棋盘）
- 服务：Python 标准库 `server.py`（零第三方依赖），同时托管正式前端与 MVP 兜底
- 桌面：Electron 外壳加载 `http://127.0.0.1:8765`（后端不变）

**KataGo 资源（老马提供）：**
- 仓库：https://github.com/lightvector/KataGo
- 神经网络权重：https://katagotraining.org/networks
- 分析配置（stonebase 推荐）：https://raw.githubusercontent.com/lightvector/KataGo/refs/heads/master/cpp/configs/analysis_example.cfg

**DeepSeek（老马提供）：**
- 模型：`deepseek-v4-flash`
- Key：已由老马提供。当前为自用阶段，硬编码在 `src/config.py`，**后续应改为环境变量/本地配置文件且不入库**。

**KataGo 实际落地（2026-08-13 验证）：**
- 程序：`deps/katago/katago.exe`（官方 v1.17.1 **eigenavx2** 纯 CPU 构建，适配无独显机器）
- 权重：`deps/katago_b10c384h6nbttflrs.bin.gz`（b10c384 网络，比 b18c384 小、CPU 更快；老马本机 `C:/Users/mhf/katago/` 已有，直接复制使用）
- 配置：`deps/analysis_example.cfg`（stonebase 原版，按 CPU 调优：`maxVisits` 降到 80，logDir 改为相对 `katago_logs`）

---

## 1. 项目目标（复盘优先）

**核心场景是复盘，不是实时对弈。** 初学者下完一盘棋，往往不知道自己哪一步差、差在哪、为什么 AI 推荐的点更好。本程序解决：导入 SGF 棋谱 → 从第一步起逐手复盘 → 用 KataGo 算出「实际落子」与「推荐选点」的胜率/目差差距 → 用大模型把差距翻译成结合棋理、棋型、局部分析的自然语言讲解。

Slogan 参考：每一步，都看清自己与高手之间的那几目棋。

---

## 2. 竞品与现状（略，见 v0.2：围棋思考教练 / AI Sensei / KaTrain / 星阵 / AlphaGo Teach）

现有工具多偏「实时对弈辅助」或「纯数据展示」，缺少「导入自己棋谱、逐手复盘讲解」的易用整合产品——这正是我们的切入点。

---

## 3. 用户痛点与需求

| 痛点 | 说明 |
|------|------|
| 下完不知道差在哪 | 有 SGF，但只看到胜率曲线，不知自己哪手是败着 |
| 选点没解释 | 红/蓝点只说“下这里”，说不出“这里为什么重要” |
| 缺乏棋理联系 | AI 强在计算，弱在用术语/棋理/棋型解释 |
| 变化树抽象 | 多步变化列表初学者难还原 |
| 缺层次化讲解 | 同一局面，入门/进阶需要不同深度 |

目标用户：围棋初学者到中级（18K–5D），以及用 AI 复盘但看不懂输出的人。

---

## 4. 产品功能规划

### 阶段 1：MVP（端到端已跑通 ✅）
1. ~~**SGF 导入**：解析、加载棋谱，展示基本信息（对局者、贴目、手数）。~~ ✅ 已实现（前端文件/粘贴 + 后端解析）
2. ~~**逐手复盘 UI**：上手/下手/滑块/跳到指定手，棋盘随当前手渲染，标记实际落子/AI 推荐/变化线。~~ ✅ 已实现（`web/` 前端 + Canvas）
3. ~~**每手 KataGo 分析**：以「第 N-1 手后局面」调 analysis，得到当前胜率、实际落子的胜率变化、推荐选点及胜率、变化树。~~ ✅ 已实现
4. ~~**对比展示**：实际落子 vs 推荐选点，标出胜率损失（Δ）。~~ ✅ 已实现（面板 + 棋盘高亮）
5. ~~**DeepSeek 讲解**：为什么实际这步不好/好，推荐点优势，自然融入棋理。~~ ✅ 已实现
6. **基础设置 UI**：KataGo 路径/参数、DeepSeek Key/模型。（后端有配置项，前端已暴露 level/visits，Key 配置 UI 待补）

### 阶段 2：教学增强
1. 变化树可视化（分支切换、胜率标注）。
2. 难度分级 + Prompt 调优。
3. 实时对弈指导（选点即分析、假设推演）——参考产品的「下棋指导」。
4. 棋理知识库 RAG（术语/定式/棋谚检索引用）。

### 阶段 3：体验打磨（自用可延后）
1. 9/13/19 路棋盘（后端已支持任意尺寸，权重需适配）。
2. TTS 语音播报。
3. 历史棋谱管理、用户偏好记忆。
4. 迁移到 Electron+React 正式桌面应用（见 §0 说明）。

---

## 5. 技术架构

### 5.1 分层
```
用户交互层（当前：web/ 原生前端；目标：Electron+React） → 应用服务层（当前：server.py 标准库；目标：FastAPI） → AI 引擎层（KataGo CPU + DeepSeek） → 数据层（SGF/缓存/配置）
```
**已实现层**：AI 引擎层 + 数据层 + 应用服务层（`server.py`）+ 用户交互层（`web/`）。前后端通过 HTTP + JSON 联通。

### 5.2 已实现代码模块
| 模块 | 职责 |
|------|------|
| `src/config.py` | 全局配置：KataGo 路径/权重/配置、DeepSeek Key/模型、分析精度（maxVisits=80）、阈值（5%） |
| `src/go_board.py` | 坐标转换 **SGF ↔ GTP**（GTP 列字母跳过 `I`，符合标准）；Board 类 |
| `src/sgf_parser.py` | 解析 SGF 提取尺寸/贴目/落子序列（已修 PB/PW 误匹配 bug） |
| `src/katago_engine.py` | KataGo analysis 引擎封装：子进程 + JSON 协议、候选点/胜率/变化树解析、错误即时抛出 |
| `src/explainer.py` | 组装讲解 Prompt、调 DeepSeek、空响应重试、LLM 失败兜底讲解 |
| `src/review.py` | 端到端编排：逐手对比「实际 vs 最佳」→ 算胜率差（黑视角→落子方视角）→ 筛失误手 → 调 DeepSeek → 返回结构化 dict + 进度回调 + 生成 Markdown |
| `run_review.py` | CLI 入口（复用 review.run_review） |
| `server.py` | **零依赖 HTTP 服务**：托管 `web/` 静态资源 + `POST /api/analyze` + `GET /api/analyze/<id>` 轮询 + 健康检查 |
| `web/index.html` / `web/styles.css` / `web/app.js` | **前端 MVP**：SGF 导入、Canvas 棋盘渲染、逐手导航、实际 vs 推荐对比、胜率差、DeepSeek 讲解展示、变化线可视化 |

产物：`sample/9x9-demo.sgf`（示例棋谱）、`sample/9x9-demo-复盘报告.md`（示例报告）。

### 5.3 KataGo（CPU 模式，本地）
- 接口：**Analysis Engine**（JSON over stdin/stdout），比 GTP 更适合拿候选/胜率/变化树。
- 构建：eigenavx2（纯 CPU，**不依赖显卡驱动**）。
- CPU 参数：`maxVisits` 80（9 路足够）、`numAnalysisThreads=2`、`backend` 由构建本身决定（命令行不可另传，否则启动即报错）。
- 实测：9 路 80 visits 每手分析约数秒；20 手 ×2 分析 + 讲解，端到端约 8–12 分钟（含 DeepSeek 出网耗时）。

### 5.4 DeepSeek
- 接口：官方兼容 OpenAI 协议（`https://api.deepseek.com/v1`），模型 `deepseek-v4-flash`，Key 本地配置。
- 实测：返回 200，讲解质量高（生活化比喻 + 棋理融入），适合初学者。

### 5.5 前端（v0.5 零依赖 MVP `web/` + v0.7 正式前端 `frontend/`）

**运行方式：**
```
cd C:/Users/mhf/WorkBuddy/围棋教练AI复盘
python server.py 8765        # 需 Python 3（标准库，无需 pip install）
# 浏览器打开 http://127.0.0.1:8765
```
**API 契约（前端 ↔ 后端）：**
- `POST /api/analyze`　请求体 `{sgf, visits?, threshold?, level?}` → `{task_id, meta:{size,total_moves,komi,...}}`
- `GET /api/analyze/<task_id>` → 快照 `{status, current, meta, entries[], mistakes[], error, report_path}`
  - `entries[]` 每项：`{no, color, actual, best, best_pv_sgf[], ai_wr, actual_wr, delta, explain?}`
  - 进度事件：`move`（逐手分析完成）/ `explain`（某手讲解就绪）/ `done`（完成）
- `GET /api/health` → `{status:"ok"}`
- 静态：`/` → index.html；`/app.js`、`/styles.css` 同源托管（无跨域问题）

**前端交互：**
- SGF 导入：选文件或粘贴文本；可选用户水平（入门/进阶/挑战）、分析精度 visits。
- 棋盘：Canvas 绘制（木色 + 网格 + 星位），棋子黑/白；当前手「你的落子」红圈、「AI 推荐」绿圈、「推荐后续变化」蓝色虚线。
- 导航：滑块（第 0~N 手）、上一手/下一手、失误手列表点击跳转。
- 信息面板：当前手实际 vs 推荐、胜率(推荐)→胜率(实际)、胜率差 Δ、DeepSeek 讲解文本。
- 总览：总手数、已分析、失误手数、最大偏差手。

> **v0.7 正式前端 `frontend/`**：与 `web/` 功能对等，技术栈升级为 Vite + React + TypeScript + Zustand，棋盘用 Canvas 渲染，讲解用**内置轻量 Markdown 渲染器**（不依赖 react-markdown，避免沙箱装包卡死）。构建产物 `frontend/dist` 由 `server.py` 自动托管（无 dist 时回退 `web/`）。**v0.7.1 已在本机（沙箱，走 npmmirror 镜像）用 electron-packager 打包出 `GoMaster.exe`**（Windows 免安装包，resources 内嵌 server.py/src/deps/.env/dist），后端路径已适配开发态/打包态。详见 `frontend/README.md`。

---

## 6. 核心数据流：复盘时序

```
导入 SGF（前端文件/粘贴）→ 后端解析每手序列
  ↓
前端 POST /api/analyze → 后端起后台线程跑 review.run_review（progress_cb 推进度）
  ↓
遍历到第 N 手（progress_cb 逐手推送）：
  后端以「第 N-1 手后局面」调 KataGo analysis（moves 用 GTP 小写 b/w + 跳过 I 的坐标）
    ↓
  返回：候选选点 + 各点胜率（黑视角）+ 变化树(PV)
    ↓
  计算：AI 最佳选点胜率(落子方视角) vs 实际落子后胜率(落子方视角) = 胜率差 Δ
    ↓
  Δ ≥ 阈值(5%) → 标记为失误手 → 组装 Prompt（实际 vs 推荐、胜率差、变化树、难度）
    ↓
  调 DeepSeek → 返回讲解（失败则兜底讲解）
    ↓
前端轮询 GET /api/analyze/<id>：棋盘随 current 渲染、信息面板与讲解逐手填充
    ↓
完成：report_path 生成 Markdown 报告；前端展示全部失误手讲解
```

---

## 7. 关键 Bug 修复记录（v0.4–v0.5 执行中踩坑，已解决）

| # | 现象 | 根因 | 修复 |
|---|------|------|------|
| 1 | KataGo 启动即崩溃 | `analysis` 子命令不接受 `-backend` 命令行参数 | 去掉，backend 由构建决定 |
| 2 | KataGo 启动即崩溃 | `analysis_example.cfg` 的 `logDir` 相对 cwd 解析失败 | 改为相对 `katago.exe` 的 `katago_logs` |
| 3 | KataGo 返回 warning 被误当分析结果 | 读取逻辑收到带 id 的 warning 即返回 | 跳过 warning/error，等真正的分析 JSON |
| 4 | 所有分析请求被拒、90s 超时空转 | 传给 KataGo 的 moves 颜色是大写 `B/W`，协议要求小写 `b/w` | 引擎统一 `str(c).lower()` |
| 5 | 坐标转换返回 None / pass | `review._sgfcoord_to_gtp` 缩进错误，正常分支不可达 | 修正缩进 |
| 6 | KataGo 报 `Could not parse board location: I3` | GTP 列字母未跳过 `I`（第 9 列应为 `J`） | `xy_to_gtp`/`gtp_to_xy` 列索引跳 I |
| 7 | 胜率出现 97.7% 等荒谬值 | KataGo 胜率恒为黑视角，白方落子未转换、且 after 多减一次 | 统一 `_to_color_wr` 视角转换 |
| 8 | 部分失误手讲解为空 | DeepSeek 偶发返回空 content（HTTP 200） | 空内容检测 + 重试 2 次 + LLM 失败兜底讲解 |
| 9 | 轮询进度 status 一直 `pending` | `run_task` 漏设 `status="running"` | 起线程即置 `running`，done/error 再改 |

---

## 8. 模块划分与 Prompt 工程

### 8.1 复盘讲解 Prompt（核心，已落地 `explainer.py`）
```
你是一位耐心、擅长用生活化比喻讲解的围棋老师，正在为「入门」水平的围棋爱好者做复盘。
请用通俗易懂、鼓励的语气……讲解要具体，紧扣这一手的得失。

这是一盘 9 路棋盘的复盘。第 N 手（黑/白方）出现了明显分岔，请你讲解：
【前情】最近几手依次是：Bcc, Wgg, ...
【该方实际落子】X
【AI 推荐落子】Y
【胜率对比】若走推荐点，该方胜率约 A%；实际走子后降到约 B%，下降了 C 个百分点。
【AI 推荐后续变化】Y → ...
请按以下结构讲解：1) 实际落子的问题 … 2) 为什么 Y 更好 … 3) 融入棋理 … 4) 打个比方。控制在 200 字以内。
```

### 8.2 提升质量技巧（DeepSeek 建议，部分已落地）
1. RAG 棋理库：术语/定式/棋谚向量检索引用，降幻觉。（阶段 2）
2. 局面自动检测：检测角部构型/弱棋块/模样，生成文字概述。（阶段 2）
3. 变化图约束：明确告诉模型实际演变，避免凭空想象。（✅ 已用 PV 变化树约束）
4. 语气分层：按级位调提示词。（✅ `level=入门/进阶/挑战` 已接入）

---

## 9. 风险与应对

- **CPU 慢**：调低 `maxVisits`、分析缓存、**只对胜率波动 >5% 的关键手调 LLM**。（✅ 已实现，实测端到端 8–12 分钟/20 手）
- **DeepSeek 偶发空响应**：重试 + 兜底讲解。（✅ 已解决）
- **权重下载受限**（沙箱网络）：官方 GitHub release 自带权重可直连；`media.katagotraining.org` 在本沙箱被墙，老马本机可直接下载更强 b18c384 权重换用。（✅ 用老马本地权重解决）
- **npm 不可达**：沙箱白名单拦截 `registry.npmjs.org`，无法装 React/Electron。→ 阶段 1 用零依赖原生前端先跑起来；本机有网时再迁移。（✅ 已用零依赖方案解决）
- **19 路棋盘性能**：CPU 下 maxVisits 需更低（如 30–50），或后续引入 GPU/云端 KataGo。

---

## 10. 执行状态与下一步（v0.5）

**已跑通（2026-08-13）：**
- [x] 方案 v0.3（复盘优先）+ v0.4（后端执行）+ v0.5（前端 MVP）
- [x] 验证 DeepSeek API（deepseek-v4-flash + Key，返回讲解）
- [x] 下载 KataGo（CPU 版 eigenavx2）+ 权重 + analysis_example.cfg
- [x] 验证 KataGo analysis 返回 JSON（CPU 模式）
- [x] 后端端到端：SGF → 逐手复盘 → 对比 + DeepSeek 讲解 → Markdown 报告
- [x] **前端 MVP**：零依赖 Web 版（web/ + server.py），联调验证「提交 SGF → 轮询 → 20 手全分析 → 7 个失误手讲解就绪 → 前端渲染」
  - 产物：`sample/9x9-demo-复盘报告.md`（9 路 20 手，7 个失误手 LLM 讲解示范）

**下一步：**
1. **老马本机试跑**：`python server.py` 打开浏览器实测交互（沙箱无 GUI，棋盘渲染需肉眼验证；API 闭环已验证）。
2. 前端功能补强：设置面板（DeepSeek Key/权重路径）、讲解加载态、移动端适配。
3. 分析缓存：避免重复分析同一局面，加速大棋谱。
4. 19 路支持与更强权重接入（视老马机器性能）。
5. 阶段 2 教学增强 + **v0.7 已启动正式前端迁移**（React+Electron，见 `frontend/`）：沙箱可构建验证，Electron 本机打包待老马本机执行。

---

## 11. 非开发替代方案（过渡期可用，DeepSeek 建议）

暂不开发也能用「AI 算 + 大模型讲」：
- **KaTrain + ChatGPT 半自动**：KaTrain 开 KataGo 分析，复制推荐点与变化图，粘贴给大模型提问。
- **AI Sensei + 大模型润色**：导出全盘数据，让大模型改写成初学者复盘。
- 这些方法适合老马自用过渡，验证价值后再推进正式开发。
