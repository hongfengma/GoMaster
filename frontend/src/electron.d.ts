// Electron 预加载桥接的类型声明（运行期由 preload.cjs 注入 window.electronAPI）
interface ElectronAPI {
  /** 把报告各区块的截图（PNG dataURL 数组，按顺序）交由主进程拼成图片 PDF 并存盘。 */
  exportReportPDF: (
    images: string[]
  ) => Promise<{ ok: boolean; path?: string; error?: string }>;
  /** 打开文件选择对话框，挑选 KataGo 神经网络权重文件（.bin.gz/.bin），返回绝对路径或 null。 */
  selectWeightFile: () => Promise<string | null>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
