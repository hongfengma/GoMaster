# 围棋教练 AI 复盘 · 正式前端（React + TypeScript + Zustand）

本目录是项目的**正式前端**，替代 `web/` 零依赖 MVP。后端 API 契约不变（`server.py` + `src/`）。

## 技术栈
- Vite + React 19 + TypeScript
- Zustand 状态管理（含自动轮询）
- Canvas 棋盘渲染（边线坐标 / 变分带序号黑白子 / 实际落子红圈 / AI 推荐绿圈）
- 讲解渲染：内置轻量 Markdown 渲染器（不依赖 react-markdown，避免沙箱装包卡死）

## 本地开发
```bash
cd frontend
npm install
npm run dev            # 默认 http://localhost:5173
```
> 开发前需先启动后端：在仓库根目录 `python server.py 8765`，前端通过同源 `/api/*` 访问。

## 生产构建
```bash
npm run build          # 产物输出 frontend/dist
```
构建后由根目录 `server.py` 自动托管：`python server.py 8765` 打开 http://127.0.0.1:8765 即加载正式前端；无 `dist` 时回退到 `web/`。

## 桌面应用（Electron）
Electron 二进制需从 GitHub 下载。在国内/沙箱环境安装与打包时，**必须指定国内镜像**，否则会卡在从 GitHub 下载 electron 二进制（反复重试）。

### 1) 安装 Electron（国内镜像）
```bash
cd frontend
ELECTRON_MIRROR="https://cdn.npmmirror.com/binaries/electron/" npm i -D electron electron-packager --legacy-peer-deps
```

### 2) 开发态桌面运行
```bash
npm run build
python ../server.py 8765 &   # 先起后端
npm run electron             # 打开桌面窗口，加载 http://127.0.0.1:8765
```

### 3) 打包为 Windows 免安装 exe（已实测通过）
```bash
# 先确保已 npm run build 生成 dist/
ELECTRON_MIRROR="https://cdn.npmmirror.com/binaries/electron/" \
ELECTRON_CACHE="$LOCALAPPDATA/electron/Cache" \
npx electron-packager . GoMaster \
  --platform=win32 --arch=x64 --out=dist-electron --overwrite --prune \
  --extra-resource=../server.py --extra-resource=../src \
  --extra-resource=../deps --extra-resource=../.env --extra-resource=dist \
  --ignore='(dist|src|deps|server\.py|node_modules/electron|node_modules/electron-packager|dist-electron)'
```
产出：`frontend/dist-electron/GoMaster-win32-x64/GoMaster.exe`（含 electron 运行时 + resources 内嵌 server.py / src / deps / .env / dist）。

### ⚠️ 运行桌面 exe 的前置条件
- **本机需安装 Python 3**（exe 通过 `py` / `python` / `python3` 拉起后端）；后端只用 Python 标准库，无需额外 pip 包。
- `.env`（含 DeepSeek Key）已随包内嵌在 `resources/.env`——**仅限自用，切勿把 exe 发给他人**。
- 双击 `GoMaster.exe` 即自动起后端并打开复盘窗口；关闭窗口会杀掉后端进程。

## 目录
- `src/types.ts`        数据类型（与后端 entries 对齐）
- `src/api.ts`          `/api/analyze` 提交 + 轮询封装
- `src/store.ts`        Zustand 全局状态 + 自动轮询
- `src/board-utils.ts`  坐标转换 + Canvas 绘制
- `src/components/`      Board / Toolbar / Navigator / InfoPanel / MistakeList / MarkdownView
- `src/App.tsx`         整体布局
- `electron/`           Electron 外壳（main.cjs / preload.cjs）
  - `main.cjs`：spawn 拉起 Python 后端 → 轮询 8765 端口就绪 → 加载窗口 → 退出时清理
