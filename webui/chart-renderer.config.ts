import { defineConfig } from "vite";
import { klineProLifecycle } from "./kline-pro-adapter-plugin";
import path from "node:path";

export default defineConfig({ publicDir: false, plugins: [klineProLifecycle()], define: { "process.env.NODE_ENV": '"production"' }, build: {
  outDir: path.resolve(__dirname, "../nanobot/charts/assets"), emptyOutDir: false,
  lib: { entry: path.resolve(__dirname, "src/components/charts/render-entry.ts"), name: "NanobotChartRender", formats: ["iife"], fileName: () => "chart-renderer.js" },
  rollupOptions: { output: { assetFileNames: "chart-renderer.[ext]" } },
} });
