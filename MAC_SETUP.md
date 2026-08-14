# 在单位 Mac 上继续开发「围棋教练 AI 复盘」

当前工作区已用 git 初始化（首个提交即 v0.6）。本指南说明如何把进度同步到单位 Mac，并在 Mac 上跑起来、继续开发。

> 跨平台要点：代码已做成"零外部依赖 + 路径自动探测"。`config.py` 不再硬编码 Windows 路径，KataGo 可执行文件、权重文件都会按平台自动查找。只需在 Mac 上各自准备好"KataGo 二进制"和"权重"（二者平台相关，不能跨机器拷贝 .exe）。

---

## 一、把代码弄到 Mac

### 方式 A：GitHub（推荐，双向同步最方便）
1. **Windows 本机（有网）** 推到 GitHub 仓库（默认分支已是 `master`，即最新 v0.7.7）：
   ```bash
   cd "C:\Users\mhf\WorkBuddy\围棋教练AI复盘"
   git remote -v                      # 确认 origin 指向 GitHub 上的 GoMaster 仓库
   git push -u origin master
   ```
   `.gitignore` 已排除权重(`*.bin.gz`)、KataGo 二进制、`.env`（含 DeepSeek Key）、上传文件等，只同步源码，仓库很小。
2. **Mac 上** 克隆（默认分支即 `master`，落地即为 v0.7.7 最新版）：
   ```bash
   git clone https://github.com/hongfengma/GoMaster.git
   cd GoMaster
   ```

### 方式 B：同步盘 / U 盘
直接拷贝整个 `围棋教练AI复盘` 文件夹到 Mac 也可。但**不要**拷贝 `deps/katago/`（Windows 的 `katago.exe` 在 Mac 用不了），Mac 端需单独下载 KataGo（见下）。

---

## 二、Mac 端环境准备

1. **Python 3.10+**：Mac 自带 3.9 偏旧，建议 `brew install python` 或 pyenv。
2. **KataGo（Mac 版）**：
   - 前往 https://github.com/lightvector/KataGo/releases/tag/v1.17.1
   - 下载 **macOS** 版本的压缩包（文件名通常含 `mac` / `universal`），解压得到 `katago` 可执行文件。
   - 放到 `deps/katago/katago`（注意**没有** `.exe` 后缀）。
   - `config.py` 会自动探测：找不到 `katago.exe` 时回退到 `deps/katago/katago`。
3. **小网络权重（CPU 提速关键！）**，二选一放到 `deps/`：
   - `g170-b10c128-s197428736-d67404019.bin.gz`（推荐，~11MB，棋力职业级以上）
     https://katagoarchive.org/g170/neuralnets/g170-b10c128-s197428736-d67404019.bin.gz
   - `g170-b6c96-s175395328-d26788732.bin.gz`（极快，~3.6MB，棋力约业余初级）
     https://katagoarchive.org/g170/neuralnets/g170-b6c96-s175395328-d26788732.bin.gz
   - `config.py` 候选顺序：b10c128 → b6c96 → 你的 b10c384（兜底），自动优先选小的。
4. **DeepSeek Key**：现已移出代码、改由 `.env` 读取（`.env` 已被 `.gitignore` 忽略，不会进仓库）。Mac 上克隆后需自行准备：
   ```bash
   cp .env.example .env
   # 然后编辑 .env，把 DEEPSEEK_API_KEY= 填上你的真实 Key
   ```
   `.env.example` 是模板（已进仓库），`.env` 含真实 Key（仅本机、不提交）。

---

## 三、运行

```bash
cd weiqi-coach
python3 server.py
```

浏览器打开 http://127.0.0.1:8765 ，点「载入示例棋谱」即可看到：带坐标的棋盘、失误手红圈、AI 推荐绿圈、后续变化带序号的黑白子、以及渲染后的 Markdown 讲解。

---

## 四、继续开发（React / Electron 路线）

- **npm 本身没问题**：沙箱实测 `npm install react` 3 秒成功，registry 可达。
- 之前"装不了 electron"是因其安装脚本要从 **GitHub 下载原生二进制**，而沙箱对 GitHub release 资产不可达；**Mac 本机有网可正常安装**。
- 前端代码已在 `frontend/`（Vite + React 19 + TypeScript + Zustand），**无需重建**：直接 `cd frontend && npm install && npm run dev` 即可本地调试；改完后用 `npm run electron:pack:mac` 重新打包（见第六节）。后端 `server.py` / `src/` 不动。

---

## 五、进度双向同步

- Mac 改完：`git add -A && git commit -m "..." && git push`
- 回 Windows：`git pull` 即可拿到最新
- 注意：权重和 KataGo 二进制**不进 git**，每台机器各自准备。

## 六、桌面打包成 macOS 应用（Electron）

代码已含 Electron 外壳（`frontend/electron/main.cjs` + `preload.cjs`），可打包成 `GoMaster.app` 双击运行。

### 前置（前面已备好）
- `deps/katago/katago`：**Mac 版** KataGo（无 `.exe` 后缀，eigenavx2 或 universal 构建）
- `deps/` 下至少一个 g170 二进制权重（跨平台通用，可与 Windows 共用同一份 `.bin.gz`）
- `.env`（DeepSeek Key）

### 打包（必须在 Mac 上执行；沙箱 Windows 打不出 Mac 包）
```bash
cd frontend
npm install                 # 装 electron/electron-packager + 前端依赖（Mac 有网正常）
npm run build               # 构建前端 dist
npm run electron:pack:mac   # 默认打 Intel(x64) 包 → dist-electron-mac/GoMaster-darwin-x64/GoMaster.app
# Apple 芯片(M1/M2/M3) 请改用：npm run electron:pack:mac:arm
```
> electron 原生二进制下载慢时，先执行：`export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"`。
> 打包会包含 `server.py`+`src`+`deps`+`.env`+`dist`；确保 Mac 本机 `deps/katago/katago`、`deps/*.bin.gz`、`.env` 已就位（详见第二节）。

### 首次打开（Gatekeeper）
未签名的 `.app` 会被拦（"无法验证开发者"）：
1. 右键 `GoMaster.app` → 打开 → 弹窗点「打开」；或
2. 终端 `xattr -cr "dist-electron-mac/GoMaster-darwin-x64/GoMaster.app"` 清除隔离属性后双击。
自用无需 Apple 开发者证书与公证。

### 运行原理
`GoMaster.app/Contents/Resources/` 内含 `server.py`+`src`+`deps`+`.env`+`dist`，`main.cjs` 用 `python3` 拉起后端（Mac 探活顺序已含 `python3`）。
