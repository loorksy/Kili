import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChartWorkspaceProvider, ChartWorkspaceButton, ChartWorkspaceReference } from "@/components/charts/ChartWorkspace";
import { MarketRecommendation } from "@/components/charts/MarketRecommendation";

const mocks = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn(), capabilities: ["webui.cloud-chart.workspace.v1"] }));
vi.mock("@/providers/ClientProvider", () => ({ useClient: () => ({ client: {}, token: "test-token", webuiCapabilities: mocks.capabilities }) }));
vi.mock("@/lib/api", () => ({ listCloudCharts: mocks.list, updateCloudChart: mocks.update }));
vi.mock("@/components/charts/CloudChart", () => ({ CloudChart: ({ reference }: { reference: string }) => <div data-testid="chart">{reference}</div> }));
const chartId = `chart_${"a".repeat(32)}`;
const saved = { chart_id: chartId, session_key: "websocket:main", instrument: "XAU_USD", timeframe: "H1" };
const reference = JSON.stringify(saved);
function Shell({ children }: { children?: React.ReactNode }) {
  return <ChartWorkspaceProvider sessionKey="websocket:main"><ChartWorkspaceButton />{children}</ChartWorkspaceProvider>;
}
describe("Conversation chart workspace", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.capabilities = ["webui.cloud-chart.workspace.v1"];
    mocks.list.mockResolvedValue({ charts: [saved], instruments: [{ name: "XAU_USD", display_name: "XAU/USD" }], market_unavailable: false }); });
  it("opens from the header without an agent call and collapses independently of chat", async () => {
    render(<Shell><p>Conversation remains visible</p></Shell>);
    expect(mocks.list).not.toHaveBeenCalled();
    expect(screen.queryByTestId("chart")).toBeNull();
    fireEvent.click(screen.getByLabelText("Open chart"));
    expect(await screen.findByTestId("chart")).toHaveTextContent(chartId);
    expect(screen.getByText("Conversation remains visible")).toBeVisible();
    fireEvent.click(screen.getByLabelText("Collapse chart"));
    expect(screen.queryByTestId("chart")).toBeNull();
    fireEvent.click(screen.getByLabelText("Open chart"));
    expect(await screen.findByTestId("chart")).toHaveTextContent(chartId);
  });
  it("agent reference opens one bottom chart and does not reopen after folding", async () => {
    const view = render(<Shell><ChartWorkspaceReference reference={reference} /></Shell>);
    expect(await screen.findByTestId("chart")).toHaveTextContent(chartId);
    expect(screen.getAllByTestId("chart")).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("Collapse chart"));
    view.rerender(<Shell><ChartWorkspaceReference reference={reference} /><p>Another tick</p></Shell>);
    expect(screen.queryByTestId("chart")).toBeNull();
    fireEvent.click(screen.getByText("View chart"));
    expect(await screen.findByTestId("chart")).toBeVisible();
  });
  it("creates a chart from the provider catalog without invoking the agent", async () => {
    mocks.list.mockResolvedValue({ charts: [], instruments: [{ name: "XAU_USD", display_name: "XAU/USD" }], market_unavailable: false });
    mocks.update.mockResolvedValue({ id: chartId, canonical_instrument: "XAU_USD", timeframe: "H1" });
    render(<Shell />);
    fireEvent.click(screen.getByLabelText("Open chart"));
    await screen.findByText("XAU/USD");
    fireEvent.change(screen.getByLabelText("Chart instrument"), { target: { value: "XAU_USD" } });
    fireEvent.click(screen.getByText("Open", { exact: true }));
    await waitFor(() => expect(mocks.update).toHaveBeenCalledWith({}, "websocket:main", {
      operation: "create", canonical_instrument: "XAU_USD", provider_instrument: "XAU_USD", timeframe: "H1" }));
    expect(await screen.findByTestId("chart")).toHaveTextContent(chartId);
  });
  it("gates new catalog requests on compatible gateway and rejects cross-conversation references", async () => {
    mocks.capabilities = [];
    render(<Shell><ChartWorkspaceReference reference={JSON.stringify({ ...saved, session_key: "websocket:other" })} /></Shell>);
    expect(screen.queryByLabelText("Open chart")).toBeNull();
    expect(screen.queryByTestId("chart")).toBeNull();
    expect(mocks.list).not.toHaveBeenCalled();
  });
});
describe("Display-only recommendation cards", () => {
  it.each(["BUY", "SELL", "WAIT", "WATCH", "AVOID"])("labels %s explicitly without execution buttons", intent => {
    render(<MarketRecommendation reference={JSON.stringify({ instrument: "XAU_USD", intent, summary: "Fixture analysis", entry: ["2700.10"], targets: ["2710"], stop_loss: "2695" })} />);
    expect(screen.getByLabelText("Market recommendation")).toHaveTextContent("2700.10");
    expect(screen.getByText("Analysis only. No trade executed or authorized. Outcomes are not guaranteed.")).toBeVisible();
    expect(screen.queryByText("Approve")).toBeNull();
    expect(screen.queryByText("Execute")).toBeNull();
  });
  it("recommendation opens its chart in the workspace without embedding another chart", async () => {
    render(<Shell><MarketRecommendation reference={JSON.stringify({ instrument: "XAU_USD", intent: "SELL", summary: "Fixture analysis", chart_id: chartId, session_key: saved.session_key })} /></Shell>);
    expect(await screen.findByTestId("chart")).toBeVisible();
    expect(screen.getAllByTestId("chart")).toHaveLength(1);
  });
  it("rejects invalid financial values and executable payloads", () => {
    render(<MarketRecommendation reference={JSON.stringify({ instrument: "gold", intent: "BUY", summary: "invalid", entry: ["NaN"] })} />);
    expect(screen.getByText("Invalid analysis card.")).toBeVisible();
  });
});
