// Electron 预加载脚本（安全桥接）：仅暴露必要的本地能力给渲染进程
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("appInfo", {
  electron: process.versions.electron,
  platform: process.platform,
});

// 导出报告为 PDF：把报告各区块截图（PNG dataURL 数组）交由主进程拼成图片 PDF 并存盘
contextBridge.exposeInMainWorld("electronAPI", {
  exportReportPDF: (images) =>
    ipcRenderer.invoke("export-report-pdf", { images }),
  selectWeightFile: () => ipcRenderer.invoke("select-weight-file"),
});
