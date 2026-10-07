/** The only SolidJS/library boundary. All durable data comes from Nanobot. */
import { KLineChartPro, type Datafeed } from "@klinecharts/pro";
import { init } from "klinecharts";
import "@klinecharts/pro/dist/klinecharts-pro.css";
import type { CloudChartState } from "./contract";

export function mountCloudChart(container: HTMLElement, state: CloudChartState, datafeed: Datafeed): () => void {
  const units: Record<string, [number, string]> = {
    M1: [1, "minute"], M5: [5, "minute"], M15: [15, "minute"], M30: [30, "minute"],
    H1: [1, "hour"], H4: [4, "hour"], D: [1, "day"], W: [1, "week"], M: [1, "month"],
  };
  const [multiplier, timespan] = units[state.timeframe] ?? [1, "hour"];
  const period = { multiplier, timespan, text: state.timeframe };
  const pro = new KLineChartPro({ container, symbol: { ticker: state.provider_instrument, name: state.canonical_instrument },
    period, periods: [period], timezone: "UTC", locale: "en-US", mainIndicators: [], subIndicators: [],
    drawingBarVisible: false, datafeed });
  let disposed = false;
  const timer = window.setTimeout(() => {
    if (disposed) return;
    const widget = container.querySelector<HTMLElement>(".klinecharts-pro-widget");
    const coreId = widget?.getAttribute("k-line-chart-id");
    // v9 init returns its cached instance by DOM id; Pro sets the attribute.
    if (widget && coreId) widget.id = coreId;
    const core = widget && coreId ? init(widget) : null;
    if (!core) return;
    for (const annotation of state.annotations) {
      const names: Record<string, string> = { horizontal_line: "horizontalStraightLine", trend_line: "segment", price_zone: "rect" };
      core.createOverlay({ id: annotation.id, name: names[annotation.type] ?? "horizontalStraightLine", lock: true,
        points: annotation.points.map(point => ({ timestamp: point.timestamp ?? Date.now(), value: Number(point.value) })),
        extendData: { text: annotation.text } });
    }
  }, 0);
  return () => {
    disposed = true;
    window.clearTimeout(timer);
    pro.destroy();
    container.replaceChildren();
  };
}
