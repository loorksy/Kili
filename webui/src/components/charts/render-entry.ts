/** Trusted chart-only entry. No URL, network datafeed, script or navigation input. */
import type { Datafeed } from "@klinecharts/pro";
import { mountCloudChart } from "./pro-adapter";
import type { CloudChartState } from "./contract";

interface Snapshot {
  chart: CloudChartState;
  candles: { time: string; open: string; high: string; low: string; close: string; volume?: number | null }[];
  temporary_indicators: NonNullable<CloudChartState["indicator_instances"]>;
  series: NonNullable<CloudChartState["computed_series"]>;
}
export async function render(scene: Snapshot): Promise<string> {
  const container = document.getElementById("chart");
  if (!container) throw new Error("Chart container missing");
  const data = scene.candles.map(c => ({ timestamp: Date.parse(c.time), open: Number(c.open), high: Number(c.high),
    low: Number(c.low), close: Number(c.close), volume: c.volume ?? 0 }));
  const datafeed: Datafeed = { searchSymbols: async () => [], getHistoryKLineData: async () => data,
    subscribe: () => {}, unsubscribe: () => {} };
  // Plot the exact structured calculation (including pre-viewport warm-up)
  // for both built-ins and custom indicators. Do not recalculate a truncated
  // window with different initial conditions just for the exported picture.
  const instances = Array.from(new Map(scene.series.map(s => [s.instance_id, s])).values());
  const state: CloudChartState = { ...scene.chart, studies: [], temporary_indicator_instances: [],
    indicator_instances: instances.map(s => ({ id: s.instance_id, indicator_id: `indicator_export_${s.instance_id}`,
      calc_params: [], pane: s.pane === "main" ? "main" : "separate", visible: true })),
    computed_series: scene.series, computed_timestamps: data.map(c => c.timestamp) };
  await document.fonts.ready;
  const mount = mountCloudChart(container, state, datafeed);
  try {
    await mount.ready;
    const picture = mount.picture();
    const image = new Image();
    image.src = picture;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = container.clientWidth; canvas.height = container.clientHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Chart export unavailable");
    context.fillStyle = "#0f172a"; context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, canvas.height - image.height);
    context.fillStyle = "#fff"; context.font = "14px NanobotChart, sans-serif";
    context.fillText(`${state.provider_instrument} · ${state.timeframe} · ${state.provider === "metaapi" ? "Broker" : "Archived OANDA"}`, 16, 23);
    return canvas.toDataURL("image/png");
  }
  finally { mount(); }
}
