/** The only SolidJS/library boundary. All durable data comes from Nanobot. */
import { KLineChartPro, type Datafeed } from "@klinecharts/pro";
import { init } from "klinecharts";
import "@klinecharts/pro/dist/klinecharts-pro.css";
import type { CloudChartState } from "./contract";

export function mountCloudChart(container: HTMLElement, state: CloudChartState, datafeed: Datafeed): () => void {
  const calendar: Record<string, [number, string]> = { D: [1, "day"], W: [1, "week"], M: [1, "month"] };
  const unit = /^([SMH])(\d+)$/.exec(state.timeframe);
  const units: Record<string, string> = { S: "second", M: "minute", H: "hour" };
  const [multiplier, timespan] = calendar[state.timeframe] ?? (unit ? [Number(unit[2]), units[unit[1]]] : [1, "hour"]);
  const period = { multiplier, timespan, text: state.timeframe };
  const pro = new KLineChartPro({ container, symbol: { ticker: state.provider_instrument, name: state.canonical_instrument },
    period, periods: [period], timezone: "UTC", locale: "en-US", mainIndicators: state.studies.filter(name => ["MA", "EMA", "BOLL", "SAR"].includes(name)), subIndicators: state.studies.filter(name => !["MA", "EMA", "BOLL", "SAR"].includes(name)),
    drawingBarVisible: false, datafeed: { ...datafeed, getHistoryKLineData: async (...args) => {
      const data = await datafeed.getHistoryKLineData(...args);
      const range = state.visible_range;
      if (range) window.setTimeout(() => {
        if (disposed) return;
        const core = getCore();
        const [from, to] = range;
        const visible = data.filter(candle => candle.timestamp >= from && candle.timestamp <= to);
        if (core && visible.length) { core.setBarSpace(container.clientWidth / visible.length); core.scrollToTimestamp(to, 0); }
      }, 0);
      return data;
    } } });
  let disposed = false;
  const getCore = () => {
    const widget = container.querySelector<HTMLElement>(".klinecharts-pro-widget");
    const coreId = widget?.getAttribute("k-line-chart-id");
    if (widget && coreId) widget.id = coreId;
    return widget && coreId ? init(widget) : null;
  };
  const timer = window.setTimeout(() => {
    if (disposed) return;
    const core = getCore();
    if (!core) return;
    for (const annotation of state.annotations) {
      const names: Record<string, string> = { horizontal_line: "horizontalStraightLine", trend_line: "segment", price_zone: "rect", marker: "simpleAnnotation", note: "simpleAnnotation", entry: "simpleTag", stop: "simpleTag", target: "simpleTag" };
      core.createOverlay({ id: annotation.id, name: names[annotation.type] ?? "horizontalStraightLine", lock: true,
        points: annotation.points.map(point => ({ timestamp: point.timestamp ?? Date.now(), value: Number(point.value) })),
        extendData: annotation.text });
    }
  }, 0);
  return () => {
    disposed = true;
    window.clearTimeout(timer);
    pro.destroy();
    container.replaceChildren();
  };
}
