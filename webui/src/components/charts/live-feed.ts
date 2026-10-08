import type { NanobotClient } from "@/lib/nanobot-client";
import { subscribeChartPrices } from "@/lib/api";
import type { InboundEvent } from "@/lib/types";

export type ChartPriceEvent = Extract<InboundEvent, { event: "cloud_chart_price" }>;

/** Ephemeral quotes on the existing socket. No history polling or model calls. */
export function observeChartPrices(client: NanobotClient, chartId: string, sessionKey: string,
  onPrice: (event: ChartPriceEvent) => void, onStatus: (status: string) => void): () => void {
  const subscriptionId = crypto.randomUUID();
  let closed = false;
  let requested = false;
  let latest = -Infinity;
  let received = 0;
  const request = (subscribe: boolean) => {
    requested = subscribe;
    void subscribeChartPrices(client, chartId, sessionKey, subscriptionId, subscribe)
      .catch(() => { if (!closed && subscribe) onStatus("unavailable"); });
  };
  const connection = (status: string) => {
    if (closed) return;
    if (status === "open" && !document.hidden) {
      onStatus("connecting"); request(true);
    } else {
      requested = false; onStatus("reconnecting");
    }
  };
  const visibility = () => {
    if (document.hidden && requested) request(false);
    else if (!document.hidden) connection(client.status);
  };
  const update = (event: Event) => {
    if (!(event instanceof CustomEvent) || closed) return;
    const value = event.detail as ChartPriceEvent;
    if (value?.chart_id !== chartId || value.session_key !== sessionKey || value.subscription_id !== subscriptionId) return;
    if (!value.quote) {
      if (value.candles?.length) onPrice(value);
      else onStatus(value.status);
      return;
    }
    const timestamp = Date.parse(value.quote.time);
    if (!Number.isFinite(timestamp) || timestamp <= latest) return;
    latest = timestamp;
    received = Date.now();
    onPrice(value);
    onStatus(value.status === "live" && received - timestamp > 20_000 ? "stale" : value.status);
  };
  window.addEventListener("nanobot-cloud-chart-price", update);
  document.addEventListener("visibilitychange", visibility);
  const removeStatus = client.onStatus(connection);
  // This only ages the freshness label. It never requests market data.
  const timer = window.setInterval(() => {
    if (received && Date.now() - received > 20_000) onStatus("stale");
  }, 2000);
  return () => {
    closed = true;
    if (requested && client.status === "open") request(false);
    removeStatus();
    clearInterval(timer);
    window.removeEventListener("nanobot-cloud-chart-price", update);
    document.removeEventListener("visibilitychange", visibility);
  };
}
