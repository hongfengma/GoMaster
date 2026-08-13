// Electron 预加载脚本（安全桥接，默认仅暴露版本信息；如需调用本地能力再扩展）
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("appInfo", {
  electron: process.versions.electron,
  platform: process.platform,
});
