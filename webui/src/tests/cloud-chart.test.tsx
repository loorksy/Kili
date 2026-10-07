import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CloudChart } from "@/components/charts/CloudChart";
import { parseChartReference } from "@/components/charts/contract";

const mocks = vi.hoisted(() => ({ read: vi.fn(), destroy: vi.fn(), mount: vi.fn(), update: vi.fn() }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ token: "client-token", client: {} }) }));
vi.mock("@/lib/api", () => ({ fetchCloudChart: mocks.read, fetchChartCandles: vi.fn(), updateCloudChart: mocks.update }));
vi.mock("@/components/charts/pro-adapter", () => ({ mountCloudChart: mocks.mount }));
const chartId = `chart_${"a".repeat(32)}`;
const reference = JSON.stringify({ chart_id: chartId, session_key: "websocket:main" });
const saved = { id: chartId, revision: 4, canonical_instrument: "gold-usd", provider_instrument: "XAU_USD", timeframe: "H1", session_key: "websocket:main", annotations: [], studies: [] };

describe("Persistent Cloud Chart", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.read.mockResolvedValue(saved); mocks.mount.mockReturnValue(mocks.destroy); });
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
});
