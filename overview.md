# 围棋教练 AI 复盘 · v1.1.1 交付总览

> 时间：2026-08-15  |  范围：v1.1.0 实测问题修复 + 可控性增强

## 一、本次修复的问题

针对 v1.1.0 实测反馈，做如下修补：

1. **棋盘标签遮挡棋子**
   - 标签背景改为半透明（alpha 0.78），颜色调深以保证可读性；
   - 标签位置移到棋子右上方，避免覆盖棋子本体；
   - 字体/标签整体缩小，每处最多显示 2 个标签。

2. **定式挂角名称错误**
   - 修正 `_relation_name`：`(1,2)/(2,1)` 现正确识别为「小飞挂」，不再误标为「一间高挂」；
   - 同步重排 `_JOSEKI_LIBRARY` 的 key，覆盖小飞挂、一间高挂、大飞挂、二间高挂等常见型。

3. **补断/联络/边线被误读**
   - `fact_extractor.py` 新增 `_detect_connection`：检测一手是否连接己方两块棋（补断/联络），以及是否落在一/二线；
   - 事实单新增 `connection` 字段，并在 `fact_to_text` 中写入「补断/联络」或「一二线边线」提示；
   - `explainer.py` prompt 强化：写明「补断/联络」时不可讲成「隔离/分断/切断」；一二线必须描述为边线/底线；
   - `verify_explain` 增加规则校验，命中「连接却讲隔离」时追加系统提示。

4. **整体耗时变长**
   - 设置界面新增「启用 LLM 级事实校验」开关（默认开启）；
   - 关闭后每失误手省一次 DeepSeek 调用，显著降低长局总耗时；
   - 开关持久化到 `~/.gomaster/config.json` 的 `llm_verify` 字段。

## 二、关键改动文件

- `src/fact_extractor.py`：新增 `_detect_connection`；修正 `_relation_name` 与 `_JOSEKI_LIBRARY`。
- `src/explainer.py`：prompt 增强补断/边线约束；`verify_explain` 增加连接矛盾校验；`verify_and_correct` 由 `verify` 参数控制。
- `src/review.py`：`run_review` 增加 `llm_verify` 参数并透传给 `explain_move`。
- `src/userconfig.py`：新增布尔字段 `llm_verify`，持久化逻辑兼容 bool 类型。
- `server.py`：`/api/version` 返回 `1.1.1`；`/api/analyze` 从用户配置读取 `llm_verify` 并传入复盘线程。
- `frontend/src/board-utils.ts`、`Board.tsx`、`ReportView.tsx`：标签半透明、防遮挡、最多 2 个。
- `frontend/src/components/Settings.tsx`、`api.ts`、`index.css`：新增 LLM 校验开关与样式。

## 三、产物

- **Windows 免安装 exe**：`frontend/dist-electron-v111/GoMaster-win32-x64/GoMaster.exe`
- 运行需本机已装 Python 3；exe 内嵌 `.env`（DeepSeek Key），**仅限自用，勿外发**。

## 四、使用提醒

- 只双击 `frontend/dist-electron-v111/.../GoMaster.exe`。
- 旧版 `dist-electron-v075/v100/v110` 等目录里的 exe 建议删除，避免误点。
- 若长局讲解耗时仍觉慢，可在「设置」中关闭「启用 LLM 级事实校验」，但坐标/区域/定式等细节错误概率会略升。
