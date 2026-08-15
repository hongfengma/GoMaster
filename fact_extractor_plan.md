# GoMaster 解读精准度升级：Fact Extractor 方案（合并痛点 1/2/3/4）

> 目标：让 DeepSeek 的讲解"更准"，核心不是把 prompt 写得更细，而是**别让语言模型去感知原始棋盘**——
> 把"看懂棋盘（阶段/棋形/定式/棋子群）"交给确定性程序，LLM 只负责把结构化事实讲成人话。
> 这同时命中你说的 4 个痛点，且**全部本地 CPU 跑，零 API 成本**。

## 一、新架构与数据流

```
SGF 棋谱 ──► KataGo 引擎 ──► Fact Extractor（确定性事实抽取）──► LLM 讲解器 ──► Verifier ──► 讲解文本
              (胜率/PV/目差)    │ ①阶段 ②棋形 ③定式 ④上下文        (消费事实单)   (事实校验)     (含事实标签)
                               └─ 输出结构化「事实单 JSON」──┐
                                                          └─► 同时喂给 RAG 检索（命中更准）
```

- **Fact Extractor** 是本次新增的纯 Python 模块，跑在 KataGo 分析之后、LLM 调用之前。
- **LLM（Narrator）** 不再读 ASCII 棋盘自己"猜"棋形/定式，而是严格基于事实单写讲解。
- **Verifier** 用事实单校验 LLM 的事实声明，拦住幻觉。

## 二、模块设计

### 1. 新增 `src/fact_extractor.py`（确定性，本地 CPU，零 API 成本）
在 `go_board.Board` 上补 `group_and_liberties()` / `count_unsettled()` / `empty_ratio()`，再提供：

| 能力 | 实现方式 | 对应痛点 |
|---|---|---|
| **① 阶段识别** `phase` | 用 KataGo `scoreLead`（目差）+ 空点比例 + 是否存在"气数≤N 的未安定大龙" + 手数 综合判定，替换 `review.py` 现行"按手数比例切"的粗略判断 | 布局/中盘/官子识别 |
| **② 棋形识别** `shape_tags` | 本地模板匹配（相对坐标模板 + 旋转/镜像不变）。v1 先内置约 10 个常见型：**坏形优先标注**（空三角/方四/弯四/接不归/凝形/裂形）+ 少量好形（双/拆二/虎口）。*命名由确定性代码给出，LLM 不再自己认形* | 棋子棋型识别 |
| **③ 定式识别** `joseki` | 把"该手所在角部最近若干手"归一化到标准角，和内置定式字典（小目一间高挂/低挂、星位小飞守角、三三点三三等约 8 个）比对；命中则给"第 X 手偏离标准变化"。可后续扩 Waltheri/Kombilo 大数据 | 常用定式识别 |
| **④ 上下文（不孤立看）** | 事实单携带：最近 N 手坐标 + 各自胜率变化趋势 + 本手棋子群气数/分断关系 + 全局目差/领先方。让模型在"全局态势"语境下讲局部 | 不能孤立看一步 |

### 2. `src/katago_engine.py`：开启 ownership / scoreLead
- `analyze` 增加 `include_ownership` 参数（默认 `False`，不影响其他调用方）；`review` 调"后手分析"时置 `True`。
- 解析 `rootInfo.scoreLead`（目差）与 `ownership`（每点归属图，用于估算实空、判定"未安定大龙"）。

### 3. `src/explainer.py`：消费事实单 + Verifier
- `explain_move` 新增 `fact_sheet` 参数；user 提示改为"**严格基于【事实单】讲解，不得自行读棋盘下棋理结论；事实单未提及的棋理不得杜撰**"。
- 新增 `verify_explain(text, fact_sheet)`：规则校验（坐标合法性已有；补充"事实声明与事实单矛盾"检查），命中矛盾则带事实单重生成一次或明确标注。v1 先用**规则校验（不增 API 调用）**，LLM 级矛盾检测作后续增强。
- 讲解方式：v1 采用**单轮增强提示**（战略态势已塞进事实单一次给到，省一次 API 调用）；两阶段（先产出战略总结再讲局部）作为后续增强。

### 4. `src/review.py`：串起来
- 失误手循环里，分析前后局面后调用 `extract()` 生成 `fact_sheet`，传给 `explain_move`；用 `fact_sheet['phase']` 替换原比例判断；报告 builder 也带上事实标签。

### 5. `src/rag.py` 轻量升级
- `retrieve` 接受 `facts`（shape_tags/joseki/phase），检索 query 自动附加这些标签 → 命中更精准（如识别到"空三角"优先召回棋形条目）。

### 6. 前端（可选增强，低风险）
- 在失误手卡片下展示"本手识别：`空三角` · `小目一间高挂(偏离)`"等事实标签 chip，让讲解有据可查。

### 7. 版本与打包
- 版本建议 **v1.0.0**（准确性里程碑）；打包目录 `dist-electron-v100`；commit + push master。

## 三、fact_sheet 数据契约（摘要）

```json
{
  "move_no": 12, "color": "B",
  "phase": "中盘",
  "phase_reason": "存在气数≤4的未安定大龙且目差中等",
  "actual": "D6", "best": "F6",
  "local_groups": { "own_group_liberties": 3, "capture_happened": false, "cuts": ["将白棋分成两块"] },
  "shape_tags": ["空三角", "接不归"],
  "joseki": { "matched": "小目一间高挂", "step": 3,
              "deviation": "第3手偏离标准变化（标准应小飞，实战大飞）" },
  "strategic_context": {
    "lead_color": "B", "score_lead": 4.2, "empty_ratio": 0.55,
    "unsettled_groups": 2,
    "recent_moves": ["W:C7","B:D4","W:F5"],
    "recent_trend": "近3手黑方胜率 -3%→+5%→-2%"
  },
  "pv": ["F6","Q16","D10"],
  "rag_hints": ["空三角","小目一间高挂"]
}
```

## 四、实施步骤（建议顺序）

1. `go_board` 补 `group/liberties/empty_ratio` + 单测
2. `katago_engine` 开 `ownership/scoreLead` + 解析
3. `fact_extractor.py`：phase/shape/joseki/context + 自测（合成局面，无需 KataGo）
4. `explainer` 改 prompt 消费事实单 + `verify`
5. `review` 串联
6. `rag` 标签增强
7. 前端事实标签展示（可选）
8. 版本 bump + 构建打包 + 推送
9. 沙箱只能跑确定性单测；全链路（KataGo）需老马本机验证

## 五、测试策略

- **确定性部分**：`fact_extractor_selftest()` 用合成棋盘断言气数/棋形/阶段正确（不依赖 KataGo/网络）。
- **端到端**：老马本机跑一局 9 路 + 一局 19 路，看讲解是否出现"基于事实单"的准确表述、红点/曲线仍正常。

## 六、风险与坦诚边界

- 棋形/定式识别是**启发式模板匹配**，v1 准确率有限（复杂局面、罕见定式会更弱）；架构价值在于：即便标签不完美，也比让 LLM 自己读棋盘认形可靠得多，且 Verifier 拦住明显错讲。
- 定式字典 v1 仅内置少量常见型，需后续扩充数据。
- **不增加任何 API 成本**（全本地确定性）。

## 七、待你拍板

- 讲解方式：单轮增强提示 vs 两阶段提示？
- Verifier：v1 是否纳入（规则校验，不增 API 调用）？
- 版本号：v1.0.0 还是 v0.10.0？
