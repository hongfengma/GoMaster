// Electron 预加载脚本（安全桥接）：仅暴露必要的本地能力给渲染进程
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("appInfo", {
  electron: process.versions.electron,
  platform: process.platform,
});

// 导出报告为 PDF：把报告 HTML + 样式字符串交由主进程生成并存盘
contextBridge.exposeInMainWorld("electronAPI", {
  exportReportPDF: (html, css) =>
    ipcRenderer.invoke("export-report-pdf", { html, css }),
  selectWeightFile: () => ipcRenderer.invoke("select-weight-file"),
});
