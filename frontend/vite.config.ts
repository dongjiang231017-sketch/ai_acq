import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // 相对路径：打包后 Electron 用 file:// 加载 dist/index.html，绝对路径 /assets 会指向
  // 文件系统根导致白屏。相对 ./assets 在 file:// 和 http 下都成立。
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
  },
});
