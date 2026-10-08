import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { mountCloudChart } from "@/components/charts/pro-adapter";
import type { CloudChartState } from "@/components/charts/contract";
import type { Datafeed } from "@klinecharts/pro";

const mocks = vi.hoisted(() => ({ core: { setOffsetRightDistance: vi.fn(), setBarSpace: vi.fn(),
  createOverlay: vi.fn(), createIndicator: vi.fn(), getDataList: vi.fn(() => [{ timestamp: 1000 }]),
  convertToPixel: vi.fn(() => ({ x: 50, y: 80 })) }, destroy: vi.fn(), register: vi.fn() }));
vi.mock("@klinecharts/pro", () => ({ KLineChartPro: class {
  constructor(options: { container: HTMLElement }) {
    const widget = document.createElement("div"); widget.className = "klinecharts-pro-widget";
    widget.setAttribute("k-line-chart-id", "core"); options.container.appendChild(widget);
  }
  destroy() { mocks.destroy(); }
} }));
vi.mock("klinecharts", () => ({ init: () => mocks.core, registerIndicator: mocks.register }));
const state: CloudChartState = { id: `chart_${"a".repeat(32)}`, revision: 0, canonical_instrument: "gold",
  provider_instrument: "XAU_USD", timeframe: "H1", session_key: "websocket:main", studies: [], annotations: [], candle_count: 100 };
const feed: Datafeed = { searchSymbols: async () => [], getHistoryKLineData: async () => [], subscribe: () => {}, unsubscribe: () => {} };

describe("Chart semantic adapter", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); });
  afterEach(() => { vi.useRealTimers(); });
  it("restores semantic viewport and ignores stale cursor events", () => {
    const container = document.createElement("div"); document.body.appendChild(container);
    const stop = mountCloudChart(container, state, feed);
    vi.runOnlyPendingTimers();
    expect(mocks.core.setOffsetRightDistance).toHaveBeenCalledWith(40);
    window.dispatchEvent(new CustomEvent("nanobot-cloud-chart-updated", { detail: {
      chart_id: state.id, operation: "add_annotation", occurred_at: Date.now(), anchors: [[1000, "2700.10"], [2000, "2710.20"]] } }));
    vi.advanceTimersByTime(200);
    expect(mocks.core.convertToPixel).toHaveBeenLastCalledWith({ timestamp: 2000, value: 2710.2 }, { paneId: "candle_pane", absolute: true });
    expect(container.querySelector('[aria-label="Nanobot chart cursor"]')?.getAttribute("style")).toContain("translate(50px, 80px)");
    stop(); expect(mocks.destroy).toHaveBeenCalledOnce(); expect(container.children.length).toBe(0);
    vi.advanceTimersByTime(6000);
    const stopAgain = mountCloudChart(container, state, feed); vi.runOnlyPendingTimers();
    expect(container.querySelector<HTMLElement>('[aria-label="Nanobot chart cursor"]')?.style.display).toBe("none");
    stopAgain(); container.remove();
  });
  it("projects saved semantic drawings and separate indicator panes", () => {
    const container = document.createElement("div");
    const stop = mountCloudChart(container, { ...state, annotations: [{ id: "a", type: "drawing", library_name: "rect", text: "zone", created_by: "main", updated_at: 0, visible: true, locked: true, points: [{ timestamp: 1000, value: "2700" }, { timestamp: 2000, value: "2710" }] }],
      indicator_instances: [{ id: "study_x", indicator_id: "RSI", calc_params: [6,12,24], pane: "separate", visible: true }] }, feed);
    vi.runOnlyPendingTimers();
    expect(mocks.core.createOverlay).toHaveBeenCalledWith(expect.objectContaining({ name: "rect", points: [{ timestamp: 1000, value: 2700 }, { timestamp: 2000, value: 2710 }] }));
    expect(mocks.core.createIndicator).toHaveBeenCalledWith({ name: "RSI", calcParams: [6,12,24] }, true, { id: "study_x" });
    stop();
  });
});
