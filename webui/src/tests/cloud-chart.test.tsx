import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CloudChart } from "@/components/charts/CloudChart";
import { parseChartReference } from "@/components/charts/contract";
import type { Datafeed } from "@klinecharts/pro";

const mocks = vi.hoisted(() => ({ read: vi.fn(), destroy: vi.fn(), mount: vi.fn(), update: vi.fn(), subscribe: vi.fn(),
  capabilities: ["webui.cloud-chart.prices.v1"], client: { status: "open", onStatus: vi.fn() } }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "client-token", client: mocks.client, webuiCapabilities: mocks.capabilities }) }));
vi.mock("@/lib/api", () => ({ fetchCloudChart: mocks.read, fetchChartCandles: vi.fn(), updateCloudChart: mocks.update, subscribeChartPrices: mocks.subscribe }));
vi.mock("@/components/charts/pro-adapter", () => ({ mountCloudChart: mocks.mount }));
const chartId = `chart_${"a".repeat(32)}`;
const reference = JSON.stringify({ chart_id: chartId, session_key: "websocket:main" });
const saved = { id: chartId, revision: 4, canonical_instrument: "gold-usd", provider_instrument: "XAU_USD", timeframe: "H1", session_key: "websocket:main", annotations: [], studies: [] };

describe("Persistent Cloud Chart", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.read.mockResolvedValue(saved); mocks.mount.mockReset().mockReturnValue(mocks.destroy);
    mocks.capabilities = ["webui.cloud-chart.prices.v1"];
    mocks.subscribe.mockResolvedValue({ subscribed: true });
    mocks.client.onStatus.mockImplementation(callback => { callback("open"); return vi.fn(); }); });
  it("restores backend state after unmount/remount and cleans library ownership", async () => {
    const first = render(<CloudChart reference={reference} />);
    await waitFor(() => expect(mocks.mount).toHaveBeenCalled());
    first.unmount();
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
    render(<CloudChart reference={reference} />);
    await screen.findByText("gold-usd");
    expect(mocks.read).toHaveBeenLastCalledWith("client-token", chartId, "websocket:main");
    expect(mocks.mount.mock.calls.at(-1)?.[1].revision).toBe(4);
  });
  it("rejects executable or invalid chart references", () => {
    expect(parseChartReference('{"chart_id":"javascript:alert(1)","session_key":"websocket:main"}')).toBeNull();
    expect(parseChartReference("bad json")).toBeNull();
  });
  it("updates quotes and candles without remounting the chart and releases its subscription", async () => {
    const candle = vi.fn();
    mocks.mount.mockImplementation((_container, _chart, feed: Datafeed) => {
      feed.subscribe({ ticker: "XAU_USD" }, { multiplier: 1, timespan: "hour", text: "H1" }, candle);
      return mocks.destroy;
    });
    const view = render(<CloudChart reference={reference} />);
    await waitFor(() => expect(mocks.subscribe).toHaveBeenCalledTimes(1));
    const subscriptionId = mocks.subscribe.mock.calls[0][3];
    const time = new Date().toISOString();
    act(() => window.dispatchEvent(new CustomEvent("nanobot-cloud-chart-price", { detail: {
      event: "cloud_chart_price", chart_id: chartId, session_key: "websocket:main", subscription_id: subscriptionId,
      timeframe: "H1", status: "live", quote: { time, fetched_at: time, bid: "2700.10", ask: "2700.20", provider_instrument: "XAU_USD", source: "oanda" },
      candle: { time, open: "2699", high: "2701", low: "2698", close: "2700.15", volume: null, complete: false }, provisional: true,
    } })));
    expect(await screen.findByLabelText("Live market quote")).toHaveTextContent("2700.10 / Ask 2700.20");
    expect(candle).toHaveBeenCalledWith(expect.objectContaining({ close: 2700.15 }));
    expect(mocks.mount).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(mocks.subscribe.mock.calls.at(-1)?.[4]).toBe(false);
    expect(mocks.destroy).toHaveBeenCalledTimes(1);
  });
  it("keeps historical charts usable on an older host without sending unsupported subscriptions", async () => {
    mocks.capabilities = ["webui.core.v1"];
    mocks.mount.mockImplementation((_container, _chart, feed: Datafeed) => {
      feed.subscribe({ ticker: "XAU_USD" }, { multiplier: 1, timespan: "hour", text: "H1" }, vi.fn());
      return mocks.destroy;
    });
    const view = render(<CloudChart reference={reference} />);
    expect(await screen.findByText("Live pricing needs a gateway update.")).toBeInTheDocument();
    expect(mocks.subscribe).not.toHaveBeenCalled();
    view.unmount();
  });
});
