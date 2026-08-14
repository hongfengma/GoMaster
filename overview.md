# 围棋教练 AI 复盘 · v0.7.1 交付总览

> 时间：2026-08-13  |  范围：本机实测交互 + Electron 桌面打包

## 一、本机实测（接口/数据流级）
沙箱无 GUI/浏览器，无法肉眼看 Canvas 渲染，故做**接口级端到端联调**：

- 起 `server.py` 托管正式前端 `frontend/dist`：`GET /` 返回 React 版 index.html、`/assets` 200、`/api/health` ok。
- 提交真实 `sample/9x9-demo.sgf`（9 路 20 手）跑完整分析：**KataGo 20 手全分析（~24s）、12 个失误手判定、DeepSeek 逐手讲解生成**。
- **字段对齐验证**：API 返回 `ai_wr`/`actual_wr`/`best_pv_sgf`/`top3`/`phase`/`delta`/`explain` 与 `frontend/src/types.ts` 逐一吻合；`InfoPanel` 已优雅处理 `explain` 为空（小 delta 手不调 LLM，显示"该手暂无讲解"）。**前端能正确消费联调数据**。

## 二、桌面打包（Electron，沙箱实测通过）
**踩坑→破法**：`electron-packager` 默认从 GitHub 拉 electron 二进制 + 校验和，沙箱 GitHub 被掐 → 无限重试 8 分钟零产出。
**解决**：打包前 `export ELECTRON_MIRROR="https://cdn.npmmirror.com/binaries/electron/"`（npmmirror 镜像可达，108MB zip HTTP 200）+ `--prune`，**9 秒完成**。

**产物**：`frontend/dist-electron/GoMaster-win32-x64/GoMaster.exe`（177MB，Windows 免安装包）

**产物结构**：
```
GoMaster-win32-x64/
├── GoMaster.exe            # 主程序
└── resources/
    ├── app/                # 前端（asar/目录）
    ├── server.py           # Python 后端（开发态/打包态路径已适配）
    ├── src/                # 分析引擎（KataGo+DeepSeek）
    ├── deps/               # KataGo 二进制 + 权重
    ├── dist/               # 前端构建产物（server 实际托管此目录）
    └── .env                # DeepSeek Key（内嵌，仅限自用）
```

**关键修复**：
1. `main.cjs` 的 `findPython()`：原用异步 `spawn` 探测（永远返回首选项），改为 `spawnSync` 同步探测，Windows 优先 `py` 启动器。
2. 打包态路径：server.py 的 `DIST_DIR` 改相对自身；`config.py` 的 `DEPS` 改 `os.path.join(HERE,"..","deps")`，兼容开发态/打包态。
3. `electron/` 外壳补"spawn 拉起后端 + 端口就绪检测 + 退出清理"逻辑。

**打包后后端冒烟测试通过**：cwd 切 `resources/` 跑 `server.py 8771` → `/api/health` 返回 ok，`GET /` 返回 React 页面，证明打包态下 dist 解析/.env 密钥/deps 路径全部正确。

## 三、遗留与注意事项
- ⚠️ 沙箱无显示器，**Canvas 棋盘/讲解的视觉渲染需老马本机双击 exe 或 `npm run dev` 肉眼确认**。
- ⚠️ exe 内嵌 `.env`（DeepSeek Key），**仅限自用，勿外发**。
- ⚠️ 运行 exe 需本机装 **Python 3**（exe 经 py/python/python3 拉起后端，仅用标准库）。
- 代码尚未推 GitHub（GoMaster/main 仍是 v0.6.5 旧版）；v0.7.1 的 frontend/Electron 改动待推，仍走 classic PAT + api.github.com 通道。

## 四、交付文件
- `frontend/dist-electron/GoMaster-win32-x64/` —— 可直接运行的桌面应用
- `frontend/README.md` —— 开发/构建/打包完整命令（含国内镜像环境变量）
- `frontend/electron/main.cjs` —— Electron 外壳（spawn 后端 + 端口检测）
- `围棋教练AI方案.md` —— 已更新至 v0.7.1 状态
- `server.py` / `src/config.py` —— 打包态路径适配
