# 围棋教练 AI 复盘 · v0.7.5 交付总览

> 时间：2026-08-14  |  范围：本机实测交互 + Electron 桌面打包

## 一、当前状态

v0.7.5 已修复 v0.7.4 最顽固的「新 exe 仍显示旧界面」问题，核心改动是 **Electron 外壳自动检测并避开已被占用的 8765 端口**，同时棋盘新增窗口 resize 监听、后端新增 `/api/version` 用于调试。

## 二、v0.7.5 关键修复

1. **动态端口（根治旧后端残留）**
   - `frontend/electron/main.cjs`：启动前先探测 8765 是否空闲；若被旧实例占用，自动递增到 8766/8767… 再启动新后端、从新端口加载前端。
   - 这彻底避免了「新 exe 启动后仍连到旧后端、显示旧界面/旧坐标」的问题。

2. **棋盘响应式增强**
   - `frontend/src/components/Board.tsx`：新增 `window.resize` 监听，窗口大小变化后自动重绘棋盘。
   - 棋盘尺寸保持 `window.innerWidth * 0.6`，最小 600px，最大 860px。

3. **后端版本标识**
   - `server.py` 新增 `GET /api/version`，返回 `{version:"0.7.5", cwd:...}`，便于用户开 DevTools 确认连接的是哪个后端。

4. **代码层面坐标问题已确认修复**
   - `src/review.py`：`actual` = 大写 GTP（如 `G7`），`actual_sgf` = SGF（如 `ge`）；`best` 同样 uppercase。
   - 前端 `InfoPanel` / `MistakeList` 直接显示 `e.actual` / `e.best`。
   - `Board.tsx` 用 `actual_sgf` 绘制棋子。

## 三、产物

- **Windows 免安装 exe**：`frontend/dist-electron-v075/GoMaster-win32-x64/GoMaster.exe`（约 177MB）
- 运行前需本机已装 Python 3；exe 内嵌 `.env`（DeepSeek Key），**仅限自用，勿外发**。

## 四、使用提醒

- **只双击 `dist-electron-v075/.../GoMaster.exe`**。
- 旧目录 `dist-electron/`、`dist-electron-v072/`、`dist-electron-v073/`、`dist-electron-v074/` 里的 exe 都不要点；建议本机删除这些旧目录。
- v0.7.5 会自动换端口，无需手动结束旧进程；但为避免资源浪费，打开新 exe 前仍可手动关闭旧 GoMaster 窗口。
- classic PAT 已在历史对话中泄露，强烈建议去 GitHub Settings → Developer settings → Personal access tokens 中 revoke。

## 五、交付文件

- `frontend/dist-electron-v075/GoMaster-win32-x64/GoMaster.exe`
- `frontend/electron/main.cjs`
- `frontend/src/components/Board.tsx`
- `server.py`
- `frontend/package.json`
