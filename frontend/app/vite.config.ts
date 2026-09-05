import { fileURLToPath, URL } from "node:url";
import path from "node:path";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 产物固定输出到站端资源目录：station_edition/xrs/assets/frontend
// web_http_core 以 /ui/* 前缀托管该目录并做 SPA fallback。
const outDir = path.resolve(
  fileURLToPath(new URL("../../station_edition/xrs/assets/frontend", import.meta.url)),
);

export default defineConfig({
  plugins: [vue()],
  base: "/ui/",
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    sourcemap: false,
    target: "es2020",
  },
  server: {
    host: "127.0.0.1",
    port: 5199,
  },
});
