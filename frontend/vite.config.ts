import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // WorkBuddy 沙箱的 safe-delete 会拦截 Vite 默认的 emptyDir，
    // 改为 false 避免构建失败；旧文件由 gitignore 忽略，不影响产物。
    emptyOutDir: false,
  },
})
