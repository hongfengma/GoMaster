// 围棋教练 AI 复盘 - Electron 桌面外壳入口（CommonJS，.cjs 以兼容 package.json 的 "type":"module"）
//
// 启动流程：
//   1) 定位打包资源里的 server.py（开发环境在 frontend/ 根，打包后在 resources/ 下）
//   2) spawn 本地 Python 后端（python server.py 8765），并把 server 的工作目录切到资源目录
//   3) 轮询 127.0.0.1:8765 直到就绪，再 loadURL
//   4) 窗口关闭 / app 退出时 kill 后端进程，避免残留
//
// 说明：Python 运行时依赖本机 PATH 中的 python（老马本机已具备）。
// 打包后 server.py / src / deps / .env 通过 --extra-resource 放到 resources/ 下（asar 外，可写）。
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const net = require("net");

const SERVER_PORT = 8765;
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

let serverProc = null;

// 定位 server.py 所在目录：打包后优先 resources/，开发态回退项目根
function findServerRoot() {
  const resources = process.resourcesPath || "";
  const candidates = [
    path.join(resources, "server.py"),
    path.join(resources, "src", "review.py"),
    path.join(app.getAppPath(), "..", "server.py"),
    path.join(__dirname, "..", "..", "server.py"),
    path.join(__dirname, "..", "server.py"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) return path.dirname(c);
  }
  return null;
}

// 探测可用的 python 命令（依赖本机 PATH）。用 spawnSync 同步探测，
// 命令不存在时 spawnSync 会在 r.error 上反映，避免 spawn 异步报错导致探测失效。
// Windows 上优先试 py 启动器（python 不一定在 PATH）。
function findPython() {
  const names = ["py", "python", "python3"];
  for (const n of names) {
    try {
      const r = spawnSync(n, ["--version"], { stdio: "ignore" });
      if (r.error) continue; // 命令不存在 / 无法启动
      return n;
    } catch (_) {
      continue;
    }
  }
  return "py"; // 兜底：交给系统报错提示
}

function waitPort(port, timeoutMs) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tryOnce = () => {
      const sock = net.connect(port, "127.0.0.1");
      sock.on("connect", () => {
        sock.destroy();
        resolve(true);
      });
      sock.on("error", () => {
        sock.destroy();
        if (Date.now() - start > timeoutMs) reject(new Error("后端服务启动超时"));
        else setTimeout(tryOnce, 500);
      });
    };
    tryOnce();
  });
}

async function startBackend() {
  const root = findServerRoot();
  if (!root) {
    console.error("[electron] 找不到 server.py，请确认打包资源完整");
    return;
  }
  const py = findPython();
  console.log(`[electron] 启动后端: ${py} server.py ${SERVER_PORT} (cwd=${root})`);
  serverProc = spawn(py, ["server.py", String(SERVER_PORT)], {
    cwd: root,
    stdio: ["ignore", "pipe", "pipe"],
  });
  serverProc.stdout.on("data", (d) => console.log("[server]", d.toString().trim()));
  serverProc.stderr.on("data", (d) => console.error("[server-err]", d.toString().trim()));
  serverProc.on("exit", (code) => console.log(`[server] 进程退出 code=${code}`));

  try {
    await waitPort(SERVER_PORT, 30000);
    console.log("[electron] 后端端口就绪");
  } catch (e) {
    console.error("[electron]", e.message);
  }
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#f5f1e8",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(SERVER_URL);
  // win.webContents.openDevTools();
}

app.whenReady().then(async () => {
  await startBackend();
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (serverProc) {
    try {
      serverProc.kill();
    } catch (_) {}
  }
  if (process.platform !== "darwin") app.quit();
});
