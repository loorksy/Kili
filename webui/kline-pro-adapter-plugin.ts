/** Minimal build-time lifecycle patch for pinned Apache-2.0 @klinecharts/pro 0.1.1.
 * No installed files are edited. Fail closed if the pinned bundle changes.
 */
import { createHash } from "node:crypto";
import type { Plugin } from "vite";

export function patchKlinePro(source: string): string {
  const digest = createHash("sha256").update(source).digest("hex");
  if (digest !== "c0e29e80385382b35e12781f60ff01db01475dfb7d2da30b10a406935d65cb5c") {
    throw new Error("Pinned KLineChart Pro bundle changed; review the lifecycle patch");
  }
  return source.replace("    H5(() => d(Dl, {", "    this.__nanobotDispose = H5(() => d(Dl, {")
    .replace("  setTheme(t) {\n", "  destroy() { this.__nanobotDispose?.(); this.__nanobotDispose = null; }\n  setTheme(t) {\n");
}

export function patchKlineViewport(source: string): string {
  const digest = createHash("sha256").update(source).digest("hex");
  if (digest !== "313a26786af901e2b5b93c16ac002c6ceeebb54ecc9b6a55e386f1b31805ca5d") {
    throw new Error("Pinned KLineChart bundle changed; review the viewport bounds patch");
  }
  const limits = "var BarSpaceLimitConstants = {\n    MIN: 1,\n    MAX: 50\n};";
  if (!source.includes(limits)) throw new Error("Pinned viewport bounds missing");
  return source.replace(limits, "var BarSpaceLimitConstants = {\n    MIN: 0.01,\n    MAX: 10000\n};");
}

export function klineProLifecycle(): Plugin {
  return {
    name: "nanobot-kline-pro-lifecycle", enforce: "pre",
    transform(source, id) {
      if (id.endsWith("/@klinecharts/pro/dist/klinecharts-pro.js")) return patchKlinePro(source);
      if (id.endsWith("/klinecharts/dist/index.esm.js")) return patchKlineViewport(source);
    },
  };
}
