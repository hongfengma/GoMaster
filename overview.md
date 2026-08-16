# 围棋教练 AI 复盘 · v1.1.2 交付总览

> 时间：2026-08-15  |  范围：整体优化（线数锚定 / 定式角色 / 推荐点事实单 / 方向感 / KataGo 全字段利用）

## 一、本次要解决的问题（来自实测反馈）

v1.1.1 出现 3 类典型误读，根因一致：**给大模型的事实单空间描述不精确 → LLM 自行脑补线数、定式名、跨盘关联**。本次不再"打补丁式"修个别点，而是从源头重构事实抽取：

1. **R14 被认成第四线、定式被误认一间高挂**
   - 新增 `line_of_xy` / `line_of_gtp`：以"到最近边距离 + 1 = 第 N 线"标准化（R14 距右边 2 格 → 「右边第三线」），事实单与讲解强制以「第 N 线」措辞锚定，杜绝"第四线"式幻觉。
   - 定式识别改为**角色判定**而非硬命名：`_detect_joseki` 先判断首子→挂角→应手→定式外/脱先；脱先或定式外时**不强行套定式名**（R14 不再误标"二间低挂"）。

2. **Q13 与 Q4 被讲成拆二、S14 方向感错（压迫白棋右边）**
   - 拆二/联络/配合检测加**严格空间约束**：仅当两子曼哈顿距离 ≤ 3、且落子关系符合棋理时才成立；>3 格一律禁止描述为"拆二/配合/压迫"。
   - 新增 `ownership` 驱动的**方向感分析** `_analyze_direction`：对比实际点与推荐点的领地倾向（己方强势力/对方强势力/均势）。S14 一带若属对方强势力区，讲解应讲"打入/破空/侵消"，而非"压迫"。
   - `explainer.py` 强化 prompt「严禁跨盘关联」条款；新增 `verify_explain` 跨盘检测：若文本含拆二/配合/压迫/联络等关系词且任一提取坐标曼哈顿距离 > 3，追加系统提示「事实单未支撑跨盘关联」。

3. **KataGo 全接口数据利用（用户要求）**
   - 此前仅用 `winrate` / `scoreLead` / `moveInfos[0].pv`。本次把**早已开启但从未解析**的数据全部用上：
     - `ownership`（top-level，`includeOwnership=true`，行优先 `[-1,1]` 黑正）：驱动「棋子群安定度」「方向感领地倾向」「推荐点归属」；
     - `moveInfos[]` 每位候选：`prior` / `utility` / `lcb` / `scoreSelfplay` / `pv` → 用于评估"实际手 vs 推荐手的优先度差"；
     - `rootInfo`：`scoreStdev` / `scoreSelfplay` / `visits` / `thisHash` → 判断局势确定性；
     - `policy`（`includePolicy`）→ 全局走子分布（后续可扩展热点图）。
   - `katago_engine.py` / `review.py` 已正确透传这些字段，本次**无需改动**（仅 fact_extractor 内部消费）。

## 二、关键改动文件

- `src/go_board.py`：新增 `nearest_edge` / `line_of_xy` / `line_of_gtp` / `ownership_at` / `group_ownership` / `is_stable_group`（安定度 = 气≥3 或 群 ownership 均值 |≥0.85|，避免把厚势误判为"未安定大龙"）。
- `src/fact_extractor.py`（重构）：
  - 阶段判定改用 ownership 区分"厚势 vs 未安定"；
  - `_detect_shapes` 拆二严格距离=2 且中间为空；
  - `_detect_joseki` 角色判定 + 脱先识别（自带 selftest 断言）；
  - `_analyze_direction` 方向感；
  - `_extract_point_fact` 推荐点事实单（`best_fact`：区域/线数/归属/邻近子）；
  - `fact_to_text` 增加线数锚定、best_fact、方向块、禁跨盘关联声明；
  - `extract_fact` 解析 ownership / score_lead / score_selfplay / score_stdev / 实际手 prior+scoreLead，输出 `confidence`（高=坏形或确认定式角色；中=区域差/匹配；否则低）。
- `src/explainer.py`：prompt 加「6.5 严禁跨盘关联」；`verify_explain` 增加跨盘检测（含 `size` 参数）；`verify_and_correct` 系统提示项 6。
- `frontend/src/types.ts`：新增 `FactSheet` 接口（`line_dir/line_no/best_*`/`joseki`/`direction`/`best_fact`/`confidence` 等），`ReviewEntry.fact?`。
- `frontend/src/components/Board.tsx`、`MistakeList.tsx`、`ReportView.tsx`、`index.css`：**事实标签仅在 `confidence === "高"` 时渲染**；报告新增「推荐点事实单」区块（虚线框）。
- `server.py`：`/api/version` 返回 `1.1.2`。
- `frontend/package.json`：version `1.1.2`，`electron:pack` 产物目录 `dist-electron-v112`。

## 三、产物

- **Windows 免安装 exe**：`frontend/dist-electron-v112/GoMaster-win32-x64/GoMaster.exe`
- 运行需本机已装 Python 3；exe 内嵌 `.env`（DeepSeek Key），**仅限自用，勿外发**。

## 四、自测

- `src/fact_extractor.py` 自带 `_selftest` 全部通过：方四/空三角/单子气数/阶段/角部分类/区域/第 N 线（R14=右边第三线）/定式角色脱先（R14 不再误标二间低挂）。
- 全部后端模块 `py_compile` 通过；`explainer` 导入正常。

## 五、使用提醒

- 只双击 `frontend/dist-electron-v112/.../GoMaster.exe`。
- 旧版 `dist-electron-v111` 等目录里的 exe 建议删除，避免误点。
- 事实标签「高置信」才显示，可在「设置」关闭「启用 LLM 级事实校验」以提速（但细节错误概率略升）。
