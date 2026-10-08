import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NanobotClient } from "@/lib/nanobot-client";
import { observeChartPrices, type ChartPriceEvent } from "@/components/charts/live-feed";

const mocks = vi.hoisted(() => ({ subscribe: vi.fn() }));
vi.mock("@/lib/api", () => ({ subscribeChartPrices: mocks.subscribe }));

describe("Live chart stream on the existing socket", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-07T19:00:00Z")); mocks.subscribe.mockReset().mockResolvedValue({ subscribed: true }); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  function setup() {
    const client = new NanobotClient({ url: "ws://localhost/ws", reconnect: false });
    let connection: (status: "open" | "reconnecting") => void = () => undefined;
    const remove = vi.fn();
    vi.spyOn(client, "status", "get").mockReturnValue("open");
    vi.spyOn(client, "onStatus").mockImplementation(callback => {
      connection = callback; callback("open"); return remove;
    });
    const prices = vi.fn(), statuses = vi.fn();
    const stop = observeChartPrices(client, "chart_a", "websocket:main", prices, statuses);
    const id = mocks.subscribe.mock.calls.at(-1)?.[3] as string;
    const send = (changes: Partial<ChartPriceEvent> = {}) => {
      const value: ChartPriceEvent = { event: "cloud_chart_price", chart_id: "chart_a", session_key: "websocket:main",
        subscription_id: id, timeframe: "H1", status: "live", quote: { bid: "2700.10", ask: "2700.20", time: "2026-10-07T19:00:00Z",
          fetched_at: "2026-10-07T19:00:00Z", provider_instrument: "XAU_USD", source: "oanda" }, ...changes };
      window.dispatchEvent(new CustomEvent("nanobot-cloud-chart-price", { detail: value }));
    };
    return { prices, statuses, stop, send, connection: (status: "open" | "reconnecting") => connection(status), remove };
  }

  it("delivers immediately, isolates subscriptions and rejects old ticks without polling", () => {
    const test = setup();
    test.send();
    expect(test.prices).toHaveBeenCalledTimes(1);
    expect(test.statuses).toHaveBeenLastCalledWith("live");
    test.send();
    test.send({ chart_id: "other" });
    test.send({ session_key: "websocket:other" });
    test.send({ subscription_id: "old-socket" });
    expect(test.prices).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(22_000);
    expect(test.statuses).toHaveBeenLastCalledWith("stale");
    expect(mocks.subscribe).toHaveBeenCalledTimes(1);
    test.stop();
    expect(mocks.subscribe).toHaveBeenLastCalledWith(expect.anything(), "chart_a", "websocket:main", expect.any(String), false);
    expect(test.remove).toHaveBeenCalledOnce();
    test.send();
    expect(test.prices).toHaveBeenCalledTimes(1);
  });

  it("resubscribes after reconnect and never labels an old snapshot live", () => {
    const test = setup();
    test.connection("reconnecting");
    expect(test.statuses).toHaveBeenLastCalledWith("reconnecting");
    vi.advanceTimersByTime(30_000);
    test.connection("open");
    expect(mocks.subscribe).toHaveBeenCalledTimes(2);
    test.send();
    expect(test.statuses).toHaveBeenLastCalledWith("stale");
    test.stop();
  });

  it("releases hidden charts and restores visible charts", () => {
    const test = setup();
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(mocks.subscribe.mock.calls.at(-1)?.[4]).toBe(false);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(mocks.subscribe.mock.calls.at(-1)?.[4]).toBe(true);
    test.stop();
  });
});
