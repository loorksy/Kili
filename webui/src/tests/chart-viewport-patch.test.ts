import fs from "node:fs";
import { describe, it, expect } from "vitest";
import { patchKlineViewport } from "../../kline-pro-adapter-plugin";

describe("Pinned semantic viewport bounds", () => {
  it("extends bar-spacing bounds without changing installed library files or defaults", () => {
    const path = "node_modules/klinecharts/dist/index.esm.js";
    const original = fs.readFileSync(path, "utf8");
    const transformed = patchKlineViewport(original);
    expect(transformed).toContain("MIN: 0.01,\n    MAX: 10000");
    expect(transformed).toContain("var DEFAULT_BAR_SPACE = 8;");
    expect(fs.readFileSync(path, "utf8")).toBe(original);
    expect(() => patchKlineViewport(original + "modified")).toThrow("Pinned KLineChart bundle changed");
  });
});
