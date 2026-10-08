/** The only SolidJS/library boundary. All durable data comes from Nanobot. */
import { KLineChartPro, type Datafeed } from "@klinecharts/pro";
import { init, registerIndicator, type Overlay } from "klinecharts";
import "@klinecharts/pro/dist/klinecharts-pro.css";
import type { CloudChartState } from "./contract";

const recentActions = new WeakMap<HTMLElement, CustomEvent>();

export interface DrawingEdit { id?: string; object_revision?: number; name: string; points: { timestamp: number; value: string }[] }
export interface ChartInteraction { selectedTool?: string; onDrawing?: (drawing: DrawingEdit) => void }
export function mountCloudChart(container: HTMLElement, state: CloudChartState, datafeed: Datafeed, interaction: ChartInteraction = {}): () => void {
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
    core.setOffsetRightDistance(state.right_spacing ?? 40);
    if (!state.visible_range) core.setBarSpace(container.clientWidth / (state.candle_count ?? 200));
    for (const instance of state.indicator_instances ?? []) {
      if (!instance.visible) continue;
      if (instance.indicator_id.startsWith("indicator_")) {
        const outputs = (state.computed_series ?? []).filter(s => s.instance_id === instance.id);
        const timestamps = state.computed_timestamps ?? [];
        const values = new Map(timestamps.map((time, i) => [time, Object.fromEntries(outputs.map(s => [s.name, s.values[i] === null ? undefined : Number(s.values[i])]))]));
        const name = "NANOBOT_" + instance.id;
        registerIndicator({ name, shortName: instance.indicator_id, calcParams: [],
          figures: outputs.map(s => ({ key: s.name, title: s.name, styles: () => ({ color: s.color }), type: s.kind === "histogram" ? "bar" as const : s.kind === "marker" ? "circle" as const : "line" as const })),
          calc: data => data.map(c => values.get(c.timestamp) ?? {}) });
        core.createIndicator(name, true, { id: instance.pane === "main" ? "candle_pane" : instance.id });
      } else {
        core.createIndicator({ name: instance.indicator_id, calcParams: instance.calc_params }, true, { id: instance.pane === "main" ? "candle_pane" : instance.id });
      }
    }
    const saveDrawing = (overlay: Overlay, id?: string, revision?: number) => {
      const points = overlay.points.map(point => ({ timestamp: point.timestamp ?? core.getDataList()[point.dataIndex ?? -1]?.timestamp, value: String(point.value) }));
      if (points.some(p => p.timestamp === undefined || !Number.isFinite(Number(p.value)))) return;
      interaction.onDrawing?.({ id, object_revision: revision, name: overlay.name, points: points.flatMap(p => typeof p.timestamp === "number" ? [{ timestamp: p.timestamp, value: p.value }] : []) });
    };
    if (interaction.selectedTool && state.drawing_tools?.some(tool => tool.id === interaction.selectedTool)) {
      core.createOverlay({ name: interaction.selectedTool, onDrawEnd: ({ overlay }) => { saveDrawing(overlay); return true; } });
    }
    for (const annotation of [...state.annotations, ...(state.temporary_annotations ?? [])]) {
      if (annotation.visible === false) continue;
      const names: Record<string, string> = { horizontal_line: "horizontalStraightLine", trend_line: "segment", price_zone: "rect", marker: "simpleAnnotation", note: "simpleAnnotation", entry: "simpleTag", stop: "simpleTag", target: "simpleTag" };
      core.createOverlay({ id: annotation.id, name: annotation.library_name ?? names[annotation.type] ?? "horizontalStraightLine", lock: annotation.locked ?? true,
        points: annotation.points.map(point => ({ timestamp: point.timestamp ?? Date.now(), value: Number(point.value) })),
        extendData: annotation.text, onPressedMoveEnd: ({ overlay }) => { saveDrawing(overlay, annotation.id, annotation.revision); return true; } });
    }
  }, 0);
  const cursor = document.createElement("div");
  cursor.textContent = "➤ Nanobot";
  cursor.setAttribute("aria-label", "Nanobot chart cursor");
  cursor.style.cssText = "position:absolute;left:0;top:0;z-index:10;pointer-events:none;color:#38bdf8;font-size:12px;display:none;transition:transform 120ms ease";
  container.style.position = "relative";
  container.appendChild(cursor);
  let hideTimer: ReturnType<typeof setTimeout> | undefined;
  const replay = (event: Event) => {
    if (!(event instanceof CustomEvent) || event.detail?.chart_id !== state.id || !event.detail.operation || Date.now() - event.detail.occurred_at > 5000) return;
    recentActions.set(container, event);
    const core = getCore();
    if (!core) return;
    const anchors: [number, string][] = event.detail.anchors ?? [];
    cursor.style.display = "block";
    cursor.textContent = "➤ Nanobot · " + event.detail.operation.replaceAll("_", " ");
    for (const [index, anchor] of anchors.entries()) {
      window.setTimeout(() => {
        if (disposed) return;
        const point = core.convertToPixel({ timestamp: anchor[0], value: Number(anchor[1]) }, { paneId: "candle_pane", absolute: true });
        if (!Array.isArray(point) && typeof point.x === "number" && typeof point.y === "number") cursor.style.transform = `translate(${point.x}px, ${point.y}px)`;
      }, index * 120);
    }
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { cursor.style.display = "none"; }, Math.min(1800, anchors.length * 120 + 700));
  };
  window.addEventListener("nanobot-cloud-chart-updated", replay);
  const recent = recentActions.get(container);
  if (recent) window.setTimeout(() => { if (!disposed) replay(recent); }, 100);
  return () => {
    window.removeEventListener("nanobot-cloud-chart-updated", replay);
    if (hideTimer) clearTimeout(hideTimer);
    disposed = true;
    window.clearTimeout(timer);
    pro.destroy();
    container.replaceChildren();
  };
}
