# 围棋教练 AI 复盘 · v1.1.0 交付总览

> 时间：2026-08-15  |  范围：解读准确性深化 + 定式库/Verifier/标签上盘/分类统计

## 一、当前状态

v1.1.0 针对实测反馈的「坐标引用错误」「四线被误称为中腹」等问题，做了四层深化：

1. **坐标与区域锚定**：事实单输出「涉及坐标」「区域（角/边/中腹）」，并在 prompt 中强制 LLM 只能引用这些坐标，四线及以下不再被说成中腹。
2. **定式库 + 偏差检测**：本地内置常见星位/小目/三三/目外/高目定式库，识别角部定式基底与挂角关系，当前手若不在常见应手集合内则标记「定式偏离」。
3. **LLM 级 Verifier**：每手讲解后多一次审核调用，自动检查坐标、区域、阶段、棋形、定式、变化图混淆等矛盾，必要时输出修正版。
4. **事实标签上盘 + 失误分类统计**：棋形/定式/分类标签直接画在棋盘图例与报告里；总览面板新增当前视角方的失误分类统计。

## 二、关键改动文件

- `src/go_board.py`：新增 `zone_of_xy/gtp`、`line_to_edge`、`nearby_stones`；区域定义：四线及以下为边/角，五线及以上为中腹。
- `src/fact_extractor.py`：棋形输出涉及坐标；扩充 `_JOSEKI_LIBRARY` 与 `_detect_joseki` 偏离检测；新增 `_classify_mistake` 分类；事实单含 `zone`、`best_zone`、`category`、`shape_stones`、`joseki.expected` 等。
- `src/explainer.py`：系统/用户提示强化坐标铁律与区域铁律；新增 `verify_and_correct`（LLM 级审核+修正，一次额外调用）；统一把「无矛盾」收敛为「无」。
- `src/review.py`：entry 挂载 `category`；`fact_tags` 增加「定式偏离」与分类；Markdown 报告新增「失误分类统计」与逐手分类/标签。
- `server.py`：`/api/version` 返回 `1.1.0`。
- `frontend/src/board-utils.ts`、`Board.tsx`、`ReportView.tsx`：Canvas 绘制事实标签（坏形红 / 定式绿 / 分类蓝）。
- `frontend/src/App.tsx`、`MistakeList.tsx`、`index.css`、`types.ts`：总览分类统计、分类 chip、样式、类型声明。
- `frontend/package.json`：版本 `1.1.0`，打包目录 `dist-electron-v110`。

## 三、产物

- **Windows 免安装 exe**：`frontend/dist-electron-v110/GoMaster-win32-x64/GoMaster.exe`
- 运行需本机已装 Python 3；exe 内嵌 `.env`（DeepSeek Key），**仅限自用，勿外发**。

## 四、使用提醒

- 只双击 `frontend/dist-electron-v110/.../GoMaster.exe`。
- 旧版 `dist-electron-v075/v100` 等目录里的 exe 建议删除，避免误点。
- LLM 级 Verifier 每失误手多一次 DeepSeek 调用，费用较低但会增加总耗时；后续可在设置里增加开关。
- classic PAT 已在历史对话中泄露，建议去 GitHub Settings → Developer settings → Personal access tokens 中 revoke。
