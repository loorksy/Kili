import { useEffect, useRef, useState } from "react";
import type { Datafeed } from "@klinecharts/pro";
import { useClient } from "@/providers/ClientProvider";
import { fetchCloudChart, fetchChartCandles, updateCloudChart } from "@/lib/api";
import { parseChartReference, type CloudChartState } from "./contract";
import { mountCloudChart } from "./pro-adapter";

export function CloudChart({ reference }: { reference: string }) {
  const parsed = parseChartReference(reference);
  const chartId = parsed?.chart_id;
  const sessionKey = parsed?.session_key;
  const { client, token } = useClient();
  const [chart, setChart] = useState<CloudChartState | null>(null);
  const [error, setError] = useState("");
  const [drawingTool, setDrawingTool] = useState("");
  const [price, setPrice] = useState("");
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!chartId || !sessionKey) return;
    let active = true;
    const load = () => fetchCloudChart(token, chartId, sessionKey).then(value => { if (active) { setChart(previous => previous && JSON.stringify(previous) === JSON.stringify(value) ? previous : value); setError(""); } })
      .catch(() => { if (active) setError("Chart unavailable. Reconnect and try again."); });
    void load();
    const refresh = (event: Event) => {
      if (event instanceof CustomEvent && event.detail?.chart_id === chartId && !["cursor", "select_drawing_tool"].includes(event.detail.operation)) void load();
    };
    window.addEventListener("nanobot-cloud-chart-updated", refresh);
    window.addEventListener("online", load);
    return () => { active = false; window.removeEventListener("nanobot-cloud-chart-updated", refresh); window.removeEventListener("online", load); };
  }, [chartId, sessionKey, token]);
  useEffect(() => {
    if (!chart || !container.current || !chartId || !sessionKey) return;
    let closed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const stopFeed = () => { if (timer) clearTimeout(timer); timer = undefined; };
    const feed: Datafeed = {
      searchSymbols: async () => [{ ticker: chart.provider_instrument, name: chart.canonical_instrument }],
      getHistoryKLineData: async (_symbol, _period, _from, to) => {
        const page = await fetchChartCandles(token, chartId, sessionKey, new Date(chart.visible_range ? Math.min(chart.visible_range[1] + 1, to) : to).toISOString(), chart.candle_count ?? 200);
        if (closed) return [];
        return page.candles.map(c => ({ timestamp: Date.parse(c.time), open: Number(c.open), high: Number(c.high),
          low: Number(c.low), close: Number(c.close), volume: c.volume ?? 0 }));
      },
      subscribe: (_symbol, _period, callback) => {
        stopFeed();
        const refresh = async () => {
          if (closed) return;
          try {
            if (!document.hidden) {
              const page = await fetchChartCandles(token, chartId, sessionKey, undefined, 2);
              if (!closed) {
                for (const c of page.candles) callback({ timestamp: Date.parse(c.time), open: Number(c.open),
                  high: Number(c.high), low: Number(c.low), close: Number(c.close), volume: c.volume ?? 0 });
                setError(page.stale ? "Showing cached market data; provider unavailable." : "");
              }
            }
          } catch { if (!closed) setError("Market updates unavailable. Retrying…"); }
          if (!closed) timer = setTimeout(() => void refresh(), 30_000);
        };
        timer = setTimeout(() => void refresh(), 30_000);
      },
      unsubscribe: stopFeed,
    };
    const destroy = mountCloudChart(container.current, chart, feed, { selectedTool: drawingTool, onCrosshair: point => {
      void updateCloudChart(client, sessionKey, { operation: "report_crosshair", chart_id: chart.id, pointer_pane: point?.pane, points: point ? [{ timestamp: point.timestamp, value: point.value }] : undefined }).catch(() => undefined);
    }, onDrawing: drawing => {
      void updateCloudChart(client, sessionKey, { operation: drawing.id ? "update_annotation" : "add_annotation",
        chart_id: chart.id, expected_revision: chart.revision, annotation_id: drawing.id, object_revision: drawing.object_revision,
        annotation_type: "drawing", drawing_name: drawing.name, points: drawing.points })
        .then(updated => { if (!closed) { setDrawingTool(""); setChart(updated); setError(""); } })
        .catch(() => { if (!closed) setError("Drawing changed. Reopen the chart before editing."); });
    } });
    return () => { closed = true; stopFeed(); destroy(); };
  }, [chart, chartId, sessionKey, token, drawingTool, client]);
  async function change(operation: Record<string, unknown>) {
    if (!chart || !sessionKey) return;
    try {
      const updated = await updateCloudChart(client, sessionKey, { ...operation, chart_id: chart.id, expected_revision: chart.revision });
      setChart(updated); setError("");
    } catch { setError("Chart changed or is unavailable. Reopen it before editing."); }
  }
  if (!parsed) return <p>Invalid chart reference.</p>;
  return <section className="my-3 min-w-0 overflow-hidden rounded-xl border border-border bg-background" aria-label="Persistent market chart">
    <div className="flex flex-wrap items-center gap-2 p-2 text-xs">
      <span>{chart?.canonical_instrument ?? "Loading chart…"}</span>
      <span className="text-muted-foreground">OANDA</span>
      {chart && <select aria-label="Chart timeframe" value={chart.timeframe} onChange={e => void change({ operation: "set_timeframe", timeframe: e.target.value })}>
        {["M1", "M5", "M15", "M30", "H1", "H4", "D", "W", "M"].map(tf => <option key={tf}>{tf}</option>)}
      </select>}
      {chart && <select aria-label="Agent chart animation" value={chart.layout?.agent_animation_mode ?? "fast"} onChange={e => void change({ operation: "set_animation_mode", animation_mode: e.target.value })}>
        <option value="normal">Visible agent</option><option value="fast">Fast agent</option><option value="instant">Instant agent</option>
      </select>}
      {!!chart?.drawing_tools?.length && <select aria-label="Chart drawing tool" value={drawingTool} onChange={e => setDrawingTool(e.target.value)}>
        <option value="">Draw…</option>{chart.drawing_tools.map(tool => <option key={tool.id} value={tool.id}>{tool.id}</option>)}
      </select>}
    </div>
    {error && <p className="p-2 text-xs text-destructive" role="status">{error}</p>}
    <div ref={container} className="h-[360px] w-full min-w-0 sm:h-[440px]" />
    <div className="flex flex-wrap gap-2 p-2 text-xs">
      <input aria-label="Annotation price" className="w-28 rounded border bg-background px-2" value={price} onChange={e => setPrice(e.target.value)} placeholder="Price" />
      <button disabled={!chart || !/^[0-9]+(?:\.[0-9]+)?$/.test(price)} onClick={() => void change({ operation: "add_annotation", annotation_type: "horizontal_line", points: [{ value: price }], text: "User price level" })}>Save price level</button>
      {chart?.annotations.map(a => <span key={a.id} className="text-muted-foreground" title={`${a.origin ?? "NANOBOT"} · ${new Date(a.updated_at).toLocaleString()}`}>{a.text || a.type}{["USER", "IMPORT"].includes(a.origin ?? "") && <label className="ml-1"><input type="checkbox" checked={a.agent_editable ?? false} aria-label={`Allow Nanobot to edit ${a.text || a.type}`} onChange={e => void change({ operation: "configure_annotation", annotation_id: a.id, object_revision: a.revision, agent_editable: e.target.checked })} /> Agent edits</label>}</span>)}
    </div>
  </section>;
}
